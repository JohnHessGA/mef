"""Unit tests for the ranker v0 scoring rules.

Pure-function tests. No DB, no SHDB. Each test builds an EvidenceBundle
with one or two synthetic symbols and asserts on the output.
"""

from __future__ import annotations

from datetime import date

import pytest

from mef.evidence import EvidenceBundle
from mef.ranker import (
    POSTURE_BEARISH_CAUTION,
    POSTURE_BULLISH,
    POSTURE_NO_EDGE,
    POSTURE_RANGE_BOUND,
    rank,
    select_for_emission,
)


def _row(**kwargs):
    """Build a synthetic feature row with sensible defaults."""
    base = {
        "symbol": "TEST", "asset_kind": "stock", "bar_date": date(2026, 4, 17),
        "close": 100.0, "sma_20": 98.0, "sma_50": 95.0, "sma_200": 90.0,
        # sma_slopes default to a clearly rising trend so baseline tests
        # don't accidentally trigger chop detection. flat_th at close=100
        # is 0.08, so 0.2 sits firmly in "rising" territory.
        "sma_20_slope": 0.20, "sma_50_slope": 0.15,
        # Default multi-timeframe returns: constructive, no disagreements,
        # so baseline tests don't accidentally trip MTF penalties.
        "return_5d": 0.005, "return_20d": 0.03, "return_63d": 0.05,
        "return_126d": 0.08, "return_252d": 0.12,
        "rsi_14": 55.0, "macd_histogram": 0.5,
        # Relative-strength defaults: modest outperformance vs SPY and
        # QQQ so baseline tests don't inadvertently trip RS penalties.
        "rs_vs_spy_20d": 0.02, "rs_vs_spy_63d": 0.03, "rs_vs_qqq_63d": 0.01,
        "realized_vol_20d": 0.15, "realized_vol_63d": 0.16,
        "drawdown_current": -0.02,
        "volume_z_score": 0.2, "sector": "Technology",
        # Fundamentals defaults — healthy large-cap profile so baseline
        # tests don't accidentally trigger the veto or penalties.
        "free_cash_flow": 5_000_000_000.0, "pe_trailing": 25.0,
        "earnings_yield": 0.04,
        "trend_above_sma50": True, "trend_above_sma200": True,
    }
    base.update(kwargs)
    return base


def _bundle(rows: dict[str, dict], spy_ret20: float = 0.01, sector_returns_63d=None):
    baseline = {
        "spy_return_20d":     spy_ret20,
        "spy_return_63d":     0.02,
        "sector_returns_63d": sector_returns_63d or {},
    }
    return EvidenceBundle(
        as_of_date=date(2026, 4, 17), baseline=baseline, symbols=rows,
    )


def test_bullish_uptrend_with_healthy_rsi_emits():
    cands = rank(_bundle({"AAPL": _row(symbol="AAPL")}))
    assert len(cands) == 1
    c = cands[0]
    assert c.posture == POSTURE_BULLISH
    assert c.conviction_score >= 0.70
    assert c.proposed_expression == "buy_shares"
    assert c.proposed_stop is not None and c.proposed_stop < c.features["close"]
    assert c.proposed_target is not None and c.proposed_target > c.features["close"]


def test_below_both_smas_is_bearish_caution():
    cands = rank(_bundle({"X": _row(
        symbol="X", close=80.0, sma_50=95.0, sma_200=90.0,
        trend_above_sma50=False, trend_above_sma200=False,
    )}))
    assert cands[0].posture == POSTURE_BEARISH_CAUTION


def test_overbought_uptrend_becomes_range_bound():
    cands = rank(_bundle({"Y": _row(symbol="Y", rsi_14=78.0)}))
    assert cands[0].posture == POSTURE_RANGE_BOUND


def test_mixed_trend_is_range_bound():
    cands = rank(_bundle({"Z": _row(
        symbol="Z", trend_above_sma50=True, trend_above_sma200=False,
    )}))
    assert cands[0].posture == POSTURE_RANGE_BOUND


def test_missing_sma_is_no_edge():
    cands = rank(_bundle({"Q": _row(symbol="Q", sma_50=None, sma_200=None)}))
    assert cands[0].posture == POSTURE_NO_EDGE
    assert cands[0].conviction_score == 0.0


