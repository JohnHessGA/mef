"""LLM gate — 3-way disposition over the ranker's emitted candidates.

Interface:

    apply_gate(conn, run_uid, survivors) -> GateResult

``survivors`` is the list of RankedCandidate that passed the ranker's
threshold + cap. The gate builds a prompt, calls the LLM, parses a JSON
response, and returns a ``GateResult`` describing each candidate's
disposition. Every call is logged to ``mef.llm_trace``.

Disposition (matches the v2 prompt):

  - "approve"     — safe to ship as-is. Becomes a recommendation. Goes in email.
  - "review"      — not auto-shippable. Becomes a recommendation. NOT in email.
                    Reviewable via ``mef recommendations`` and `mef show`.
  - "reject"      — does not become a recommendation. Audit lives on
                    mef.candidate (llm_gate_decision/llm_gate_reason/llm_gate_issue_type).
  - "unavailable" — LLM call failed. Becomes a recommendation with a
                    "not reviewed by LLM" warning. Goes in email so an LLM
                    outage doesn't silence MEF entirely.

issue_type is server-validated against the enum in
``prompts.ALLOWED_ISSUE_TYPES``. Unknown values get coerced to
"missing_context" — the most-conservative default — and the original
LLM-supplied string is preserved in the reason text for audit.

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
from mef.llm.prompts import ALLOWED_DECISIONS, ALLOWED_ISSUE_TYPES, build_gate_prompt
from mef.ranker import RankedCandidate
from mef.uid import next_uid


@dataclass
class GateDecision:
    symbol: str
    decision: str               # 'approve' | 'review' | 'reject' | 'unavailable'
    reason: str | None
    issue_type: str | None      # one of ALLOWED_ISSUE_TYPES, or None when unavailable


@dataclass
class GateResult:
    decisions: dict[str, GateDecision]   # symbol → decision
    available: bool                       # False if the LLM failed wholesale
    llm_trace_uid: str | None             # row in mef.llm_trace, if one was written

    approved: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)

    # The LLM's synthesis top-picks in order. Only symbols it approved.
    # Empty list when the LLM chooses "no new trades today" or when
    # the gate is unavailable. Populated only for multi-engine runs
    # where the prompt asks for a synthesis block.
    synthesis: list[str] = field(default_factory=list)


def _candidate_payload(
    c: RankedCandidate,
    *,
    candidate_uid: str | None = None,
    engine_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Serialize a RankedCandidate for prompt rendering.

    `engine_scores` maps engine_name → conviction for this symbol
    across any engines that picked it. Rendered into the candidate
    line so the LLM can see engine agreement/disagreement.
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
    if engine_scores:
        scores_str = " ".join(
            f"{eng}={score:.2f}" for eng, score in engine_scores.items()
        )
    else:
        scores_str = f"{c.engine}={c.conviction_score:.2f}"
    return {
        "candidate_id":         candidate_uid,
        "symbol":               c.symbol,
        "asset_kind":           c.asset_kind,
        "posture":              c.posture,
        "conviction_score":     c.conviction_score,
        "engine":               c.engine,
        "engine_scores_str":    scores_str,
        "features":             features,
        "proposed_expression":  c.proposed_expression,
        "proposed_entry_zone":  c.proposed_entry_zone,
        "proposed_stop":        c.proposed_stop,
        "proposed_target":      c.proposed_target,
        "proposed_time_exit":   c.proposed_time_exit.isoformat() if c.proposed_time_exit else None,
        "needs_pullback":       c.needs_pullback,
        "days_to_earnings":     days_to_earn,
    }


def _coerce_issue_type(raw: Any, decision: str) -> str:
    """Validate the LLM's issue_type against the allowed enum.

    Rules:
      - approve → if missing/garbage, default to "none"
      - review/reject → if missing/garbage, default to "missing_context"
        (most-conservative; flags as audit-worthy)
    """
    if isinstance(raw, str) and raw in ALLOWED_ISSUE_TYPES:
        return raw
    return "none" if decision == "approve" else "missing_context"


def _parse_gate_response(
    text: str,
) -> tuple[dict[str, tuple[str, str, str]], list[str]]:
    """Parse the LLM's JSON response into (reviews, synthesis).

    Returns ({symbol: (decision, issue_type, reason)}, synthesis_list).
    Synthesis is empty for single-engine prompts (old schema) or when
    the LLM returns an empty array / a malformed synthesis field.

    Raises ValueError on unparseable or malformed shape. Per-row issue_type
    is validated/coerced; per-row decisions outside the allowed enum are
    skipped (caller treats missing symbols as 'unavailable').
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

    out: dict[str, tuple[str, str, str]] = {}
    for rev in reviews:
        if not isinstance(rev, dict):
            continue
        sym = rev.get("symbol")
        dec = rev.get("decision")
        if not sym or dec not in ALLOWED_DECISIONS:
            continue
        reason = str(rev.get("reason") or "").strip()
        issue_type = _coerce_issue_type(rev.get("issue_type"), dec)
        out[sym] = (dec, issue_type, reason)

    # Synthesis is optional — single-engine prompts never emit one.
    # Accept list of strings only; any other shape → empty list.
    synthesis_raw = data.get("synthesis", [])
    synthesis: list[str] = []
    if isinstance(synthesis_raw, list):
        for item in synthesis_raw:
            if isinstance(item, str) and item:
                # Only include symbols the LLM also approved in reviews.
                rev = out.get(item)
                if rev and rev[0] == "approve":
                    synthesis.append(item)
    return out, synthesis


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
        s: GateDecision(symbol=s, decision="unavailable", reason=None, issue_type=None)
        for s in symbols
    }


