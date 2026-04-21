"""Deterministic ranker.

Produces ``RankedCandidate`` rows with a three-layer pipeline per
(engine, symbol) pair:

    Layer A — eligibility     (mef.eligibility.check)
    Layer C — engine thesis   (this module; _score_symbol / _score_mean_rev /
                                _score_value — each computes a *raw* conviction)
    Layer B — hazard overlay  (mef.hazard_overlay.compute — macro + earnings_prox)

The engine scorers know nothing about macro events or earnings blackouts
— those concerns live in Layers A and B. The only fundamental rule that
remains inside an engine is the **value engine's negative-FCF hard
veto**, because a cash-burning name is a direct thesis violation for
value (cheap + durable). Trend and mean-reversion keep soft penalties
(PE, earnings yield) but no FCF veto — their theses are primarily
technical.

Conviction naming on ``RankedCandidate``:

  - ``raw_conviction``    — engine belief, before any overlay
  - ``conviction_score``  — effective score used by selectors / thresholds
                            (equals raw for no_edge; raw − overlay.total
                            for emittable postures)

Emission (becoming a ``proposed`` recommendation) is decided downstream
using ``conviction_score >= conviction_threshold`` AND a non-no_edge
posture, capped at ``max_new_ideas_per_run``. Those two knobs live in
``config/mef.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Callable

from mef import eligibility, hazard_overlay
from mef.evidence import SECTOR_TO_ETF, EvidenceBundle


POSTURE_BULLISH = "bullish"
POSTURE_BEARISH_CAUTION = "bearish_caution"
POSTURE_RANGE_BOUND = "range_bound"
POSTURE_NO_EDGE = "no_edge"
POSTURE_OVERSOLD_BOUNCING = "oversold_bouncing"
POSTURE_VALUE_QUALITY = "value_quality"

EXPRESSION_BUY_SHARES = "buy_shares"
EXPRESSION_BUY_ETF = "buy_etf"
EXPRESSION_COVERED_CALL = "covered_call"
EXPRESSION_CASH_SECURED_PUT = "cash_secured_put"


ENGINE_TREND = "trend"
ENGINE_MEAN_REVERSION = "mean_reversion"
ENGINE_VALUE = "value"
KNOWN_ENGINES = (ENGINE_TREND, ENGINE_MEAN_REVERSION, ENGINE_VALUE)


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    asset_kind: str
    posture: str
    conviction_score: float         # effective (post-overlay) value
    features: dict[str, Any]

    # Engine tag — ``rank()`` enforces that this matches the producing
    # engine so the mef.candidate.engine column stays honest.
    engine: str = ENGINE_TREND

    # Layer A bookkeeping
    eligibility_pass: bool = True
    eligibility_fail_reasons: list[str] = field(default_factory=list)

    # Layer B bookkeeping
    raw_conviction: float = 0.0
    hazard_penalty_total: float = 0.0
    hazard_penalty_macro: float = 0.0
    hazard_penalty_earnings_prox: float = 0.0
    hazard_event_type: str | None = None
    hazard_flags: list[str] = field(default_factory=list)

    # Draft plan — only populated for non-no_edge candidates worth
    # emitting. Plan numbers are *not* adjusted by the hazard overlay.
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


# ─────────────────────────────── Layer C: trend ───────────────────────────────

def _score_symbol(symbol: str, row: dict[str, Any], baseline: dict[str, Any]) -> RankedCandidate:
    """Trend scorer — raw-only. No earnings, no macro, no FCF veto.

    Soft PE / earnings-yield penalties remain: they are Layer C thesis
    adjustments (an overpriced name is a weaker trend thesis), not
    universal risk controls.
    """
    close = row.get("close")
    return_20d = row.get("return_20d")
    rsi = row.get("rsi_14")
    macd_hist = row.get("macd_histogram")
    vol_z = row.get("volume_z_score")
    drawdown = row.get("drawdown_current")
    above_50 = bool(row.get("trend_above_sma50"))
    above_200 = bool(row.get("trend_above_sma200"))

    # Minimum viable evidence.
    if close is None or row.get("sma_50") is None or row.get("sma_200") is None:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            reasoning_notes=["insufficient evidence: close or SMA(s) missing"],
        )

    notes: list[str] = []

    # ─────────────────────────────── posture ───────────────────────────────
    if above_50 and above_200:
        posture = POSTURE_BULLISH
        base = 0.55
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
        sma50 = row.get("sma_50")
        if sma50 and sma50 > 0:
            ext50 = (close / sma50) - 1.0
            if 0.0 <= ext50 <= 0.03:
                base += 0.05
                notes.append(f"close {ext50:+.1%} from SMA50 → coiled setup")
            elif ext50 > 0.08:
                base -= 0.08
                notes.append(f"close {ext50:+.1%} above SMA50 → extended penalty")
        rs_spy_20d = row.get("rs_vs_spy_20d")
        if posture == POSTURE_BULLISH and rs_spy_20d is not None:
            if rs_spy_20d > 0:
                base += 0.03
                notes.append(f"outperforming SPY by {rs_spy_20d:+.1%} over 20d")
            elif rs_spy_20d < -0.03:
                base -= 0.04
                notes.append(f"trailing SPY by {rs_spy_20d:+.1%} over 20d")
        rs_spy_63d = row.get("rs_vs_spy_63d")
        if posture == POSTURE_BULLISH and rs_spy_63d is not None and rs_spy_63d > 0.03:
            base += 0.02
            notes.append(f"sustained SPY outperformance ({rs_spy_63d:+.1%}/63d)")
        rs_qqq_63d = row.get("rs_vs_qqq_63d")
        if posture == POSTURE_BULLISH and rs_qqq_63d is not None:
            if rs_qqq_63d > 0.03:
                base += 0.02
                notes.append(f"beating QQQ by {rs_qqq_63d:+.1%}/63d")
            elif rs_qqq_63d < -0.08:
                base -= 0.02
                notes.append(f"lagging QQQ by {rs_qqq_63d:+.1%}/63d")
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
        posture = POSTURE_RANGE_BOUND
        base = 0.40
        notes.append("trend mixed (one SMA above, one below)")

    # Vol contraction — classic "coiled spring" signal.
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

    # Multi-timeframe consensus.
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
        if return_5d is not None and return_5d < -0.015:
            base -= 0.08
            notes.append(f"falling this week (ret5d {return_5d:+.1%})")

    if drawdown is not None and drawdown < -0.20:
        base -= 0.15
        notes.append(f"deep drawdown {drawdown:.1%} → penalty")

    needs_pullback = drawdown is not None and drawdown > -0.03
    if needs_pullback:
        notes.append(f"at recent peak (dd {drawdown:+.1%}) → wait for pullback")

    # Soft fundamental adjustments for trend — kept in Layer C because
    # they shape the trend thesis (overpriced ≠ strong continuation),
    # not a universal risk. FCF hard veto lives in the value engine.
    if row.get("asset_kind") == "stock":
        pe = row.get("pe_trailing")
        ey = row.get("earnings_yield")
        if pe is not None and pe > 60:
            base -= 0.05
            notes.append(f"extreme PE ({pe:.0f}) → penalty")
        if ey is not None and 0 < ey < 0.02:
            base -= 0.02
            notes.append(f"earnings yield {ey:.1%} → expensive")

    conviction = _clamp(base, 0.0, 1.0)

    # Posture gate on raw — anything that barely scored is no_edge.
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        raw_conviction=round(conviction, 4),
        features=row,
        needs_pullback=needs_pullback,
        reasoning_notes=notes,
    )


def _draft_plan(cand: RankedCandidate) -> RankedCandidate:
    """Attach a draft expression + entry/stop/target for emittable trend postures."""
    close = cand.features.get("close")
    if close is None or cand.posture in (POSTURE_NO_EDGE, POSTURE_BEARISH_CAUTION):
        return cand

    if cand.posture == POSTURE_BULLISH:
        expression = EXPRESSION_BUY_ETF if cand.asset_kind == "etf" else EXPRESSION_BUY_SHARES
        if cand.needs_pullback:
            sma20 = cand.features.get("sma_20") or 0.0
            atr14 = cand.features.get("atr_14") or 0.0
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

    return replace(
        cand,
        proposed_expression=expression,
        proposed_entry_zone=f"${entry_low:.2f}-${entry_high:.2f}",
        proposed_stop=stop,
        proposed_target=target,
        proposed_time_exit=time_exit,
    )


# ─────────────────────────── Layer C: mean_reversion ──────────────────────────

def _score_mean_rev(symbol: str, row: dict[str, Any], baseline: dict[str, Any]) -> RankedCandidate:
    """Mean-reversion scorer — raw-only. No earnings, no macro, no FCF veto."""
    close = row.get("close")
    sma_50 = row.get("sma_50")
    sma_200 = row.get("sma_200")
    rsi = row.get("rsi_14")
    macd_hist = row.get("macd_histogram")
    macd_value = row.get("macd_value")
    macd_signal = row.get("macd_signal")
    return_5d = row.get("return_5d")
    drawdown = row.get("drawdown_current")
    vol_z = row.get("volume_z_score")
    rv20 = row.get("realized_vol_20d")
    rv63 = row.get("realized_vol_63d")

    if close is None or sma_50 is None or rsi is None:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_MEAN_REVERSION,
            reasoning_notes=["insufficient evidence for mean_reversion"],
        )

    # Oversold gate.
    below_sma50_pct = (close / sma_50) - 1.0
    if rsi >= 40 or below_sma50_pct > -0.03:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_MEAN_REVERSION,
            reasoning_notes=["not oversold for mean_reversion"],
        )

    # Falling-knife veto.
    if (return_5d is not None and return_5d < -0.02) \
       or (drawdown is not None and drawdown < -0.30):
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_MEAN_REVERSION,
            reasoning_notes=[
                f"falling knife — ret5d {(return_5d or 0):+.1%} dd {(drawdown or 0):+.1%}"
            ],
        )

    notes: list[str] = []
    posture = POSTURE_OVERSOLD_BOUNCING
    base = 0.50

    if rsi < 30:
        base += 0.08
        notes.append(f"RSI deeply oversold ({rsi:.0f})")
    elif rsi < 35:
        base += 0.05
        notes.append(f"RSI oversold ({rsi:.0f})")
    else:
        base += 0.02
        notes.append(f"RSI mildly oversold ({rsi:.0f})")

    if -0.15 <= below_sma50_pct <= -0.05:
        base += 0.08
        notes.append(f"{below_sma50_pct:+.1%} below SMA50 (snapback zone)")
    elif below_sma50_pct < -0.15:
        base -= 0.05
        notes.append(f"{below_sma50_pct:+.1%} below SMA50 (deep)")

    if return_5d is not None:
        if return_5d >= 0.01:
            base += 0.08
            notes.append(f"bouncing (ret5d {return_5d:+.1%})")
        elif return_5d >= 0:
            base += 0.04
            notes.append(f"stabilizing (ret5d {return_5d:+.1%})")

    if macd_value is not None and macd_signal is not None and macd_value > macd_signal:
        base += 0.05
        notes.append("MACD bullish cross")
    elif macd_hist is not None and macd_hist > 0:
        base += 0.03
        notes.append("MACD histogram positive")

    if sma_200 is not None:
        if close > sma_200:
            base += 0.04
            notes.append("above SMA200 (pullback in uptrend)")
        else:
            base -= 0.05
            notes.append("below SMA200 (not just a pullback)")

    if vol_z is not None and vol_z > 1.0:
        base += 0.04
        notes.append(f"accumulation volume (z {vol_z:+.2f})")

    if rv20 is not None and rv63 is not None and rv63 > 0:
        vol_ratio = rv20 / rv63
        if vol_ratio < 0.85:
            base += 0.03
            notes.append(f"vol contracting into low ({vol_ratio:.2f})")

    conviction = _clamp(base, 0.0, 1.0)
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        raw_conviction=round(conviction, 4),
        features=row,
        engine=ENGINE_MEAN_REVERSION,
        reasoning_notes=notes,
    )


def _draft_plan_mean_rev(cand: RankedCandidate) -> RankedCandidate:
    close = cand.features.get("close")
    if close is None or cand.posture != POSTURE_OVERSOLD_BOUNCING:
        return cand

    expression = EXPRESSION_BUY_ETF if cand.asset_kind == "etf" else EXPRESSION_BUY_SHARES
    sma_50 = cand.features.get("sma_50") or (close * 1.08)
    target = round(min(sma_50, close * 1.08), 2)
    entry_low = round(close * 0.99, 2)
    entry_high = round(close * 1.01, 2)
    stop = round(close * 0.93, 2)

    bar_date = cand.features.get("bar_date") or date.today()
    time_exit = bar_date + timedelta(days=30)

    return replace(
        cand,
        proposed_expression=expression,
        proposed_entry_zone=f"${entry_low:.2f}-${entry_high:.2f}",
        proposed_stop=stop,
        proposed_target=target,
        proposed_time_exit=time_exit,
        needs_pullback=False,
    )


# ─────────────────────────────── Layer C: value ───────────────────────────────

def _score_value(symbol: str, row: dict[str, Any], baseline: dict[str, Any]) -> RankedCandidate:
    """Value scorer — raw-only. FCF hard veto kept (it IS the value thesis)."""
    close = row.get("close")
    sma_50 = row.get("sma_50")
    rsi = row.get("rsi_14")
    return_252d = row.get("return_252d")
    pe = row.get("pe_trailing")
    fcf = row.get("free_cash_flow")
    ey = row.get("earnings_yield")

    if close is None or row.get("asset_kind") != "stock":
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=["value engine is equities-only"],
        )

    if pe is None or fcf is None or ey is None:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=["missing fundamentals for value engine"],
        )

    # Value's own hard veto — kept in Layer C because FCF *is* the value
    # thesis (cheap + durable → cash generation). Trend and mean-rev do
    # NOT apply this veto.
    if fcf < 0:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=["negative TTM FCF → value thesis veto"],
        )
    if return_252d is not None and return_252d < -0.20:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            raw_conviction=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=[f"long-term downtrend ({return_252d:+.1%}/252d)"],
        )

    notes: list[str] = []
    posture = POSTURE_VALUE_QUALITY
    base = 0.50

    if 5 <= pe <= 15:
        base += 0.10
        notes.append(f"PE {pe:.1f} (cheap)")
    elif 15 < pe <= 25:
        base += 0.05
        notes.append(f"PE {pe:.1f} (fair)")
    elif pe > 30:
        base -= 0.05
        notes.append(f"PE {pe:.1f} (expensive for value)")
    elif pe < 5:
        base -= 0.03
        notes.append(f"PE {pe:.1f} (possibly distressed)")

    if ey > 0.07:
        base += 0.08
        notes.append(f"earnings yield {ey:.1%}")
    elif ey > 0.05:
        base += 0.04
        notes.append(f"earnings yield {ey:.1%}")
    elif ey < 0.02:
        base -= 0.03
        notes.append(f"earnings yield {ey:.1%} (expensive)")

    if return_252d is not None:
        if return_252d > 0.10:
            base += 0.05
            notes.append(f"long-term trend +{return_252d:.1%}/252d")
        elif return_252d > 0:
            base += 0.02
            notes.append(f"long-term trend +{return_252d:.1%}/252d")

    if sma_50 is not None and sma_50 > 0:
        ext_pct = (close / sma_50) - 1.0
        if ext_pct > 0.10:
            base -= 0.08
            notes.append(f"extended +{ext_pct:.1%} above SMA50 (momentum, not value)")

    if rsi is not None:
        if 40 <= rsi <= 65:
            base += 0.03
            notes.append(f"RSI stable ({rsi:.0f})")
        elif rsi < 30:
            base -= 0.05
            notes.append(f"RSI oversold ({rsi:.0f}) → mean-rev turf")

    if fcf > 5_000_000_000:
        base += 0.04
        notes.append("robust FCF (>$5B)")

    conviction = _clamp(base, 0.0, 1.0)
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        raw_conviction=round(conviction, 4),
        features=row,
        engine=ENGINE_VALUE,
        reasoning_notes=notes,
    )


def _draft_plan_value(cand: RankedCandidate) -> RankedCandidate:
    close = cand.features.get("close")
    if close is None or cand.posture != POSTURE_VALUE_QUALITY:
        return cand

    expression = EXPRESSION_BUY_SHARES
    entry_low = round(close * 0.99, 2)
    entry_high = round(close * 1.01, 2)
    stop = round(close * 0.90, 2)
    target = round(close * 1.10, 2)

    bar_date = cand.features.get("bar_date") or date.today()
    time_exit = bar_date + timedelta(days=60)

    return replace(
        cand,
        proposed_expression=expression,
        proposed_entry_zone=f"${entry_low:.2f}-${entry_high:.2f}",
        proposed_stop=stop,
        proposed_target=target,
        proposed_time_exit=time_exit,
        needs_pullback=False,
    )


# ─────────────────── Layer A + B wrappers (applied per engine) ───────────────

def _ineligible_candidate(
    symbol: str, row: dict[str, Any] | None, engine: str,
    reasons: list[str],
) -> RankedCandidate:
    """Emit a no_edge record when Layer A rejects the (symbol, engine) pair."""
    return RankedCandidate(
        symbol=symbol,
        asset_kind=(row or {}).get("asset_kind", "stock"),
        posture=POSTURE_NO_EDGE,
        conviction_score=0.0,
        raw_conviction=0.0,
        features=row or {"symbol": symbol},
        engine=engine,
        eligibility_pass=False,
        eligibility_fail_reasons=list(reasons),
        reasoning_notes=[f"layer_a: {r}" for r in reasons],
    )


def _apply_overlay(
    cand: RankedCandidate,
    row: dict[str, Any],
    baseline: dict[str, Any],
    today: date,
    hazard_config: dict[str, Any] | None,
) -> RankedCandidate:
    """Subtract the hazard overlay from raw, populate the decomposition.

    Called only for candidates whose posture survived the raw gate
    (i.e. is emittable). no_edge candidates are returned unchanged —
    their final == raw == 0 and the overlay would be meaningless.
    """
    if cand.posture == POSTURE_NO_EDGE:
        return cand
    overlay = hazard_overlay.compute(
        row, baseline, engine=cand.engine, today=today, config=hazard_config,
    )
    final = max(0.0, round(cand.raw_conviction - overlay.total, 4))
    return replace(
        cand,
        conviction_score=final,
        hazard_penalty_total=overlay.total,
        hazard_penalty_macro=overlay.macro,
        hazard_penalty_earnings_prox=overlay.earnings_prox,
        hazard_event_type=overlay.event_type,
        hazard_flags=list(overlay.flags),
        reasoning_notes=list(cand.reasoning_notes) + list(overlay.notes),
    )


def _rank_engine(
    evidence: EvidenceBundle,
    engine: str,
    scorer_fn: Callable[[str, dict, dict], RankedCandidate],
    plan_fn: Callable[[RankedCandidate], RankedCandidate],
    hazard_config: dict[str, Any] | None,
) -> list[RankedCandidate]:
    """Common per-engine pipeline: Layer A → Layer C → Layer B → plan."""
    today = evidence.as_of_date
    out: list[RankedCandidate] = []
    for symbol, row in evidence.symbols.items():
        elig = eligibility.check(symbol, row, engine=engine, today=today)
        if not elig.passed:
            out.append(_ineligible_candidate(symbol, row, engine, elig.reasons))
            continue

        # Layer C — engine thesis
        cand = scorer_fn(symbol, row, evidence.baseline)
        # Force engine tag — scorer functions set their own default but
        # the single source of truth is this wrapper.
        cand = replace(cand, engine=engine)

        # Layer B — hazard overlay (no-op on no_edge)
        cand = _apply_overlay(cand, row, evidence.baseline, today, hazard_config)

        # Draft plan — runs after overlay so the plan is attached to the
        # canonical candidate; entry/stop/target derive from features,
        # not from conviction, so overlay timing is irrelevant.
        cand = plan_fn(cand)
        out.append(cand)
    return out


def _rank_trend(evidence: EvidenceBundle, hazard_config=None) -> list[RankedCandidate]:
    return _rank_engine(evidence, ENGINE_TREND, _score_symbol, _draft_plan, hazard_config)


def _rank_mean_reversion(evidence: EvidenceBundle, hazard_config=None) -> list[RankedCandidate]:
    return _rank_engine(
        evidence, ENGINE_MEAN_REVERSION, _score_mean_rev, _draft_plan_mean_rev, hazard_config,
    )


def _rank_value(evidence: EvidenceBundle, hazard_config=None) -> list[RankedCandidate]:
    return _rank_engine(evidence, ENGINE_VALUE, _score_value, _draft_plan_value, hazard_config)


ENGINE_REGISTRY: dict[str, Callable[..., list[RankedCandidate]]] = {
    ENGINE_TREND:          _rank_trend,
    ENGINE_MEAN_REVERSION: _rank_mean_reversion,
    ENGINE_VALUE:          _rank_value,
}


def rank(
    evidence: EvidenceBundle,
    *,
    enabled_engines: list[str] | None = None,
    hazard_config: dict[str, Any] | None = None,
) -> list[RankedCandidate]:
    """Run every enabled engine through Layer A → C → B → plan.

    ``hazard_config`` is forwarded to ``hazard_overlay.compute``. When
    None, the module-level defaults apply — this keeps tests that don't
    care about overlay tuning simple.
    """
    if enabled_engines is None:
        enabled_engines = list(ENGINE_REGISTRY.keys())

    out: list[RankedCandidate] = []
    for engine_name in enabled_engines:
        fn = ENGINE_REGISTRY.get(engine_name)
        if fn is None:
            continue
        out.extend(fn(evidence, hazard_config=hazard_config))

    out.sort(key=lambda c: c.conviction_score, reverse=True)
    return out


# Postures that any engine considers emittable.
EMITTABLE_POSTURES = frozenset([
    POSTURE_BULLISH,
    POSTURE_RANGE_BOUND,
    POSTURE_OVERSOLD_BOUNCING,
    POSTURE_VALUE_QUALITY,
])


def select_for_emission(
    candidates: list[RankedCandidate],
    *,
    conviction_threshold: float,
    max_new_ideas: int,
) -> list[RankedCandidate]:
    """Flat top-N selection across all emittable candidates."""
    eligible = [
        c for c in candidates
        if c.posture in EMITTABLE_POSTURES
        and c.conviction_score >= conviction_threshold
    ]
    eligible.sort(key=lambda c: c.conviction_score, reverse=True)
    return eligible[:max_new_ideas]


def select_per_engine(
    candidates: list[RankedCandidate],
    *,
    conviction_threshold: float,
    top_n_per_engine: int,
) -> dict[str, list[RankedCandidate]]:
    """Per-engine top-N selection — threshold applied to final conviction."""
    per_engine: dict[str, list[RankedCandidate]] = {}
    for c in candidates:
        if c.posture not in EMITTABLE_POSTURES:
            continue
        if c.conviction_score < conviction_threshold:
            continue
        per_engine.setdefault(c.engine, []).append(c)
    for engine in per_engine:
        per_engine[engine].sort(key=lambda c: c.conviction_score, reverse=True)
        per_engine[engine] = per_engine[engine][:top_n_per_engine]
    return per_engine


def merge_for_llm(
    per_engine: dict[str, list[RankedCandidate]],
) -> tuple[list[RankedCandidate], dict[str, dict[str, float]]]:
    """Dedup per-engine top-Ns into a unique-by-symbol list for the LLM."""
    best_by_symbol: dict[str, RankedCandidate] = {}
    scores: dict[str, dict[str, float]] = {}
    for engine, cands in per_engine.items():
        for c in cands:
            scores.setdefault(c.symbol, {})[engine] = c.conviction_score
            prev = best_by_symbol.get(c.symbol)
            if prev is None or c.conviction_score > prev.conviction_score:
                best_by_symbol[c.symbol] = c
    merged = sorted(
        best_by_symbol.values(),
        key=lambda c: c.conviction_score, reverse=True,
    )
    return merged, scores


# ──────────────────────── Emission-outcome classification ────────────────────

def classify_outcomes(
    candidates: list[RankedCandidate],
    *,
    conviction_threshold: float,
) -> dict[str, dict[str, Any]]:
    """Tag each candidate with its pre-LLM disposition.

    Returns ``{candidate_key: {selected_pre_llm: bool, suppressed_by_hazard: bool}}``
    keyed by ``(engine, symbol)``. The pipeline writes these onto
    ``mef.candidate`` so audit can ask "which emittable postures did
    the hazard overlay silence?".

    - selected_pre_llm — emittable posture AND conviction_score >= threshold
    - suppressed_by_hazard — emittable posture, raw >= 0.40, final < threshold,
      AND a hazard penalty > 0 actually contributed. Candidates whose raw was
      already below threshold (weak thesis, not a hazard suppression) do NOT
      count as suppressed.
    """
    out: dict[str, dict[str, Any]] = {}
    for c in candidates:
        key = (c.engine, c.symbol)
        emittable = c.posture in EMITTABLE_POSTURES
        selected = emittable and c.conviction_score >= conviction_threshold
        suppressed = (
            emittable
            and not selected
            and c.raw_conviction >= conviction_threshold
            and c.hazard_penalty_total > 0
        )
        out[key] = {
            "selected_pre_llm":     selected,
            "suppressed_by_hazard": suppressed,
        }
    return out
