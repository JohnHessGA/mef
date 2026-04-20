"""Deterministic ranker v0.

Scores each universe symbol for directional posture and conviction using a
small, rule-based evidence mix. Intentionally crude — future versions will
expand the evidence set, tune weights, and introduce sector-relative context.

Input:  ``EvidenceBundle`` from ``mef.evidence`` plus runtime knobs.
Output: list of ``RankedCandidate`` — one per symbol with non-trivial evidence.

Emission (i.e. becoming a ``proposed`` recommendation) is decided by the
caller using ``conviction_score >= conviction_threshold`` AND a non-no_edge
posture, capped at ``max_new_ideas_per_run``. Those two knobs live in
``config/mef.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mef.evidence import EvidenceBundle


POSTURE_BULLISH = "bullish"
POSTURE_BEARISH_CAUTION = "bearish_caution"
POSTURE_RANGE_BOUND = "range_bound"
POSTURE_NO_EDGE = "no_edge"

EXPRESSION_BUY_SHARES = "buy_shares"
EXPRESSION_BUY_ETF = "buy_etf"
EXPRESSION_COVERED_CALL = "covered_call"
EXPRESSION_CASH_SECURED_PUT = "cash_secured_put"


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    asset_kind: str
    posture: str
    conviction_score: float
    features: dict[str, Any]

    # Draft plan — only populated for non-no_edge candidates worth emitting.
    proposed_expression: str | None = None
    proposed_entry_zone: str | None = None
    proposed_stop: float | None = None
    proposed_target: float | None = None
    proposed_time_exit: date | None = None

    # Emission helpers
    emitted: bool = False
    reasoning_notes: list[str] = field(default_factory=list)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _score_symbol(symbol: str, row: dict[str, Any], baseline: dict[str, Any]) -> RankedCandidate:
    """Pure scoring rule over one symbol's evidence row."""
    close = row.get("close")
    return_20d = row.get("return_20d")
    rsi = row.get("rsi_14")
    macd_hist = row.get("macd_histogram")
    vol_z = row.get("volume_z_score")
    drawdown = row.get("drawdown_current")
    above_50 = bool(row.get("trend_above_sma50"))
    above_200 = bool(row.get("trend_above_sma200"))

    # Minimum viable evidence. Without a close or SMAs we have no opinion.
    if close is None or row.get("sma_50") is None or row.get("sma_200") is None:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            reasoning_notes=["insufficient evidence: close or SMA(s) missing"],
        )

    notes: list[str] = []

    # ─────────────────────────────── posture ───────────────────────────────
    if above_50 and above_200:
        posture = POSTURE_BULLISH
        base = 0.55
        if rsi is not None and 45 <= rsi <= 65:
            base += 0.10
            notes.append(f"RSI healthy ({rsi:.0f})")
        elif rsi is not None and rsi > 70:
            posture = POSTURE_RANGE_BOUND
            base = 0.45
            notes.append(f"RSI overbought ({rsi:.0f}) → range_bound")
        if macd_hist is not None and macd_hist > 0:
            base += 0.05
            notes.append("MACD histogram positive")
        # Tiered 20d-return: reward modest advances (pre-breakout / early),
        # neutral in the middle, penalize already-extended bounces.
        if return_20d is not None:
            if 0.02 <= return_20d <= 0.08:
                base += 0.05
                notes.append(f"20d return {return_20d:.1%} (modest, constructive)")
            elif return_20d > 0.15:
                base -= 0.10
                notes.append(f"20d return {return_20d:.1%} extended → bounce penalty")
        if vol_z is not None and vol_z > 0.5:
            base += 0.03
            notes.append(f"volume z-score {vol_z:+.2f}")
        # Extension from SMA50: prefer names near or just-reclaiming SMA50
        # (coiled setups) over names already well above it (bounce done).
        sma50 = row.get("sma_50")
        if sma50 and sma50 > 0:
            ext50 = (close / sma50) - 1.0
            if 0.0 <= ext50 <= 0.03:
                base += 0.05
                notes.append(f"close {ext50:+.1%} from SMA50 → coiled setup")
            elif ext50 > 0.08:
                base -= 0.08
                notes.append(f"close {ext50:+.1%} above SMA50 → extended penalty")
        # SPY-relative nudge
        spy20 = baseline.get("spy_return_20d")
        if posture == POSTURE_BULLISH and spy20 is not None and return_20d is not None:
            rel = return_20d - spy20
            if rel > 0:
                base += 0.03
                notes.append(f"outperforming SPY by {rel:+.1%} over 20d")
            elif rel < -0.03:
                base -= 0.04
                notes.append(f"trailing SPY by {rel:+.1%} over 20d")
    elif not above_50 and not above_200:
        posture = POSTURE_BEARISH_CAUTION
        base = 0.45
        notes.append("below SMA50 and SMA200")
        if drawdown is not None and drawdown < -0.10:
            base += 0.05
            notes.append(f"drawdown {drawdown:.1%}")
    else:
        # mixed trend — either regaining SMA200 or losing SMA50
        posture = POSTURE_RANGE_BOUND
        base = 0.40
        notes.append("trend mixed (one SMA above, one below)")

    # Drawdown penalty regardless of posture
    if drawdown is not None and drawdown < -0.20:
        base -= 0.15
        notes.append(f"deep drawdown {drawdown:.1%} → penalty")

    conviction = _clamp(base, 0.0, 1.0)

    # Anything that barely scored is just no_edge.
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        features=row,
        reasoning_notes=notes,
    )


