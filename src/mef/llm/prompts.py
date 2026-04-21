"""Prompt templates for MEF's LLM gate.

v2 prompt (2026-04-XX):
- 3-way disposition: approve / review / reject
- Server-validated issue_type enum
- Strict review order (mechanical → trade-shape → durable knowledge → missing-context)
- Conservative bias — "review" for borderline; "approve" only when coherent
- Future-proofed for option candidates (currently inactive: MEF v1 only emits stock/ETF)

Edits to the template land here. Every call's full prompt is recorded in
``mef.llm_trace`` so we can diff prompt changes against outcome quality
once the audit corpus accumulates (mef.paper_score + mef.shadow_score).
"""

from __future__ import annotations

from typing import Any


# Allowed issue_type strings — must match the CHECK constraint in
# sql/mefdb/005_gate_review_disposition.sql. The gate parser validates
# against this set and coerces unknown values to "missing_context".
ALLOWED_ISSUE_TYPES = (
    "none",
    "mechanical",
    "risk_shape",
    "volatility_mismatch",
    "posture_mismatch",
    "asset_structure",
    "options_structure",
    "missing_context",
)

ALLOWED_DECISIONS = ("approve", "review", "reject")


GATE_PROMPT_TEMPLATE = """\
You are reviewing the output of a deterministic daily ranker built for
selective stock/ETF trading over a curated US universe. Some candidates may
ultimately be expressed with options, but your primary job is to evaluate
whether the underlying setup is coherent enough to ship.

The ranker has emitted {n_candidates} candidate recommendation(s). Each
candidate carries a posture, conviction score, and a draft plan produced from
deterministic rules only. No current news, no browsing, and no post-cutoff
events are available to you.

MEF is advisory only and intentionally selective. It is healthy for this gate
to approve none of the candidates on a weak day.

Your job is to gate each candidate with exactly one disposition:

- "approve" = safe to ship as-is
- "review"  = not safe to auto-ship; hold for manual or deterministic follow-up
- "reject"  = do not ship

You are NOT being asked to forecast the market. You are acting as a strict,
conservative coherence and risk reviewer.

----------------------------------------------------------------
HOW TO REVIEW CANDIDATES
----------------------------------------------------------------

Review each candidate in this order:

1. Mechanical coherence
Reject if the plan is internally inconsistent or malformed.
Examples:
- stop is on the wrong side of entry
- target is on the wrong side of entry
- entry zone conflicts with posture
- time_exit is missing or nonsensical
- expression conflicts with posture

2. Trade-shape sanity
Reject or review if the plan has obviously weak structure from the provided data.
Examples:
- downside is too large relative to target
- vol_z is extreme for the stated holding window
- drawdown / RSI / MACD / ret20d materially conflict with the posture and plan
- the setup looks too fragile for a conservative advisory system

3. Durable-knowledge risk screen
Use only durable, non-current market knowledge.
Allowed examples:
- sector/industry is typically too gap-prone for this style of plan
- security type is structurally noisy or regime-sensitive
- the plan shape is usually unsuitable for names with this profile
Do NOT use current news, current earnings results, rumors, or post-cutoff facts.

4. Missing-context rule
If the candidate might be valid but essential context is missing, use "review".
Do not approve borderline cases.

----------------------------------------------------------------
SPECIAL RULE FOR PULLBACK SETUPS
----------------------------------------------------------------

When a candidate has pullback_setup=true, the ranker has INTENTIONALLY anchored
the entry zone below the current price because the stock closed at or very near
its recent peak. The entry zone is a resting-limit price that fills only on a
pullback — the gap between current close and entry_high is by design.

On a pullback_setup=true candidate:

- Do NOT flag "current price exceeds entry range" as an issue. That gap is the
  feature, not a bug.
- When judging risk/reward, compute it from the midpoint of the entry zone,
  NOT from current close. The stop/target are sized against the pullback entry,
  not against today's print.
- Everything else (trade-shape sanity, durable-knowledge risk, mechanical
  coherence) still applies normally.

If a pullback setup is otherwise coherent, approve it.

----------------------------------------------------------------
SPECIAL RULE FOR OPTION CANDIDATES
----------------------------------------------------------------

If asset_kind = "option" OR the expression uses options, do NOT try to judge
whether the strike/expiry is optimal.

Instead:
- review the UNDERLYING thesis first
- ask whether the stock/ETF setup is coherent enough to justify an options
  expression at all
- if the underlying thesis is weak, fragile, or incoherent, use "reject" or
  "review"
- only use "approve" if the underlying setup is coherent and nothing in the
  provided option fields is obviously malformed

For option candidates:
- if option details are clearly incoherent, use issue_type = "options_structure"
- if option details are merely incomplete, use "review" with
  issue_type = "missing_context"

----------------------------------------------------------------
DECISION STANDARD
----------------------------------------------------------------

For EACH candidate return exactly one of:

- decision: "approve"
  Use only when the plan is internally coherent, conservatively reasonable,
  and not obviously at odds with the provided metrics plus durable knowledge.

- decision: "review"
  Use when the idea is not clearly broken, but is too uncertain, incomplete,
  fragile, or borderline to auto-ship.

- decision: "reject"
  Use when the plan is malformed, structurally weak, or clearly outside the
  comfort zone of a conservative advisory system.

Allowed issue_type values:
- "none"
- "mechanical"
- "risk_shape"
- "volatility_mismatch"
- "posture_mismatch"
- "asset_structure"
- "options_structure"
- "missing_context"

Reason rules:
- one sentence only
- <= 160 characters
- concrete, not vague
- no suggestions, no alternatives, no caveats

----------------------------------------------------------------
RULES
----------------------------------------------------------------

- Do NOT invent current news, earnings results, or post-cutoff events.
- Do NOT browse.
- Do NOT change prices, posture, conviction, or plan values.
- Do NOT recommend edits.
- Do NOT approve "maybe" cases; use "review" or "reject".
- Be willing to approve none.

Return JSON only, matching exactly this schema:

{{
  "reviews": [
    {{
      "candidate_id": "<ID>",
      "symbol": "<SYM>",
      "decision": "approve" | "review" | "reject",
      "issue_type": "none" | "mechanical" | "risk_shape" | "volatility_mismatch" | "posture_mismatch" | "asset_structure" | "options_structure" | "missing_context",
      "reason": "<one sentence>"
    }}
  ]
}}

Context for this run:
as_of_date: {as_of_date}
SPY_20d_return: {spy_ret20}
SPY_63d_return: {spy_ret63}

Candidates:
{candidates_block}
"""


