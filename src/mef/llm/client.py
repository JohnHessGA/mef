"""LLM client — subprocess wrapper around the ``claude`` CLI.

The CLI returns a JSON envelope::

    {"type":"result","result":"<model output>","duration_ms":...,
     "total_cost_usd":...,"usage":{...},"modelUsage":{...}}

We extract ``.result`` (the model's text). For gate calls the model's text
is itself JSON; the caller parses it with helpers in ``mef.llm.gate``.

``call_claude`` never raises — it returns an ``LLMResponse`` with a clear
error field when something goes wrong. That lets the pipeline treat an
LLM outage as a soft failure ("unavailable") and ship anyway.

The provider is pluggable via config: ``mef.yaml → llm.provider``. Only
``claude-cli`` is implemented in v1; callers use ``call_llm`` so the
provider indirection is trivial to extend later.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from mef.config import load_app_config


DEFAULT_CLI_PATH = "/home/johnh/.local/bin/claude"
DEFAULT_MODEL = "haiku"
DEFAULT_TIMEOUT_S = 120

# Retry-on-timeout policy (only for the `claude-cli` provider).
# If the first call hits the subprocess timeout — NOT a crash, parse
# error, or missing binary — pause ``RETRY_PAUSE_S`` seconds and try
# once more at ``RETRY_TIMEOUT_S``. The Claude CLI sits in a slow
# right-tail for large prompts (11K+ chars commonly take 60-120s), and
# the first timeout is frequently a transient long-tail event rather
# than a real hang. One retry catches most of those without doubling
# worst-case wall-clock on genuine outages.
RETRY_TIMEOUT_S = 180
RETRY_PAUSE_S = 60


@dataclass
class LLMResponse:
    ok: bool
    text: str                              # raw model output (possibly fenced)
    error: Optional[str] = None
    latency_ms: int = 0
    model_duration_ms: Optional[int] = None
    cost_usd: Optional[float] = None
    token_input: Optional[int] = None
    token_output: Optional[int] = None
    model_name: Optional[str] = None
    provider: str = "claude-cli"


def call_llm(prompt: str, *, timeout_s: Optional[int] = None) -> LLMResponse:
    """Dispatch to whichever provider is configured in ``config/mef.yaml``.

    For ``claude-cli`` specifically: if the first attempt hits the
    subprocess timeout, pause ``RETRY_PAUSE_S`` and retry once with
    ``RETRY_TIMEOUT_S``. Any other error (binary missing, parse,
    non-zero exit) is returned immediately — those are not transient.
    """
    cfg = load_app_config().get("llm") or {}
    provider = cfg.get("provider", "claude-cli")
    timeout_s = timeout_s or int(cfg.get("timeout_s", DEFAULT_TIMEOUT_S))

    if provider == "claude-cli":
        cli_path = cfg.get("cli_path")
        model = cfg.get("model_hint", DEFAULT_MODEL)
        first = call_claude(prompt, cli_path=cli_path, model=model, timeout_s=timeout_s)
        if first.ok or not _is_timeout_error(first.error):
            return first
        # Transient-looking timeout on first attempt → pause + retry once.
        _sleep(RETRY_PAUSE_S)
        second = call_claude(
            prompt, cli_path=cli_path, model=model, timeout_s=RETRY_TIMEOUT_S,
        )
        if not second.ok and _is_timeout_error(second.error):
            second.error = (
                f"LLM timed out twice — first {timeout_s}s attempt and "
                f"{RETRY_TIMEOUT_S}s retry (after {RETRY_PAUSE_S}s pause) "
                f"both expired"
            )
        elif not second.ok:
            # Second attempt failed for a different reason — annotate so
            # audit sees the retry context rather than a bare second error.
            second.error = (
                f"LLM retry failed after first attempt timed out "
                f"({timeout_s}s): {second.error}"
            )
        return second
    return LLMResponse(
        ok=False, text="",
        error=f"unknown LLM provider: {provider!r} (set mef.yaml → llm.provider)",
        provider=provider,
    )


def _is_timeout_error(err: Optional[str]) -> bool:
    """Classify an LLMResponse.error as a subprocess-timeout outcome."""
    return bool(err) and "timed out" in err.lower()


def _sleep(seconds: int) -> None:
    """Indirection so tests can patch the pause to zero."""
    time.sleep(seconds)


def call_claude(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    cli_path: Optional[str] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> LLMResponse:
    """Send a prompt to the Claude CLI. Never raises — returns LLMResponse."""
    cli = (
        cli_path
        or os.environ.get("MEF_CLAUDE_PATH")
        or DEFAULT_CLI_PATH
    )
    argv = [cli, "-p", "--output-format", "json", "--model", model]

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return LLMResponse(
            ok=False, text="",
            error=f"claude CLI not found at {cli!r} "
                  "(set MEF_CLAUDE_PATH or install the Claude CLI)",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
    except subprocess.TimeoutExpired:
        return LLMResponse(
            ok=False, text="",
            error=f"claude CLI timed out after {timeout_s}s",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        return LLMResponse(
            ok=False, text="", error=f"subprocess error: {exc}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if proc.returncode != 0:
        return LLMResponse(
            ok=False, text=proc.stdout or "",
            error=f"claude CLI exit {proc.returncode}: {proc.stderr[:200]}",
            latency_ms=latency_ms,
        )

    try:
        envelope = json.loads(proc.stdout)
    except Exception as exc:
        return LLMResponse(
            ok=False, text=proc.stdout or "",
            error=f"failed to parse CLI envelope JSON: {exc}",
            latency_ms=latency_ms,
        )

    result_text = (envelope.get("result") or "").strip()
    model_used = next(iter(envelope.get("modelUsage") or {}), None)
    usage = envelope.get("usage") or {}

    return LLMResponse(
        ok=True,
        text=result_text,
        latency_ms=latency_ms,
        model_duration_ms=envelope.get("duration_ms"),
        cost_usd=envelope.get("total_cost_usd"),
        token_input=usage.get("input_tokens"),
        token_output=usage.get("output_tokens"),
        model_name=model_used,
    )


# ─────────────────────────────────────────────────────────────────────────
# JSON extraction helpers — the model sometimes wraps output in code fences
# ─────────────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def extract_json_block(text: str) -> str:
    """Strip code fences / prose and return the likely JSON substring."""
    if not text:
        return text
    stripped = text.strip()

    m = _FENCE_RE.match(stripped)
    if m:
        return m.group(1).strip()

    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    braced = _balanced_json_object(stripped)
    return braced if braced is not None else stripped


def _balanced_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\" and in_str:
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None
