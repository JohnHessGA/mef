"""LLM gate — 3-way disposition over the ranker's emitted candidates.

Interface:

    apply_gate(conn, run_uid, survivors, ...) -> GateResult

``survivors`` is the list of RankedCandidate that passed the ranker's
threshold + per-engine cap. The gate builds a prompt, calls the LLM,
parses a JSON response, and returns a ``GateResult`` describing each
candidate's disposition. Every call is logged to ``mef.llm_trace``.

Disposition (matches the v3 prompt, 2026-04-21 rewrite):

  - "approve"     — safe to ship as-is. Becomes a recommendation. Goes in email.
  - "review"      — not auto-shippable. Becomes a recommendation and is
                    shown in the email's "Held for review" section.
  - "reject"      — does not become a recommendation. Audit lives on
                    mef.candidate (llm_gate_decision + rich fields).
  - "unavailable" — LLM call failed. Becomes a recommendation with a
                    "not reviewed by LLM" warning. Goes in email so an LLM
                    outage doesn't silence MEF entirely.

Per-candidate output is now structured: ``summary`` + ``strengths[]`` +
``concerns[]`` + ``key_judgment``. The legacy ``reason`` string and
``issue_type`` enum have been removed from the prompt and from the
GateDecision dataclass.

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
from mef.llm.prompts import ALLOWED_DECISIONS, build_gate_prompt
from mef.ranker import RankedCandidate
from mef.uid import next_uid


@dataclass
class GateDecision:
    symbol: str
    decision: str                        # approve | review | reject | unavailable
    summary: str | None = None           # 1–2 sentence rationale
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    key_judgment: str | None = None      # one-sentence bottom line


@dataclass
class GateResult:
    decisions: dict[str, GateDecision]   # symbol → decision
    available: bool                       # False if the LLM failed wholesale
    llm_trace_uid: str | None             # row in mef.llm_trace, if one was written

    approved: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)

    # Short classification of why the gate was unavailable, carried
    # through to the email banner. One of:
    #   "timeout"   — LLM subprocess timed out (incl. post-retry)
    #   "parse"     — LLM responded but we couldn't parse the JSON
    #   "error"     — anything else (CLI missing, non-zero exit, unknown)
    # None when available == True.
    unavailable_kind: str | None = None
    # Free-form one-sentence reason for audit and logs.
    unavailable_reason: str | None = None


def _candidate_payload(
    c: RankedCandidate,
    *,
    candidate_uid: str | None = None,
) -> dict[str, Any]:
    """Serialize a RankedCandidate for prompt rendering.

    The candidate line shows the hazard overlay explicitly so the LLM
    can see what the ranker already priced.
    """
    features = {**c.features}
    features.pop("bar_date", None)
    # Derive days_to_earnings at payload time so the LLM sees the
    # scalar instead of a raw date string.
    from datetime import date as _date
    next_earn = features.get("next_earnings_date")
    bar_date = c.features.get("bar_date") or _date.today()
    days_to_earn = None
    if next_earn is not None and hasattr(next_earn, "year"):
        days_to_earn = (next_earn - bar_date).days

    return {
        "candidate_id":         candidate_uid,
        "symbol":               c.symbol,
        "asset_kind":           c.asset_kind,
        "posture":              c.posture,
        "conviction_score":     c.conviction_score,
        "raw_conviction":       getattr(c, "raw_conviction", None),
        "hazard_penalty_total": getattr(c, "hazard_penalty_total", None),
        "hazard_flags":         list(getattr(c, "hazard_flags", []) or []),
        "engine":               c.engine,
        "features":             features,
        "proposed_expression":  c.proposed_expression,
        "proposed_entry_zone":  c.proposed_entry_zone,
        "proposed_stop":        c.proposed_stop,
        "proposed_target":      c.proposed_target,
        "proposed_time_exit":   c.proposed_time_exit.isoformat() if c.proposed_time_exit else None,
        "needs_pullback":       c.needs_pullback,
        "days_to_earnings":     days_to_earn,
    }


def _coerce_str_list(raw: Any, *, cap: int = 3) -> list[str]:
    """Coerce an LLM-supplied list of bullets to list[str], truncated at ``cap``."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        out.append(s)
        if len(out) >= cap:
            break
    return out