def test_deep_drawdown_penalty():
    weak_bullish = _row(symbol="W", drawdown_current=-0.25)
    cands = rank(_bundle({"W": weak_bullish}))
    # Still bullish but scored lower.
    no_dd = rank(_bundle({"W": _row(symbol="W", drawdown_current=-0.05)}))
    assert cands[0].conviction_score < no_dd[0].conviction_score


def test_select_for_emission_applies_threshold_and_cap():
    bundle = _bundle({
        "A": _row(symbol="A"),
        "B": _row(symbol="B", return_20d=0.05, volume_z_score=1.2),
        "C": _row(symbol="C", trend_above_sma50=False, trend_above_sma200=False),  # bearish
    })
    cands = rank(bundle)

    survivors = select_for_emission(cands, conviction_threshold=0.5, max_new_ideas=5)
    assert all(c.posture in ("bullish", "range_bound") for c in survivors)
    # C is bearish so it's never in survivors.
    assert "C" not in {c.symbol for c in survivors}

    survivors_capped = select_for_emission(cands, conviction_threshold=0.5, max_new_ideas=1)
    assert len(survivors_capped) == 1


def test_negative_fcf_vetos_regardless_of_momentum():
    # Even a perfectly trending stock is vetoed if TTM FCF is negative.
    cand = rank(_bundle({"BURN": _row(symbol="BURN", free_cash_flow=-1e9)}))[0]
    assert cand.posture == POSTURE_NO_EDGE
    assert any("free cash flow" in n for n in cand.reasoning_notes)


def test_extreme_pe_applies_soft_penalty():
    cheap = rank(_bundle({"C": _row(symbol="C", pe_trailing=20)}))[0]
    expensive = rank(_bundle({"E": _row(symbol="E", pe_trailing=80)}))[0]
    assert cheap.conviction_score > expensive.conviction_score
    assert any("extreme PE" in n for n in expensive.reasoning_notes)


def test_etf_fundamentals_are_ignored():
    # ETFs don't carry TTM FCF / PE in the same way — a NULL fundamental
    # row must NOT veto or penalize an ETF candidate.
    cand = rank(_bundle({"SPY": _row(
        symbol="SPY", asset_kind="etf", sector=None,
        free_cash_flow=None, pe_trailing=None, earnings_yield=None,
    )}))[0]
    assert cand.posture != POSTURE_NO_EDGE
    assert not any("free cash flow" in n for n in cand.reasoning_notes)
    assert not any("PE" in n for n in cand.reasoning_notes)


def test_vol_contraction_bonus_vs_expansion_penalty():
    coiled = rank(_bundle({"A": _row(realized_vol_20d=0.10, realized_vol_63d=0.18)}))[0]
    neutral = rank(_bundle({"A": _row(realized_vol_20d=0.15, realized_vol_63d=0.16)}))[0]
    expanding = rank(_bundle({"A": _row(realized_vol_20d=0.25, realized_vol_63d=0.15)}))[0]
    assert coiled.conviction_score > neutral.conviction_score
    assert expanding.conviction_score < neutral.conviction_score
    assert any("coiled" in n for n in coiled.reasoning_notes)


def test_mtf_no_disagreements_gives_bonus():
    clean = rank(_bundle({"A": _row()}))[0]
    # 2 mtf disagreements: 63d and 126d both outside thresholds.
    # (V-recovery thresholds: 63d < -10%, 126d < -15%.)
    noisy = rank(_bundle({"A": _row(return_63d=-0.12, return_126d=-0.18)}))[0]
    assert clean.conviction_score > noisy.conviction_score
    assert any("no timeframe in strong disagreement" in n for n in clean.reasoning_notes)


def test_mtf_recovery_context_does_not_punish_mild_long_term_negativity():
    # In a V-recovery, 126d and 252d can be modestly negative even for
    # good stocks. -10% on 126d and -15% on 252d must NOT trigger any
    # disagreement (thresholds are -15% and -25% respectively).
    recovery = rank(_bundle({"R": _row(return_126d=-0.10, return_252d=-0.15)}))[0]
    # Should still get the "no disagreements" full bonus.
    assert any("no timeframe in strong disagreement" in n for n in recovery.reasoning_notes)


def test_mtf_falling_this_week_applies_standalone_brake():
    # TSLA case: -3% this week should trigger the 5d brake even when the
    # structural disagreement count is fine. Penalty independent of count.
    falling = rank(_bundle({"T": _row(return_5d=-0.03)}))[0]
    ok = rank(_bundle({"T": _row(return_5d=0.005)}))[0]
    assert falling.conviction_score < ok.conviction_score
    assert any("falling this week" in n for n in falling.reasoning_notes)


