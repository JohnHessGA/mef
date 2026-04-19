"""LLM gate — approve/reject the ranker's emitted candidates.

Interface:

    apply_gate(conn, run_uid, survivors) -> GateResult

``survivors`` is the list of RankedCandidate that passed the ranker's
threshold + cap. The gate builds a prompt, calls the LLM, parses a JSON
response, and returns a ``GateResult`` describing each candidate's
decision. Every call is logged to ``mef.llm_trace`` (one row per
batched gate call in v1).

Failure modes:
- LLM call errors → every survivor is marked ``unavailable``.
- JSON parse fails → same: unavailable.
- LLM returns a decision array for only some symbols → the missing ones
  are marked unavailable so they still ship.

Only the caller (``mef.run_pipeline``) writes to ``mef.candidate`` or
``mef.recommendation``. The gate only returns decisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mef.llm.client import LLMResponse, call_llm, extract_json_block
from mef.llm.prompts import build_gate_prompt
from mef.ranker import RankedCandidate
from mef.uid import next_uid


@dataclass
class GateDecision:
    symbol: str
    decision: str       # 'approve' | 'reject' | 'unavailable'
    reason: str | None


@dataclass
class GateResult:
    decisions: dict[str, GateDecision]   # symbol → decision
    available: bool                       # False if the LLM failed wholesale
    llm_trace_uid: str | None            # row in mef.llm_trace, if one was written

    approved: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def _candidate_payload(c: RankedCandidate) -> dict[str, Any]:
    """Serialize a RankedCandidate for prompt rendering.

    Features are passed through to prompt-render code which formats them;
    we don't JSON-dump here.
    """
    features = {**c.features}
    # Drop non-primitive values the prompt doesn't use
    features.pop("bar_date", None)
    return {
        "symbol":               c.symbol,
        "asset_kind":           c.asset_kind,
        "posture":              c.posture,
        "conviction_score":     c.conviction_score,
        "features":             features,
        "proposed_expression":  c.proposed_expression,
        "proposed_entry_zone":  c.proposed_entry_zone,
        "proposed_stop":        c.proposed_stop,
        "proposed_target":      c.proposed_target,
        "proposed_time_exit":   c.proposed_time_exit.isoformat() if c.proposed_time_exit else None,
    }


def _parse_gate_response(text: str) -> dict[str, tuple[str, str]]:
    """Parse the LLM's JSON response into {symbol: (decision, reason)}.

    Raises ValueError on unparseable or malformed shape.
    """
    block = extract_json_block(text)
    if not block:
        raise ValueError("empty response text")
    data = json.loads(block)
    if not isinstance(data, dict) or "reviews" not in data:
        raise ValueError("missing 'reviews' key in response")
    reviews = data["reviews"]
    if not isinstance(reviews, list):
        raise ValueError("'reviews' is not a list")

    out: dict[str, tuple[str, str]] = {}
    for rev in reviews:
        if not isinstance(rev, dict):
            continue
        sym = rev.get("symbol")
        dec = rev.get("decision")
        reason = rev.get("reason") or ""
        if not sym or dec not in ("approve", "reject"):
            continue
        out[sym] = (dec, str(reason).strip())
    return out


def _log_trace(
    conn,
    *,
    run_uid: str,
    prompt: str,
    response: LLMResponse,
    status: str,
    error_text: str | None,
) -> str:
    uid = next_uid(conn, "llm_trace")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.llm_trace (
                uid, run_uid, provider, model,
                prompt_text, response_text, elapsed_ms, status, error_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uid, run_uid, response.provider, response.model_name,
                prompt, response.text, response.latency_ms, status, error_text,
            ),
        )
    conn.commit()
    return uid


def _all_unavailable(symbols: list[str]) -> dict[str, GateDecision]:
    return {s: GateDecision(symbol=s, decision="unavailable", reason=None) for s in symbols}


def apply_gate(
    conn,
    *,
    run_uid: str,
    survivors: list[RankedCandidate],
    as_of_date: str,
    spy_return_20d: float | None,
    spy_return_63d: float | None,
) -> GateResult:
    if not survivors:
        return GateResult(decisions={}, available=True, llm_trace_uid=None)

    payload = [_candidate_payload(c) for c in survivors]
    prompt = build_gate_prompt(
        candidates=payload,
        as_of_date=as_of_date,
        spy_return_20d=spy_return_20d,
        spy_return_63d=spy_return_63d,
    )

    symbols = [c.symbol for c in survivors]
    response = call_llm(prompt)

    if not response.ok:
        trace_uid = _log_trace(
            conn, run_uid=run_uid, prompt=prompt, response=response,
            status="error", error_text=response.error,
        )
        decisions = _all_unavailable(symbols)
        result = GateResult(
            decisions=decisions, available=False, llm_trace_uid=trace_uid,
        )
        result.unavailable = symbols[:]
        return result

    try:
        parsed = _parse_gate_response(response.text)
    except Exception as exc:
        trace_uid = _log_trace(
            conn, run_uid=run_uid, prompt=prompt, response=response,
            status="error", error_text=f"parse error: {exc}",
        )
        decisions = _all_unavailable(symbols)
        result = GateResult(
            decisions=decisions, available=False, llm_trace_uid=trace_uid,
        )
        result.unavailable = symbols[:]
        return result

    trace_uid = _log_trace(
        conn, run_uid=run_uid, prompt=prompt, response=response,
        status="ok", error_text=None,
    )

    decisions: dict[str, GateDecision] = {}
    approved: list[str] = []
    rejected: list[str] = []
    unavailable: list[str] = []
    for sym in symbols:
        if sym not in parsed:
            decisions[sym] = GateDecision(symbol=sym, decision="unavailable", reason=None)
            unavailable.append(sym)
            continue
        dec, reason = parsed[sym]
        decisions[sym] = GateDecision(symbol=sym, decision=dec, reason=reason)
        if dec == "approve":
            approved.append(sym)
        else:
            rejected.append(sym)

    return GateResult(
        decisions=decisions,
        available=True,
        llm_trace_uid=trace_uid,
        approved=approved,
        rejected=rejected,
        unavailable=unavailable,
    )
