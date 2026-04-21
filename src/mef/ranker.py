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


ENGINE_TREND = "trend"
ENGINE_MEAN_REVERSION = "mean_reversion"
ENGINE_VALUE = "value"
KNOWN_ENGINES = (ENGINE_TREND, ENGINE_MEAN_REVERSION, ENGINE_VALUE)


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    asset_kind: str
    posture: str
    conviction_score: float
    features: dict[str, Any]

    # The ranker engine that produced this candidate. Defaults to the
    # pre-existing trend-follower so any caller that doesn't yet
    # enumerate engines keeps working.
    engine: str = ENGINE_TREND

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

    # At/near recent peak → patient entry only. Computed here (rather
    # than at the end) so the earnings-proximity rule below can widen
    # its veto window for pullback setups specifically.
    needs_pullback = drawdown is not None and drawdown > -0.03
    if needs_pullback:
        notes.append(f"at recent peak (dd {drawdown:+.1%}) → wait for pullback")

    # Earnings-proximity gate — stocks only. An upcoming earnings
    # announcement makes any technical thesis contingent on a binary
    # event the ranker can't see. Veto (no_edge) when close, penalty
    # when near, flag when on-horizon.
    if row.get("asset_kind") == "stock":
        next_earn = row.get("next_earnings_date")
        bar_date = row.get("bar_date") or date.today()
        if next_earn is not None:
            days_to_earn = (next_earn - bar_date).days
            # Pullback setups depend on gradual price action; an
            # earnings gap nullifies that assumption, so the veto
            # window is wider for them.
            pullback_veto_window = 10
            general_veto_window = 5
            penalty_window = 10
            flag_window = 21
            if (needs_pullback and 0 <= days_to_earn <= pullback_veto_window) \
               or (0 <= days_to_earn <= general_veto_window):
                posture = POSTURE_NO_EDGE
                base = 0.0
                notes.append(f"earnings in {days_to_earn}d → veto")
            elif 0 <= days_to_earn <= penalty_window:
                base -= 0.15
                notes.append(f"earnings in {days_to_earn}d → penalty")
            elif 0 <= days_to_earn <= flag_window:
                base -= 0.03
                notes.append(f"earnings in {days_to_earn}d → caution")

    # Macro-event dampener — applies universe-wide (all emittable
    # postures). Small -0.05 nudge when a US High-impact macro
    # release lands today or tomorrow. Not a veto: individual stocks
    # can still rise through macro releases, it's just a "maybe don't
    # start today" signal.
    if posture in (POSTURE_BULLISH, POSTURE_RANGE_BOUND):
        events = baseline.get("upcoming_high_impact_events") or []
        bar_date_for_events = row.get("bar_date") or date.today()
        for ev in events:
            days_to_ev = (ev["date"] - bar_date_for_events).days
            if 0 <= days_to_ev <= 1:
                base -= 0.05
                notes.append(
                    f"high-impact macro event {ev['event']} in {days_to_ev}d"
                )
                break  # one penalty max, even on multi-event days

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


POSTURE_OVERSOLD_BOUNCING = "oversold_bouncing"


