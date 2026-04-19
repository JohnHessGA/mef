"""Prompt templates for MEF's LLM gate.

v1 prompt instructs the LLM to approve or reject each emitted candidate,
returning strictly structured JSON.

Edits to the template land here. Every call's full prompt is recorded in
``mef.llm_trace`` so we can diff prompt changes against outcome quality
once scoring history accumulates (milestone 8).
"""

from __future__ import annotations

from typing import Any


GATE_PROMPT_TEMPLATE = """\
You are reviewing the output of a deterministic daily ranker built for
selective stock/ETF trading over a curated 305-stock + 15-ETF US universe.

The ranker has emitted {n_candidates} candidate recommendation(s). Each
carries a posture, a conviction score, and a draft entry/stop/target plan
produced from deterministic rules only — no market news, no external
context. MEF is advisory only and intentionally selective; it is healthy
for the gate to reject all candidates on a weak day.

Your job is to gate each candidate: approve it to ship, or reject it.

For EACH candidate do exactly one of:

  - decision: "approve"  — the plan looks internally coherent and not
    obviously at odds with durable market/sector knowledge you have.
    Provide a single-sentence reason (<= 140 chars).

  - decision: "reject"   — the plan is incoherent (e.g. stop above entry),
    or carries elevated risk you think the ranker missed based on durable
    knowledge (sector norms, typical volatility around catalysts, known
    structural concerns). Provide a one-sentence reason (<= 160 chars).

Rules:
  - Do NOT invent current news, earnings results, or post-cutoff events.
  - Do NOT change prices, posture, or conviction — approve or reject.
  - Be willing to reject. Uncertainty is a reason to reject, not to
    approve-with-caveat.
  - Return JSON only — no prose before or after — matching exactly:

{{
  "reviews": [
    {{"symbol": "<SYM>", "decision": "approve" | "reject", "reason": "<one sentence>"}}
  ]
}}

Context for this run:
  as_of_date: {as_of_date}
  SPY 20d return: {spy_ret20}
  SPY 63d return: {spy_ret63}

Candidates:
{candidates_block}
"""


def render_candidates_block(candidates: list[dict[str, Any]]) -> str:
    """Render the per-candidate feature block for the prompt.

    Each line is a compact feature digest — enough for the LLM to judge
    coherence without dumping the full feature_json.
    """
    lines: list[str] = []
    for c in candidates:
        fx = c.get("features", {})
        lines.append(
            f"- {c['symbol']} ({c['asset_kind']}) "
            f"posture={c['posture']} conviction={c['conviction_score']:.2f} "
            f"close={_fmt(fx.get('close'), '{:.2f}')} "
            f"ret20d={_fmt_pct(fx.get('return_20d'))} "
            f"rsi14={_fmt(fx.get('rsi_14'), '{:.0f}')} "
            f"macd_hist={_fmt(fx.get('macd_histogram'), '{:+.2f}')} "
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
