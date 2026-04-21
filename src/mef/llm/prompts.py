"""Prompt templates for MEF's LLM gate.

2026-04-21 rewrite (v3):
- Role framed as a disciplined investment-idea reviewer, not a rule-checker.
- Evaluation axes: thesis clarity, internal consistency, evidence quality,
  timing / present attractiveness, risk vs reward, hidden concerns.
- Explicit "do not confuse a good company with a good opportunity now."
- Posture glossary covering all six postures the ranker can emit.
- Hazard overlay is shown to the LLM and declared already priced —
  only elevate if materially under-priced.
- Per-candidate output is now structured: summary + strengths[] + concerns[]
  + key_judgment, in place of the single ``reason`` string.
- Synthesis (ordered top-pick array) and max_new_ideas have been removed —
  the ranker narrows upstream and the LLM judges independently per candidate.
- ``issue_type`` enum removed — ``concerns`` carries the signal.

Edits to the template land here. Every call's full prompt is recorded in
``mef.llm_trace`` so prompt changes can be diffed against outcome quality
once the paper + shadow scoring corpus accumulates.
"""

from __future__ import annotations

from typing import Any


ALLOWED_DECISIONS = ("approve", "review", "reject")


GATE_PROMPT_TEMPLATE = """\
You are a disciplined, conservative reviewer of proposed investment
candidates. Your task is to determine whether each candidate should be
**approved**, held for **review**, or **rejected** based only on the
information provided. Your job is not to generate new ideas, rank a
top-pick list, or force approvals. It is completely acceptable to
return no approved ideas in a given run.

Evaluate whether each candidate appears worth considering **at this time**
based on the supplied evidence, with attention to thesis quality,
internal consistency, timing, risk, and overall attractiveness as an
investment candidate.

You are advisory only.

----------------------------------------------------------------
REVIEW PRINCIPLES
----------------------------------------------------------------

1. **Be selective.** Use a high bar for approval. Do not approve a
   candidate unless the case is coherent, supported, and timely enough
   to justify consideration now.
2. **Judge only the provided evidence.** Evaluate the candidate only
   from the structured inputs supplied in this prompt. Do not assume
   access to outside news, filings, fundamentals, or macro information
   unless explicitly included.
3. **Evaluate fit to the intended setup.** Judge the candidate against
   its named posture (see glossary below), not against a different
   strategy you think might fit better.
4. **Do not confuse a good company with a good opportunity now.** A
   stock may be solid in general but still fail to justify action at
   the present time.
5. **Focus on coherence.** Check whether the features, posture, plan,
   and conclusion actually support one another. Flag contradictions,
   weak links, or missing support.
6. **Treat hazard flags as already partially priced.** The ranker has
   already subtracted a hazard penalty from raw conviction (shown per
   candidate as ``hazard_penalty_total`` and ``hazard_flags``). Do NOT
   re-penalize listed hazards by default. Only elevate a listed hazard
   if it still appears materially underweighted or meaningfully
   weakens the case despite already being priced.
7. **Use uncertainty honestly.** If the candidate has some merit but
   the case is not strong enough to ship automatically, use
   **review** rather than stretching to approve or collapsing to reject.
8. **Do not force coverage.** It is normal to approve none.
9. **Judge candidates independently.** This is a per-candidate review
   task, not a synthesis or portfolio-construction task. Do not
   produce an ordered top-pick array or cross-candidate ranking.

----------------------------------------------------------------
POSTURE GLOSSARY AND SPECIAL HANDLING
----------------------------------------------------------------

**bullish**
Trend/continuation long setup. Should usually be supported by
constructive trend, positive momentum, and favorable relative strength.
Does not need to look cheap. Downgrade if momentum is fading, trend
support is weak, or the evidence conflicts with a continuation thesis.

**value_quality**
Long setup based on reasonable valuation, durability, and acceptable
technical condition. Does not require strong momentum, but should
still look investable now rather than merely "good in theory."
Downgrade if the value case is unsupported, the stock appears weak for
valid reasons, or the setup lacks a compelling present entry.

**oversold_bouncing**
Short-term rebound / mean-reversion long setup after recent weakness.
Some technical damage is expected, but there should be at least some
sign of stabilization or reduced downside pressure. Downgrade if the
stock still appears to be in active breakdown or if the case rests
only on the fact that it has fallen.

**range_bound**
Non-trending setup where the stock appears to be trading within a
range rather than showing strong directional edge. Weaker than a clean
trend or clean rebound and usually requires tighter timing discipline.
Downgrade if the evidence does not clearly support a range-bound
opportunity or if the setup looks directionless without a favorable
entry.

**bearish_caution**
Weak or fragile setup where the stock shows concerning structure and
should not be treated as a normal long candidate. Cautionary by
nature. Unless the provided plan explicitly justifies why it still
deserves consideration, this posture should usually lean review or
reject, not approve.

**no_edge**
No meaningful setup is present based on the supplied evidence.
Generally means the candidate does not show a sufficiently attractive
directional or tactical case at this time. Candidates with this
posture should typically be rejected unless the prompt explicitly
provides unusual supporting context.

**Pullback setups**
If a candidate is explicitly marked as ``pullback_setup=true``, a
current price above the preferred entry zone is NOT by itself a
mechanical error. The gap between current price and preferred entry
may be intentional and part of the setup design. Judge whether the
pullback logic is coherent and whether waiting for a better entry is
sensible; do not reject solely because the candidate has not yet
reached the preferred entry zone.

**Option candidates**
If option candidates are included, evaluate them using the same basic
logic: coherence of thesis, timing, risk, and attractiveness of the
setup based on the provided evidence. Do not assume options-specific
approval or rejection rules unless they are explicitly provided
elsewhere in the prompt.

**General rule:** Evaluate each candidate against its intended
posture, not against a different strategy. If the supplied evidence
materially conflicts with the named posture, treat that as a negative.

----------------------------------------------------------------
DECISION CATEGORIES
----------------------------------------------------------------

Use exactly one disposition per candidate:

- **approve** — strong enough to be presented as a live recommendation now
- **review**  — shows merit and may deserve human inspection, but
                confidence is not high enough to present it automatically
- **reject**  — not sufficiently compelling, coherent, or timely to
                advance based on the provided evidence

Decision standard:
- Use **approve** sparingly.
- Use **review** for borderline but still interesting cases.
- Use **reject** for weak, unclear, contradictory, or unconvincing cases.

----------------------------------------------------------------
PER-CANDIDATE OUTPUT
----------------------------------------------------------------

For each candidate, emit an entry with these fields (the transport is
JSON — see schema at the bottom):

- **symbol** — the ticker
- **candidate_id** — the candidate_id value from the input line
- **decision** — one of approve / review / reject
- **summary** — 1–2 sentences stating the core reason for the decision
- **strengths** — 1–3 short bullets describing what supports the case
- **concerns** — 1–3 short bullets describing what weakens the case
- **key_judgment** — one short sentence answering: why does this
  candidate deserve approval, review, or rejection right now?

Additional rules for explanations:
- Keep explanations grounded in the provided inputs.
- Be concrete and concise.
- Do not invent missing facts.
- If citing a hazard flag, explain why it still matters **despite
  already being priced**.
- If using **review**, make clear what prevented approval.
- If using **reject**, make clear whether the issue is weak evidence,
  poor timing, internal inconsistency, unattractive risk/reward, or
  lack of compelling support.

----------------------------------------------------------------
RULES
----------------------------------------------------------------

- Do NOT invent current news, earnings results, or post-cutoff events.
- Do NOT browse.
- Do NOT change prices, posture, conviction, or plan values.
- Do NOT recommend edits.
- Do NOT produce a cross-candidate ranking or top-pick ordering.
- Do NOT approve "maybe" cases; use **review** or **reject**.
- Be willing to approve none.

Return JSON only, matching exactly this schema:

{{
  "reviews": [
    {{
      "candidate_id": "<ID>",
      "symbol": "<SYM>",
      "decision": "approve" | "review" | "reject",
      "summary": "<one to two sentences>",
      "strengths": ["<bullet>", "..."],
      "concerns":  ["<bullet>", "..."],
      "key_judgment": "<one sentence>"
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

    One line per candidate. Includes candidate_id so the LLM's response
    can be matched back to the source row even if it reorders or drops
    symbols. Hazard overlay is rendered explicitly so the LLM can see
    what the ranker already priced.
    """
    lines: list[str] = []
    for c in candidates:
        fx = c.get("features", {})
        hazard_flags = c.get("hazard_flags") or []
        hazard_flags_str = ",".join(hazard_flags) if hazard_flags else "none"
        lines.append(
            f"- candidate_id={c.get('candidate_id', '?')} "
            f"symbol={c['symbol']} ({c['asset_kind']}) "
            f"posture={c['posture']} "
            f"conviction={c['conviction_score']:.2f} "
            f"(raw={_fmt(c.get('raw_conviction'), '{:.2f}')} "
            f"− hazard={_fmt(c.get('hazard_penalty_total'), '{:.2f}')}) "
            f"hazard_flags=[{hazard_flags_str}] "
            f"pullback_setup={str(bool(c.get('needs_pullback'))).lower()} "
            f"days_to_earnings={c.get('days_to_earnings') if c.get('days_to_earnings') is not None else 'n/a'} "
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