def test_flat_smas_above_support_flip_to_range_bound():
    # Both SMAs essentially flat → stock is chopping above support, not
    # actually trending. Should NOT score as bullish.
    chop = _row(sma_20_slope=0.01, sma_50_slope=0.02)  # <<< flat threshold 0.08
    cand = rank(_bundle({"WMT": chop}))[0]
    assert cand.posture == POSTURE_RANGE_BOUND
    # And the note explains why, for audit.
    assert any("SMAs flat" in n for n in cand.reasoning_notes)


def test_sma20_rolling_over_penalizes():
    # Falling SMA20 = short-term trend has rolled over, even if close is
    # still above. Penalty relative to a rising-slope control.
    rolling = rank(_bundle({"X": _row(sma_20_slope=-0.5)}))[0]
    rising = rank(_bundle({"X": _row(sma_20_slope=0.5)}))[0]
    assert rolling.conviction_score < rising.conviction_score


def test_needs_pullback_anchors_entry_below_close():
    # drawdown_current ≈ 0 → stock is at its recent peak; the draft plan
    # must anchor the entry zone to a pullback target (sma_20 or below),
    # not the current close.
    at_peak = _row(
        symbol="P", close=100.0, sma_20=92.0, sma_50=88.0,
        drawdown_current=0.0, atr_14=2.0,
    )
    cand = rank(_bundle({"P": at_peak}))[0]
    assert cand.needs_pullback is True
    # Entry high should be meaningfully below close (at least 2% below).
    # Parse the "$low-$high" zone string for the upper bound.
    high_str = cand.proposed_entry_zone.split("-$")[1]
    entry_high = float(high_str)
    assert entry_high <= 98.0, f"entry_high {entry_high} should be ≤98.0"
    # Stop should still be below entry, target above close.
    assert cand.proposed_stop < entry_high
    assert cand.proposed_target > 100.0

    # Control: the same row with a real pullback (dd = -5%) does NOT flag.
    pulled_back = _row(
        symbol="Q", close=100.0, sma_20=92.0, sma_50=88.0,
        drawdown_current=-0.05, atr_14=2.0,
    )
    ctrl = rank(_bundle({"Q": pulled_back}))[0]
    assert ctrl.needs_pullback is False
    ctrl_high = float(ctrl.proposed_entry_zone.split("-$")[1])
    assert ctrl_high >= 99.0, f"control entry_high {ctrl_high} should be close to 100"


def test_spy_relative_boost_vs_penalty():
    better_than_spy = rank(_bundle({"S": _row(symbol="S", rs_vs_spy_20d=0.07)}))
    worse_than_spy = rank(_bundle({"S": _row(symbol="S", rs_vs_spy_20d=-0.09)}))
    assert better_than_spy[0].conviction_score > worse_than_spy[0].conviction_score


def test_sector_relative_strength_bonus_vs_penalty():
    # Tech stock beating XLK by 5% over 63d → bonus.
    leader = rank(_bundle(
        {"TECHCO": _row(symbol="TECHCO", sector="Technology", return_63d=0.12)},
        sector_returns_63d={"XLK": 0.05},
    ))[0]
    # Same stock lagging its sector by 8% → penalty.
    laggard = rank(_bundle(
        {"TECHCO": _row(symbol="TECHCO", sector="Technology", return_63d=-0.03)},
        sector_returns_63d={"XLK": 0.05},
    ))[0]
    assert leader.conviction_score > laggard.conviction_score
    assert any("beating Technology sector" in n for n in leader.reasoning_notes)


def test_sector_unmapped_falls_through_cleanly():
    # Utilities has no mapped sector ETF — ranker must not error; just no
    # sector-relative score applied.
    cand = rank(_bundle({"U": _row(symbol="U", sector="Utilities")}))[0]
    # Should score normally without sector notes.
    assert cand.posture in ("bullish", "range_bound", "no_edge")
    assert not any("sector" in n for n in cand.reasoning_notes)


def test_qqq_relative_bonus_and_penalty():
    beating_qqq = rank(_bundle({"X": _row(symbol="X", rs_vs_qqq_63d=0.08)}))[0]
    lagging_qqq = rank(_bundle({"X": _row(symbol="X", rs_vs_qqq_63d=-0.12)}))[0]
    assert beating_qqq.conviction_score > lagging_qqq.conviction_score