def _score_mean_rev(symbol: str, row: dict[str, Any], baseline: dict[str, Any]) -> RankedCandidate:
    """Mean-reversion engine scorer.

    Rewards oversold bounce setups — stocks that have pulled back 5–15%
    below their SMA50, RSI in oversold territory, macd turning up, and
    return_5d non-negative (i.e., stabilizing, not still falling). The
    thesis is: snap-back to SMA20 / SMA50. Explicitly rejects falling
    knives (return_5d < 0, deep drawdown below -30%).

    Produces posture `oversold_bouncing` when a setup is present,
    `no_edge` otherwise. Draft plan places entry near current close
    (the name is already pulled back — no further patience required),
    stop below recent low, target at SMA20/50 reclaim.
    """
    close = row.get("close")
    sma_50 = row.get("sma_50")
    sma_200 = row.get("sma_200")
    rsi = row.get("rsi_14")
    macd_hist = row.get("macd_histogram")
    macd_value = row.get("macd_value")
    macd_signal = row.get("macd_signal")
    return_5d = row.get("return_5d")
    return_20d = row.get("return_20d")
    drawdown = row.get("drawdown_current")
    vol_z = row.get("volume_z_score")
    rv20 = row.get("realized_vol_20d")
    rv63 = row.get("realized_vol_63d")
    bar_date = row.get("bar_date") or date.today()

    # Minimum viable evidence — without close or SMA50 we have no opinion.
    if close is None or sma_50 is None or rsi is None:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_MEAN_REVERSION,
            reasoning_notes=["insufficient evidence for mean_reversion"],
        )

    # Gate 1: is this an oversold setup at all? Require meaningfully
    # below SMA50 and RSI < 40. If not, no mean-rev case.
    below_sma50_pct = (close / sma_50) - 1.0
    if rsi >= 40 or below_sma50_pct > -0.03:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_MEAN_REVERSION,
            reasoning_notes=["not oversold for mean_reversion"],
        )

    # Gate 2: falling-knife veto. If return_5d is strongly negative OR
    # drawdown is deep (>30%), the stock is still in free-fall.
    if (return_5d is not None and return_5d < -0.02) \
       or (drawdown is not None and drawdown < -0.30):
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_MEAN_REVERSION,
            reasoning_notes=[
                f"falling knife — ret5d {(return_5d or 0):+.1%} dd {(drawdown or 0):+.1%}"
            ],
        )

    notes: list[str] = []
    posture = POSTURE_OVERSOLD_BOUNCING
    base = 0.50

    # RSI depth — deeper oversold = stronger snapback case.
    if rsi < 30:
        base += 0.08
        notes.append(f"RSI deeply oversold ({rsi:.0f})")
    elif rsi < 35:
        base += 0.05
        notes.append(f"RSI oversold ({rsi:.0f})")
    else:  # 35-40
        base += 0.02
        notes.append(f"RSI mildly oversold ({rsi:.0f})")

    # Distance below SMA50. Sweet spot is -5% to -15%: deep enough to
    # bounce meaningfully, not deep enough to signal trend change.
    if -0.15 <= below_sma50_pct <= -0.05:
        base += 0.08
        notes.append(f"{below_sma50_pct:+.1%} below SMA50 (snapback zone)")
    elif below_sma50_pct < -0.15:
        base -= 0.05
        notes.append(f"{below_sma50_pct:+.1%} below SMA50 (deep)")

    # Short-term direction — actively bouncing is the signal.
    if return_5d is not None:
        if return_5d >= 0.01:
            base += 0.08
            notes.append(f"bouncing (ret5d {return_5d:+.1%})")
        elif return_5d >= 0:
            base += 0.04
            notes.append(f"stabilizing (ret5d {return_5d:+.1%})")

    # MACD crossover-up — bullish cross is the classic mean-rev trigger.
    if macd_value is not None and macd_signal is not None and macd_value > macd_signal:
        base += 0.05
        notes.append("MACD bullish cross")
    elif macd_hist is not None and macd_hist > 0:
        base += 0.03
        notes.append("MACD histogram positive")

    # Trend backdrop — above SMA200 means this is a pullback in an
    # uptrend, not a full breakdown.
    if sma_200 is not None:
        if close > sma_200:
            base += 0.04
            notes.append("above SMA200 (pullback in uptrend)")
        else:
            base -= 0.05
            notes.append("below SMA200 (not just a pullback)")

    # Accumulation signal — volume spike on the decline.
    if vol_z is not None and vol_z > 1.0:
        base += 0.04
        notes.append(f"accumulation volume (z {vol_z:+.2f})")

    # Vol contracting into the low — stabilization marker.
    if rv20 is not None and rv63 is not None and rv63 > 0:
        vol_ratio = rv20 / rv63
        if vol_ratio < 0.85:
            base += 0.03
            notes.append(f"vol contracting into low ({vol_ratio:.2f})")

    # Earnings gate — identical to trend. Event risk is worse for
    # mean-rev plays because bounce thesis can be reset overnight.
    if row.get("asset_kind") == "stock":
        next_earn = row.get("next_earnings_date")
        if next_earn is not None:
            days_to_earn = (next_earn - bar_date).days
            if 0 <= days_to_earn <= 10:
                posture = POSTURE_NO_EDGE
                base = 0.0
                notes.append(f"earnings in {days_to_earn}d → veto")

    # Fundamental veto — still applies.
    if row.get("asset_kind") == "stock":
        fcf = row.get("free_cash_flow")
        if fcf is not None and fcf < 0:
            posture = POSTURE_NO_EDGE
            base = 0.0
            notes.append("negative TTM free cash flow → veto")

    # Macro-event dampener — same as trend.
    if posture == POSTURE_OVERSOLD_BOUNCING:
        events = baseline.get("upcoming_high_impact_events") or []
        for ev in events:
            days_to_ev = (ev["date"] - bar_date).days
            if 0 <= days_to_ev <= 1:
                base -= 0.05
                notes.append(
                    f"high-impact macro event {ev['event']} in {days_to_ev}d"
                )
                break

    conviction = _clamp(base, 0.0, 1.0)
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        features=row,
        engine=ENGINE_MEAN_REVERSION,
        reasoning_notes=notes,
    )