def apply_gate(
    conn,
    *,
    run_uid: str,
    survivors: list[RankedCandidate],
    as_of_date: str,
    spy_return_20d: float | None,
    spy_return_63d: float | None,
    candidate_uids: dict[str, str] | None = None,
    engine_scores: dict[str, dict[str, float]] | None = None,
    max_new_ideas: int = 5,
) -> GateResult:
    """Gate the survivors. ``candidate_uids`` maps symbol → candidate UID
    (e.g. ``C-000042``) so the prompt can include candidate_id and the
    LLM's response can be matched back even if symbols are reordered.

    ``engine_scores`` maps symbol → {engine_name: conviction} so the
    prompt can show per-engine agreement/disagreement. When multiple
    engines picked the same symbol, the LLM sees that fact. Single-
    engine callers can omit it.
    """
    if not survivors:
        return GateResult(decisions={}, available=True, llm_trace_uid=None)

    candidate_uids = candidate_uids or {}
    engine_scores = engine_scores or {}
    payload = [
        _candidate_payload(
            c,
            candidate_uid=candidate_uids.get(c.symbol),
            engine_scores=engine_scores.get(c.symbol),
        )
        for c in survivors
    ]
    prompt = build_gate_prompt(
        candidates=payload,
        as_of_date=as_of_date,
        spy_return_20d=spy_return_20d,
        spy_return_63d=spy_return_63d,
        max_new_ideas=max_new_ideas,
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
        parsed, synthesis = _parse_gate_response(response.text)
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
    review: list[str] = []
    rejected: list[str] = []
    unavailable: list[str] = []
    for sym in symbols:
        if sym not in parsed:
            decisions[sym] = GateDecision(
                symbol=sym, decision="unavailable", reason=None, issue_type=None,
            )
            unavailable.append(sym)
            continue
        dec, issue_type, reason = parsed[sym]
        decisions[sym] = GateDecision(
            symbol=sym, decision=dec, reason=reason, issue_type=issue_type,
        )
        if dec == "approve":
            approved.append(sym)
        elif dec == "review":
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
        synthesis=synthesis,
    )