def render_candidates_block(candidates: list[dict[str, Any]]) -> str:
    """Render the per-candidate feature block for the prompt.

    One line per candidate. Includes the candidate_id so the LLM's
    response can be matched back to the source row even if it reorders
    or drops symbols.
    """
    lines: list[str] = []
    for c in candidates:
        fx = c.get("features", {})
        lines.append(
            f"- candidate_id={c.get('candidate_id', '?')} "
            f"symbol={c['symbol']} ({c['asset_kind']}) "
            f"posture={c['posture']} conviction={c['conviction_score']:.2f} "
            f"pullback_setup={str(bool(c.get('needs_pullback'))).lower()} "
            f"close={_fmt(fx.get('close'), '{:.2f}')} "
            f"ret5d={_fmt_pct(fx.get('return_5d'))} "
            f"ret20d={_fmt_pct(fx.get('return_20d'))} "
            f"ret63d={_fmt_pct(fx.get('return_63d'))} "
            f"ret252d={_fmt_pct(fx.get('return_252d'))} "
            f"rsi14={_fmt(fx.get('rsi_14'), '{:.0f}')} "
            f"macd_hist={_fmt(fx.get('macd_histogram'), '{:+.2f}')} "
            f"sma20_slope={_fmt(fx.get('sma_20_slope'), '{:+.3f}')} "
            f"rv20/rv63="
            f"{_fmt((fx.get('realized_vol_20d') or 0) / (fx.get('realized_vol_63d') or 1), '{:.2f}') if fx.get('realized_vol_63d') else 'n/a'} "
            f"rs_spy63={_fmt_pct(fx.get('rs_vs_spy_63d'))} "
            f"rs_qqq63={_fmt_pct(fx.get('rs_vs_qqq_63d'))} "
            f"drawdown={_fmt_pct(fx.get('drawdown_current'))} "
            f"vol_z={_fmt(fx.get('volume_z_score'), '{:+.2f}')} "
            f"sector={fx.get('sector') or 'etf'} | "
            f"plan: {c.get('proposed_expression')} "
            f"entry={c.get('proposed_entry_zone')} "
            f"stop=${_fmt(c.get('proposed_stop'), '{:.2f}')} "
            f"target=${_fmt(c.get('proposed_target'), '{:.2f}')} "
            f"time_exit={c.get('proposed_time_exit')}"
        )
    return "\n".join(lines)


def build_gate_prompt(
    *,
    candidates: list[dict[str, Any]],
    as_of_date: str,
    spy_return_20d: float | None,
    spy_return_63d: float | None,
) -> str:
    return GATE_PROMPT_TEMPLATE.format(
        n_candidates=len(candidates),
        as_of_date=as_of_date,
        spy_ret20=_fmt_pct(spy_return_20d) or "n/a",
        spy_ret63=_fmt_pct(spy_return_63d) or "n/a",
        candidates_block=render_candidates_block(candidates),
    )


# ─────────────────────────────────────────────────────────────────────────

def _fmt(v: Any, spec: str) -> str:
    if v is None:
        return "n/a"
    try:
        return spec.format(v)
    except Exception:
        return str(v)


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.1%}"