def _draft_plan_mean_rev(cand: RankedCandidate) -> RankedCandidate:
    """Entry/stop/target for mean-reversion candidates.

    The stock is already pulled back, so entry is near current price
    (no patience needed). Stop sits below the recent low to invalidate
    the bounce thesis; target aims for SMA20/SMA50 reclaim.
    """
    close = cand.features.get("close")
    if close is None or cand.posture != POSTURE_OVERSOLD_BOUNCING:
        return cand

    expression = EXPRESSION_BUY_ETF if cand.asset_kind == "etf" else EXPRESSION_BUY_SHARES
    sma_50 = cand.features.get("sma_50") or (close * 1.08)
    # Target the SMA50 reclaim (typical snap-back destination), capped
    # at +8% so we don't propose absurd targets on very deep oversolds.
    target = round(min(sma_50, close * 1.08), 2)
    # Buy on market — name is already pulled back.
    entry_low = round(close * 0.99, 2)
    entry_high = round(close * 1.01, 2)
    # Stop 7% below close (below where the oversold bottom likely sits).
    stop = round(close * 0.93, 2)

    bar_date = cand.features.get("bar_date") or date.today()
    time_exit = bar_date + timedelta(days=30)

    return RankedCandidate(
        symbol=cand.symbol,
        asset_kind=cand.asset_kind,
        posture=cand.posture,
        conviction_score=cand.conviction_score,
        features=cand.features,
        engine=cand.engine,
        proposed_expression=expression,
        proposed_entry_zone=f"${entry_low:.2f}-${entry_high:.2f}",
        proposed_stop=stop,
        proposed_target=target,
        proposed_time_exit=time_exit,
        needs_pullback=False,
        reasoning_notes=cand.reasoning_notes,
    )


def _rank_mean_reversion(evidence: EvidenceBundle) -> list[RankedCandidate]:
    """Mean-reversion engine — oversold bounce setups.

    Opposite philosophy from trend: buys drops, not rips. Typical picks
    overlap with trend's rejections and vice versa.
    """
    out: list[RankedCandidate] = []
    for symbol, row in evidence.symbols.items():
        cand = _score_mean_rev(symbol, row, evidence.baseline)
        if cand.posture == POSTURE_OVERSOLD_BOUNCING:
            cand = _draft_plan_mean_rev(cand)
        out.append(cand)
    return out


