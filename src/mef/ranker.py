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

from mef.evidence import SECTOR_TO_ETF, EvidenceBundle


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

    # True when the symbol is at or very near its recent peak (drawdown
    # ≈ 0): posture/conviction are unchanged, but _draft_plan anchors the
    # entry zone to a pullback target instead of "buy here".
    needs_pullback: bool = False

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
        # Chop detection: above both SMAs but neither is actually rising.
        # `sma_*_slope` is in price/day; normalize by close so the threshold
        # scales across $10 and $1000 names. |slope|/close < 0.08%/day is
        # effectively sideways.
        sma20_slope = row.get("sma_20_slope")
        sma50_slope = row.get("sma_50_slope")
        flat_th = 0.0008 * close
        if (sma20_slope is not None and sma50_slope is not None
                and abs(sma20_slope) < flat_th and abs(sma50_slope) < flat_th):
            posture = POSTURE_RANGE_BOUND
            base = 0.40
            notes.append("SMAs flat → chop above support")
        elif sma20_slope is not None and sma20_slope > 0:
            base += 0.03
            notes.append("SMA20 rising")
        elif sma20_slope is not None and sma20_slope < -flat_th:
            base -= 0.05
            notes.append("SMA20 rolling over")
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
        # SPY-relative nudge (prefer the mart's pre-computed rs_vs_spy
        # over hand-math so the signal stays in sync with other tooling
        # that reads those columns).
        rs_spy_20d = row.get("rs_vs_spy_20d")
        if posture == POSTURE_BULLISH and rs_spy_20d is not None:
            if rs_spy_20d > 0:
                base += 0.03
                notes.append(f"outperforming SPY by {rs_spy_20d:+.1%} over 20d")
            elif rs_spy_20d < -0.03:
                base -= 0.04
                notes.append(f"trailing SPY by {rs_spy_20d:+.1%} over 20d")
        # Persistent SPY leadership (longer lookback) — smaller bonus,
        # more durable signal than the 20d version.
        rs_spy_63d = row.get("rs_vs_spy_63d")
        if posture == POSTURE_BULLISH and rs_spy_63d is not None and rs_spy_63d > 0.03:
            base += 0.02
            notes.append(f"sustained SPY outperformance ({rs_spy_63d:+.1%}/63d)")
        # QQQ-relative: beating the tech/growth index over 63d is a
        # meaningful signal for non-tech names; lagging it badly matters
        # for tech names. Small weight.
        rs_qqq_63d = row.get("rs_vs_qqq_63d")
        if posture == POSTURE_BULLISH and rs_qqq_63d is not None:
            if rs_qqq_63d > 0.03:
                base += 0.02
                notes.append(f"beating QQQ by {rs_qqq_63d:+.1%}/63d")
            elif rs_qqq_63d < -0.08:
                base -= 0.02
                notes.append(f"lagging QQQ by {rs_qqq_63d:+.1%}/63d")
        # Sector-relative strength: compare this stock's 63d return to
        # its own sector ETF's 63d return. Rotation leaders surface here
        # when the broad index is flat.
        sector = row.get("sector")
        sector_etf = SECTOR_TO_ETF.get(sector) if sector else None
        sector_returns_63d = baseline.get("sector_returns_63d") or {}
        sector_ret_63d = sector_returns_63d.get(sector_etf)
        return_63d = row.get("return_63d")
        if (posture == POSTURE_BULLISH and sector_ret_63d is not None
                and return_63d is not None):
            sector_rel = return_63d - sector_ret_63d
            if sector_rel > 0.02:
                base += 0.04
                notes.append(f"beating {sector} sector by {sector_rel:+.1%}/63d")
            elif sector_rel < -0.05:
                base -= 0.03
                notes.append(f"trailing {sector} sector by {sector_rel:+.1%}/63d")
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

    # Volatility contraction — classic "coiled spring" signal. Applies
    # to emittable postures: recent vol meaningfully below medium-term
    # (ratio < 0.80) often precedes breakouts. Expansion (> 1.30) is
    # often a sign of deteriorating tape — lighter penalty since it can
    # also mark the start of a good move.
    if posture in (POSTURE_BULLISH, POSTURE_RANGE_BOUND):
        rv20 = row.get("realized_vol_20d")
        rv63 = row.get("realized_vol_63d")
        if rv20 is not None and rv63 is not None and rv63 > 0:
            vol_ratio = rv20 / rv63
            if vol_ratio < 0.80:
                base += 0.04
                notes.append(f"vol contracting (20d/63d {vol_ratio:.2f}) → coiled")
            elif vol_ratio > 1.30:
                base -= 0.03
                notes.append(f"vol expanding (20d/63d {vol_ratio:.2f})")

    # Multi-timeframe consensus — applies to emittable postures only.
    # Framed as "count strong disagreements with bullish posture" rather
    # than "count alignments", so normal V-recovery negativity (SPY itself
    # sat ~-3% on 126d in late March) does NOT rack up disagreements.
    # Only genuinely damaged stocks do.
    if posture in (POSTURE_BULLISH, POSTURE_RANGE_BOUND):
        return_5d = row.get("return_5d")
        return_126d = row.get("return_126d")
        return_252d = row.get("return_252d")
        disagreements = 0
        if return_20d is not None and return_20d < -0.05:
            disagreements += 1
        if row.get("return_63d") is not None and row["return_63d"] < -0.10:
            disagreements += 1
        if return_126d is not None and return_126d < -0.15:
            disagreements += 1
        if return_252d is not None and return_252d < -0.25:
            disagreements += 1
        if disagreements == 0:
            base += 0.06
            notes.append("no timeframe in strong disagreement")
        elif disagreements == 1:
            base += 0.02
            notes.append("mostly coherent (1 timeframe soft)")
        elif disagreements == 2:
            base -= 0.04
            notes.append("two timeframes disagree with posture")
        else:
            base -= 0.08
            notes.append(f"timeframes broadly disagree ({disagreements}/4)")
        # Short-term direction brake — separate from the structural count
        # above. Catches "falling this week" independent of long-horizon
        # alignment (e.g., TSLA with a -18% dd that's still dropping).
        if return_5d is not None and return_5d < -0.015:
            base -= 0.08
            notes.append(f"falling this week (ret5d {return_5d:+.1%})")

    # Drawdown penalty regardless of posture
    if drawdown is not None and drawdown < -0.20:
        base -= 0.15
        notes.append(f"deep drawdown {drawdown:.1%} → penalty")

    # Fundamental sanity — stocks only (ETFs have NULL fundamentals,
    # and the rule wouldn't make sense applied to them anyway). Hard
    # veto on negative TTM free cash flow: no amount of technical
    # momentum saves a cash-burner. Softer penalties on extreme PE
    # / very low earnings yield for expensive names.
    if row.get("asset_kind") == "stock":
        fcf = row.get("free_cash_flow")
        pe = row.get("pe_trailing")
        ey = row.get("earnings_yield")
        if fcf is not None and fcf < 0:
            posture = POSTURE_NO_EDGE
            base = 0.0
            notes.append("negative TTM free cash flow → veto")
        else:
            if pe is not None and pe > 60:
                base -= 0.05
                notes.append(f"extreme PE ({pe:.0f}) → penalty")
            if ey is not None and 0 < ey < 0.02:
                base -= 0.02
                notes.append(f"earnings yield {ey:.1%} → expensive")

    conviction = _clamp(base, 0.0, 1.0)

    # Anything that barely scored is just no_edge.
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    # At/near recent peak → patient entry only, regardless of conviction.
    # Threshold is symmetric with the SMA50 extension check above.
    needs_pullback = drawdown is not None and drawdown > -0.03
    if needs_pullback:
        notes.append(f"at recent peak (dd {drawdown:+.1%}) → wait for pullback")

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        features=row,
        needs_pullback=needs_pullback,
        reasoning_notes=notes,
    )


