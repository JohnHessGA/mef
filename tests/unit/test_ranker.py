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
        "return_20d": 0.03, "return_63d": 0.05,
        "rsi_14": 55.0, "macd_histogram": 0.5,
        "realized_vol_20d": 0.15, "drawdown_current": -0.02,
        "volume_z_score": 0.2, "sector": "Technology",
        "trend_above_sma50": True, "trend_above_sma200": True,
    }
    base.update(kwargs)
    return base


def _bundle(rows: dict[str, dict], spy_ret20: float = 0.01):
    return EvidenceBundle(
        as_of_date=date(2026, 4, 17),
        baseline={"spy_return_20d": spy_ret20, "spy_return_63d": 0.02},
        symbols=rows,
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


def test_spy_relative_boost_vs_penalty():
    better_than_spy = rank(_bundle({"S": _row(symbol="S", return_20d=0.08)}, spy_ret20=0.01))
    worse_than_spy = rank(_bundle({"S": _row(symbol="S", return_20d=-0.05)}, spy_ret20=0.04))
    assert better_than_spy[0].conviction_score > worse_than_spy[0].conviction_score