POSTURE_VALUE_QUALITY = "value_quality"


def _score_value(symbol: str, row: dict[str, Any], baseline: dict[str, Any]) -> RankedCandidate:
    """Value/quality engine scorer.

    Rewards cheap + durable names. Typical picks are consumer staples,
    utilities, financials, and healthcare with positive free cash flow,
    moderate PE, and modest-but-positive long-term trend. Explicitly
    NOT for the same names the trend engine loves — expensive momentum
    stocks (PE > 30 AND extended above SMA50) are penalized.

    Posture `value_quality` when a setup is present, `no_edge`
    otherwise. Draft plan uses a longer time_exit (60 days vs trend's
    30) because value plays take time to pay off.
    """
    close = row.get("close")
    sma_50 = row.get("sma_50")
    sma_200 = row.get("sma_200")
    rsi = row.get("rsi_14")
    return_20d = row.get("return_20d")
    return_252d = row.get("return_252d")
    pe = row.get("pe_trailing")
    fcf = row.get("free_cash_flow")
    ey = row.get("earnings_yield")
    bar_date = row.get("bar_date") or date.today()

    # Minimum viable evidence.
    if close is None or row.get("asset_kind") != "stock":
        # Value engine is equities-only. ETFs fall through as no_edge.
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=["value engine is equities-only"],
        )

    # Gate 1: must have the fundamental signals. If mart doesn't carry
    # PE / FCF / EY for this name, we have no value opinion.
    if pe is None or fcf is None or ey is None:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=["missing fundamentals for value engine"],
        )

    # Gate 2: negative FCF is a hard veto (consistent with trend).
    # Also veto deeply negative 252d — "cheap and falling" is a trap,
    # not value.
    if fcf < 0:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=["negative TTM FCF → veto"],
        )
    if return_252d is not None and return_252d < -0.20:
        return RankedCandidate(
            symbol=symbol,
            asset_kind=row.get("asset_kind", "stock"),
            posture=POSTURE_NO_EDGE,
            conviction_score=0.0,
            features=row,
            engine=ENGINE_VALUE,
            reasoning_notes=[f"long-term downtrend ({return_252d:+.1%}/252d)"],
        )

    notes: list[str] = []
    posture = POSTURE_VALUE_QUALITY
    base = 0.50

    # Valuation — cheap is the primary signal.
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
        # Extreme cheapness often indicates distress, not value.
        base -= 0.03
        notes.append(f"PE {pe:.1f} (possibly distressed)")

    # Earnings yield — direct cheapness measure.
    if ey > 0.07:
        base += 0.08
        notes.append(f"earnings yield {ey:.1%}")
    elif ey > 0.05:
        base += 0.04
        notes.append(f"earnings yield {ey:.1%}")
    elif ey < 0.02:
        base -= 0.03
        notes.append(f"earnings yield {ey:.1%} (expensive)")

    # Durability — long-term trend should be modestly positive. Value
    # works when the business actually compounds, not when it's stuck.
    if return_252d is not None:
        if return_252d > 0.10:
            base += 0.05
            notes.append(f"long-term trend +{return_252d:.1%}/252d")
        elif return_252d > 0:
            base += 0.02
            notes.append(f"long-term trend +{return_252d:.1%}/252d")

    # Not-extended guard — value and momentum-extension are opposites.
    # Penalize names already well above SMA50 (they belong to trend).
    if sma_50 is not None and sma_50 > 0:
        ext_pct = (close / sma_50) - 1.0
        if ext_pct > 0.10:
            base -= 0.08
            notes.append(f"extended +{ext_pct:.1%} above SMA50 (momentum, not value)")

    # Moderate positive short-term momentum is ok — we don't want to
    # buy a falling name. RSI sanity check.
    if rsi is not None:
        if 40 <= rsi <= 65:
            base += 0.03
            notes.append(f"RSI stable ({rsi:.0f})")
        elif rsi < 30:
            # Oversold value — that's mean-reversion territory; value
            # engine doesn't want to double-count there.
            base -= 0.05
            notes.append(f"RSI oversold ({rsi:.0f}) → mean-rev turf")

    # FCF size signal — larger FCF in absolute $ is a quality proxy
    # for a durable cash-generating business.
    if fcf > 5_000_000_000:
        base += 0.04
        notes.append("robust FCF (>$5B)")

    # Earnings gate — value plays take time, so earnings in window
    # matters more for entry timing than for trend. Same thresholds.
    next_earn = row.get("next_earnings_date")
    if next_earn is not None:
        days_to_earn = (next_earn - bar_date).days
        if 0 <= days_to_earn <= 10:
            posture = POSTURE_NO_EDGE
            base = 0.0
            notes.append(f"earnings in {days_to_earn}d → veto")
        elif 0 <= days_to_earn <= 21:
            base -= 0.05
            notes.append(f"earnings in {days_to_earn}d → caution")

    # Macro-event dampener.
    if posture == POSTURE_VALUE_QUALITY:
        events = baseline.get("upcoming_high_impact_events") or []
        for ev in events:
            days_to_ev = (ev["date"] - bar_date).days
            if 0 <= days_to_ev <= 1:
                base -= 0.05
                notes.append(
                    f"high-impact macro event {ev['event']} in {days_to_ev}d"
                )
                break

    conviction = _clamp(base, 0.0, 1.0)
    if conviction < 0.40:
        posture = POSTURE_NO_EDGE

    return RankedCandidate(
        symbol=symbol,
        asset_kind=row.get("asset_kind", "stock"),
        posture=posture,
        conviction_score=round(conviction, 4),
        features=row,
        engine=ENGINE_VALUE,
        reasoning_notes=notes,
    )