def _draft_plan(cand: RankedCandidate) -> RankedCandidate:
    """Attach a draft expression + entry/stop/target for emittable postures.

    When ``cand.needs_pullback`` is set, the entry zone is anchored to a
    realistic pullback target (higher of SMA20 or close − 2·ATR14, capped
    at ≥2% below close) instead of "buy at/near the current print". The
    emitted zone becomes a resting-limit price: it fills on a dip or
    doesn't fill at all, which is the actionable answer when the stock
    just tagged a fresh high.
    """
    close = cand.features.get("close")
    if close is None or cand.posture in (POSTURE_NO_EDGE, POSTURE_BEARISH_CAUTION):
        return cand

    if cand.posture == POSTURE_BULLISH:
        expression = EXPRESSION_BUY_ETF if cand.asset_kind == "etf" else EXPRESSION_BUY_SHARES
        if cand.needs_pullback:
            sma20 = cand.features.get("sma_20") or 0.0
            atr14 = cand.features.get("atr_14") or 0.0
            # Best realistic pullback target: higher of SMA20 / (close − 2·ATR) /
            # a 7% floor. Cap it at 2% below close so the zone is meaningfully
            # lower than the current print — otherwise the "wait" signal is moot.
            anchor = max(sma20, close - 2.0 * atr14, close * 0.93)
            anchor = min(anchor, close * 0.98)
            entry_low = round(anchor * 0.99, 2)
            entry_high = round(anchor * 1.01, 2)
            stop = round(entry_low * 0.94, 2)
            target = round(close * 1.06, 2)
        else:
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
        needs_pullback=cand.needs_pullback,
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
