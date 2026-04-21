"""Unit tests for the LLM-client timeout-retry policy.

``call_llm`` retries once if the first ``call_claude`` attempt hits the
subprocess timeout. Other failure modes (binary missing, non-zero exit,
parse errors) are not retried — they are structural.

We patch ``call_claude`` directly rather than stubbing subprocess so the
tests exercise the retry policy, not the subprocess shim.
"""

from __future__ import annotations

from mef.llm import client as llm_client
from mef.llm.client import LLMResponse


def _ok(text: str = '{"reviews": []}') -> LLMResponse:
    return LLMResponse(ok=True, text=text, latency_ms=10)


def _timeout(secs: int = 120) -> LLMResponse:
    return LLMResponse(
        ok=False, text="",
        error=f"claude CLI timed out after {secs}s",
        latency_ms=secs * 1000,
    )


def _cli_missing() -> LLMResponse:
    return LLMResponse(
        ok=False, text="",
        error="claude CLI not found at '/fake/path' (set MEF_CLAUDE_PATH…)",
    )


def test_first_attempt_success_returns_immediately(monkeypatch):
    calls = []
    def fake_call_claude(prompt, *, timeout_s, **kw):
        calls.append(timeout_s)
        return _ok()
    monkeypatch.setattr(llm_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(llm_client, "_sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "load_app_config", lambda: {"llm": {"timeout_s": 120}})

    resp = llm_client.call_llm("any prompt")
    assert resp.ok is True
    assert calls == [120]   # only one attempt


def test_timeout_then_success_retries_and_returns_second(monkeypatch):
    calls = []
    def fake_call_claude(prompt, *, timeout_s, **kw):
        calls.append(timeout_s)
        return _timeout(120) if len(calls) == 1 else _ok()
    sleeps = []
    monkeypatch.setattr(llm_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(llm_client, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(llm_client, "load_app_config", lambda: {"llm": {"timeout_s": 120}})

    resp = llm_client.call_llm("any prompt")
    assert resp.ok is True
    # First at configured 120s, retry at module-level RETRY_TIMEOUT_S (180s).
    assert calls == [120, llm_client.RETRY_TIMEOUT_S]
    # Pause happened exactly once between the two attempts.
    assert sleeps == [llm_client.RETRY_PAUSE_S]


def test_timeout_then_timeout_returns_annotated_error(monkeypatch):
    calls = []
    def fake_call_claude(prompt, *, timeout_s, **kw):
        calls.append(timeout_s)
        return _timeout(timeout_s)
    monkeypatch.setattr(llm_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(llm_client, "_sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "load_app_config", lambda: {"llm": {"timeout_s": 120}})

    resp = llm_client.call_llm("any prompt")
    assert resp.ok is False
    # Annotated message mentions BOTH attempts so audit sees the retry context.
    assert "timed out twice" in resp.error
    assert "120s" in resp.error
    assert "180s" in resp.error
    assert calls == [120, 180]


def test_non_timeout_first_error_does_not_retry(monkeypatch):
    # Binary-missing errors are structural — retrying doesn't help.
    calls = []
    def fake_call_claude(prompt, *, timeout_s, **kw):
        calls.append(timeout_s)
        return _cli_missing()
    monkeypatch.setattr(llm_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(llm_client, "_sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "load_app_config", lambda: {"llm": {"timeout_s": 120}})

    resp = llm_client.call_llm("any prompt")
    assert resp.ok is False
    assert "not found" in resp.error
    # Only one attempt — structural errors shouldn't double the wall clock.
    assert calls == [120]


def test_timeout_then_different_error_returns_annotated(monkeypatch):
    # First timed out, retry returned a different error class. The final
    # error should mention the retry context so the llm_trace audit line
    # is self-explanatory.
    calls = []
    def fake_call_claude(prompt, *, timeout_s, **kw):
        calls.append(timeout_s)
        if len(calls) == 1:
            return _timeout(120)
        return LLMResponse(ok=False, text="", error="claude CLI exit 1: boom")
    monkeypatch.setattr(llm_client, "call_claude", fake_call_claude)
    monkeypatch.setattr(llm_client, "_sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "load_app_config", lambda: {"llm": {"timeout_s": 120}})

    resp = llm_client.call_llm("any prompt")
    assert resp.ok is False
    assert "LLM retry failed after first attempt timed out" in resp.error
    assert "boom" in resp.error


def test_is_timeout_error_classifies_correctly():
    assert llm_client._is_timeout_error("claude CLI timed out after 120s") is True
    assert llm_client._is_timeout_error("Claude CLI Timed Out after 30s") is True
    assert llm_client._is_timeout_error(None) is False
    assert llm_client._is_timeout_error("") is False
    assert llm_client._is_timeout_error("exit 1: boom") is False