def _draft_plan(cand: RankedCandidate) -> RankedCandidate:
    """Attach a draft expression + entry/stop/target for emittable postures."""
    close = cand.features.get("close")
    if close is None or cand.posture in (POSTURE_NO_EDGE, POSTURE_BEARISH_CAUTION):
        return cand

    if cand.posture == POSTURE_BULLISH:
        expression = EXPRESSION_BUY_ETF if cand.asset_kind == "etf" else EXPRESSION_BUY_SHARES
        entry_low = round(close * 0.98, 2)
        entry_high = round(close * 1.00, 2)
        stop = round(close * 0.93, 2)
        target = round(close * 1.08, 2)
    else:  # range_bound
        expression = EXPRESSION_CASH_SECURED_PUT if cand.asset_kind == "stock" else EXPRESSION_COVERED_CALL
        entry_low = round(close * 0.96, 2)
        entry_high = round(close * 0.99, 2)
        stop = round(close * 0.92, 2)
        target = round(close * 1.04, 2)

    bar_date = cand.features.get("bar_date") or date.today()
    time_exit = bar_date + timedelta(days=30)

    return RankedCandidate(
        symbol=cand.symbol,
        asset_kind=cand.asset_kind,
        posture=cand.posture,
        conviction_score=cand.conviction_score,
        features=cand.features,
        proposed_expression=expression,
        proposed_entry_zone=f"${entry_low:.2f}-${entry_high:.2f}",
        proposed_stop=stop,
        proposed_target=target,
        proposed_time_exit=time_exit,
        reasoning_notes=cand.reasoning_notes,
    )


def rank(evidence: EvidenceBundle) -> list[RankedCandidate]:
    """Score every symbol in the bundle and return a list of RankedCandidate."""
    out: list[RankedCandidate] = []
    for symbol, row in evidence.symbols.items():
        cand = _score_symbol(symbol, row, evidence.baseline)
        if cand.posture in (POSTURE_BULLISH, POSTURE_RANGE_BOUND):
            cand = _draft_plan(cand)
        out.append(cand)
    out.sort(key=lambda c: c.conviction_score, reverse=True)
    return out


def select_for_emission(
    candidates: list[RankedCandidate],
    *,
    conviction_threshold: float,
    max_new_ideas: int,
) -> list[RankedCandidate]:
    """Apply threshold + cap. Only bullish and range_bound survive to emission."""
    eligible = [
        c for c in candidates
        if c.posture in (POSTURE_BULLISH, POSTURE_RANGE_BOUND)
        and c.conviction_score >= conviction_threshold
    ]
    eligible.sort(key=lambda c: c.conviction_score, reverse=True)
    return eligible[:max_new_ideas]