def _draft_plan_value(cand: RankedCandidate) -> RankedCandidate:
    """Entry/stop/target for value candidates.

    Value plays aren't about precise entry — they compound over time.
    Entry is "at market, any day this week" (±1%). Stop is wider (10%
    below close) because short-term noise shouldn't shake the thesis.
    Target is a modest +10% over a 60-day window — cheaper per-diem
    expectation than trend (+8% over 30) because value is patient.
    """
    close = cand.features.get("close")
    if close is None or cand.posture != POSTURE_VALUE_QUALITY:
        return cand

    expression = EXPRESSION_BUY_SHARES
    entry_low = round(close * 0.99, 2)
    entry_high = round(close * 1.01, 2)
    stop = round(close * 0.90, 2)     # wider than trend's 7%
    target = round(close * 1.10, 2)   # modest 10% over 60 days

    bar_date = cand.features.get("bar_date") or date.today()
    time_exit = bar_date + timedelta(days=60)  # patient horizon

    return RankedCandidate(
        symbol=cand.symbol,
        asset_kind=cand.asset_kind,
        posture=cand.posture,
        conviction_score=cand.conviction_score,
        features=cand.features,
        engine=cand.engine,
        proposed_expression=expression,
        proposed_entry_zone=f"${entry_low:.2f}-${entry_high:.2f}",
        proposed_stop=stop,
        proposed_target=target,
        proposed_time_exit=time_exit,
        needs_pullback=False,
        reasoning_notes=cand.reasoning_notes,
    )


def _rank_value(evidence: EvidenceBundle) -> list[RankedCandidate]:
    """Value/quality engine — cheap + durable setups."""
    out: list[RankedCandidate] = []
    for symbol, row in evidence.symbols.items():
        cand = _score_value(symbol, row, evidence.baseline)
        if cand.posture == POSTURE_VALUE_QUALITY:
            cand = _draft_plan_value(cand)
        out.append(cand)
    return out