def _parse_gate_response(text: str) -> dict[str, dict[str, Any]]:
    """Parse the LLM's JSON response into {symbol: parsed_fields}.

    Returns {symbol: {decision, summary, strengths, concerns, key_judgment}}.

    Raises ValueError on unparseable / malformed shape. Per-row decisions
    outside the allowed enum are skipped (caller treats missing symbols
    as 'unavailable').
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

    out: dict[str, dict[str, Any]] = {}
    for rev in reviews:
        if not isinstance(rev, dict):
            continue
        sym = rev.get("symbol")
        dec = rev.get("decision")
        if not sym or dec not in ALLOWED_DECISIONS:
            continue
        out[sym] = {
            "decision":     dec,
            "summary":      str(rev.get("summary") or "").strip() or None,
            "strengths":    _coerce_str_list(rev.get("strengths")),
            "concerns":     _coerce_str_list(rev.get("concerns")),
            "key_judgment": str(rev.get("key_judgment") or "").strip() or None,
        }
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
    return {
        s: GateDecision(symbol=s, decision="unavailable")
        for s in symbols
    }


def _response_is_timeout(response: LLMResponse) -> bool:
    """True when the subprocess timed out (including the post-retry case)."""
    err = (response.error or "").lower()
    return "timed out" in err


def apply_gate(
    conn,
    *,
    run_uid: str,
    survivors: list[RankedCandidate],
    as_of_date: str,
    spy_return_20d: float | None,
    spy_return_63d: float | None,
    candidate_uids: dict[str, str] | None = None,
) -> GateResult:
    """Gate the survivors. ``candidate_uids`` maps symbol → candidate UID
    (e.g. ``C-000042``) so the prompt can include candidate_id and the
    LLM's response can be matched back even if symbols are reordered.
    """
    if not survivors:
        return GateResult(decisions={}, available=True, llm_trace_uid=None)

    candidate_uids = candidate_uids or {}
    payload = [
        _candidate_payload(c, candidate_uid=candidate_uids.get(c.symbol))
        for c in survivors
    ]
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
        kind = "timeout" if _response_is_timeout(response) else "error"
        result = GateResult(
            decisions=decisions, available=False, llm_trace_uid=trace_uid,
            unavailable_kind=kind,
            unavailable_reason=response.error,
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
            unavailable_kind="parse",
            unavailable_reason=f"LLM response could not be parsed: {exc}",
        )
        result.unavailable = symbols[:]
        return result

    trace_uid = _log_trace(
        conn, run_uid=run_uid, prompt=prompt, response=response,
        status="ok", error_text=None,
    )

    decisions: dict[str, GateDecision] = {}
    approved: list[str] = []
    review: list[str] = []
    rejected: list[str] = []
    unavailable: list[str] = []
    for sym in symbols:
        row = parsed.get(sym)
        if row is None:
            decisions[sym] = GateDecision(symbol=sym, decision="unavailable")
            unavailable.append(sym)
            continue
        decisions[sym] = GateDecision(
            symbol=sym,
            decision=row["decision"],
            summary=row["summary"],
            strengths=row["strengths"],
            concerns=row["concerns"],
            key_judgment=row["key_judgment"],
        )
        if row["decision"] == "approve":
            approved.append(sym)
        elif row["decision"] == "review":
            review.append(sym)
        else:
            rejected.append(sym)

    return GateResult(
        decisions=decisions,
        available=True,
        llm_trace_uid=trace_uid,
        approved=approved,
        review=review,
        rejected=rejected,
        unavailable=unavailable,
    )