def _rank_trend(evidence: EvidenceBundle) -> list[RankedCandidate]:
    """Trend-follower engine — the original MEF scorer.

    Rewards continuation/breakout setups: above both SMAs, rising
    slopes, coiled-near-SMA50, MTF consensus, vol contraction, sector
    leadership, with earnings/macro/fundamental gating.
    """
    out: list[RankedCandidate] = []
    for symbol, row in evidence.symbols.items():
        cand = _score_symbol(symbol, row, evidence.baseline)
        if cand.posture in (POSTURE_BULLISH, POSTURE_RANGE_BOUND):
            cand = _draft_plan(cand)
        out.append(cand)
    return out


# Engine registry. Each engine is a callable `(EvidenceBundle) -> list[RankedCandidate]`.
# Every returned candidate must have `engine` set to the registry key so
# downstream code can tag `mef.candidate.engine` correctly. Additional
# engines (mean_reversion, value) land in follow-up commits and register
# themselves here.
ENGINE_REGISTRY: dict[str, Any] = {
    ENGINE_TREND:          _rank_trend,
    ENGINE_MEAN_REVERSION: _rank_mean_reversion,
    ENGINE_VALUE:          _rank_value,
}


def rank(
    evidence: EvidenceBundle,
    *,
    enabled_engines: list[str] | None = None,
) -> list[RankedCandidate]:
    """Run every enabled engine and return a single flat candidate list.

    When ``enabled_engines`` is None, defaults to every engine in the
    registry. Each engine scores independently; results are merged into
    one list sorted by conviction (per-engine top-N selection happens
    in ``select_for_emission`` once multi-engine wiring lands).
    """
    if enabled_engines is None:
        enabled_engines = list(ENGINE_REGISTRY.keys())

    out: list[RankedCandidate] = []
    for engine_name in enabled_engines:
        fn = ENGINE_REGISTRY.get(engine_name)
        if fn is None:
            continue
        for cand in fn(evidence):
            # Force the engine tag on every candidate so registry and
            # output agree even if an engine implementation forgets.
            if cand.engine != engine_name:
                cand = RankedCandidate(
                    symbol=cand.symbol,
                    asset_kind=cand.asset_kind,
                    posture=cand.posture,
                    conviction_score=cand.conviction_score,
                    features=cand.features,
                    engine=engine_name,
                    proposed_expression=cand.proposed_expression,
                    proposed_entry_zone=cand.proposed_entry_zone,
                    proposed_stop=cand.proposed_stop,
                    proposed_target=cand.proposed_target,
                    proposed_time_exit=cand.proposed_time_exit,
                    needs_pullback=cand.needs_pullback,
                    emitted=cand.emitted,
                    reasoning_notes=cand.reasoning_notes,
                )
            out.append(cand)

    out.sort(key=lambda c: c.conviction_score, reverse=True)
    return out


# Postures that any engine considers emittable. Each engine may use
# its own specific posture name (bullish / oversold_bouncing /
# value_quality / range_bound) — all of them are candidates for the
# LLM to review.
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
    """Single-engine selection path: apply threshold + cap across all
    emittable candidates, return flat top-N. Retained for backward
    compat with callers that don't yet use the per-engine selection.
    """
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
    """Per-engine selection: return {engine_name: top-N emittable candidates}.

    The LLM will see the union of every engine's top-N. Each engine's
    threshold is applied independently — engines with different scoring
    scales produce different absolute conviction numbers and this is
    the right unit to cap at.
    """
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
    """Dedup per-engine top-Ns into a unique-by-symbol list for the LLM.

    Returns (unique_candidates, per_symbol_engine_scores). For each
    unique symbol, the returned candidate is the highest-conviction
    version across engines (so the LLM sees a coherent draft plan).
    ``per_symbol_engine_scores`` maps ``symbol -> {engine: conviction}``
    so the prompt can annotate each symbol with its per-engine scores.
    """
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
