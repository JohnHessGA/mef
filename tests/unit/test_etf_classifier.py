"""Unit tests for mef.etf_classifier."""

from __future__ import annotations

import pytest

from mef.etf_classifier import (
    EtfEntryLabel,
    LABELS,
    T,
    classify_etf,
    classify_universe,
)


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _spy(return_63d: float = 0.05) -> dict:
    return {"symbol": "SPY", "return_63d": return_63d}


def _etf(symbol: str = "TEST", **overrides) -> dict:
    """Construct an ETF feature row. Caller supplies whichever fields matter."""
    base = {"symbol": symbol}
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────────
# One test per label
# ──────────────────────────────────────────────────────────────────

def test_breakdown_risk_below_sma200_with_weak_rs():
    row = _etf(
        "IWM",
        close=180.0,
        sma_50=190.0,
        sma_200=205.0,
        rsi_14=42.0,
        drawdown_current=-0.15,
        return_63d=-0.02,  # 4% behind SPY's +0.05 -> rs delta -0.07 < -0.04
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "breakdown_risk"
    assert "below SMA200" in out.reason
    assert "RS vs SPY" in out.reason
    assert out.symbol == "IWM"


def test_breakdown_risk_below_sma200_with_weak_absolute_return():
    row = _etf(
        "BAD",
        close=80.0,
        sma_50=85.0,
        sma_200=95.0,
        rsi_14=40.0,
        drawdown_current=-0.20,
        return_63d=-0.12,
    )
    out = classify_etf(row, spy_features=None)  # no SPY provided
    assert out.label == "breakdown_risk"
    assert "63d return" in out.reason


def test_extended_wait_near_high_and_stretched_above_sma50():
    row = _etf(
        "QQQ",
        close=525.0,
        sma_50=490.0,        # 7.1% above SMA50 — stretched
        sma_200=470.0,
        rsi_14=68.0,
        drawdown_current=-0.005,  # within 2% of high
        return_63d=0.10,
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "extended_wait"
    assert "near recent high" in out.reason
    assert "above SMA50" in out.reason


def test_extended_wait_near_high_with_overbought_rsi():
    row = _etf(
        "QQQ",
        close=505.0,
        sma_50=495.0,        # only 2% above SMA50 — not stretched on its own
        sma_200=470.0,
        rsi_14=75.0,         # overbought triggers it
        drawdown_current=-0.01,
        return_63d=0.08,
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "extended_wait"
    assert "RSI" in out.reason


def test_healthy_pullback_5pct_off_high_above_sma200():
    row = _etf(
        "VUG",
        close=480.0,
        sma_50=485.0,        # close just below SMA50 but within band
        sma_200=460.0,       # above SMA200
        rsi_14=52.0,
        drawdown_current=-0.052,  # 5.2% off peak — healthy pullback
        return_63d=0.04,
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "healthy_pullback"
    assert "5.2%" in out.reason
    assert "above SMA200" in out.reason


def test_near_entry_small_pullback():
    row = _etf(
        "SPY",
        close=545.0,
        sma_50=540.0,
        sma_200=520.0,
        rsi_14=55.0,
        drawdown_current=-0.018,  # 1.8% off peak — between -3% and -0.5%
        return_63d=0.06,
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "near_entry"
    assert "approaching pullback" in out.reason
    assert "1.8%" in out.reason


def test_reasonable_entry_goldilocks():
    row = _etf(
        "SCHD",
        close=88.0,
        sma_50=86.5,         # 1.7% above SMA50 — not stretched
        sma_200=82.0,
        rsi_14=55.0,
        drawdown_current=-0.04,  # outside near-high zone but also outside healthy-pullback range edges
        return_63d=0.04,
    )
    # Note: drawdown_current=-0.04 puts it in the healthy_pullback band
    # (-0.12 ≤ dd ≤ -0.03). To trigger reasonable_entry we need dd
    # outside the pullback band. Adjust:
    row["drawdown_current"] = -0.025  # just below 3% — inside near_entry territory
    # Even -0.025 is inside near_entry. Use a value outside both windows:
    row["drawdown_current"] = -0.005 + 0.0   # dd = -0.005, on near-high edge
    # Actually: rules 2/3/4 all need specific dd; for "reasonable_entry"
    # use dd that is NEITHER near-high nor in the pullback bands. Easiest:
    # leave dd at None — rule 5 doesn't depend on it.
    row["drawdown_current"] = None
    out = classify_etf(row, _spy(0.05))
    assert out.label == "reasonable_entry"
    assert "trend intact" in out.reason


def test_neutral_fallback_when_nothing_fires():
    # Above SMA200 but below SMA50, mild dd outside all bands → no rule fires
    row = _etf(
        "X",
        close=100.0,
        sma_50=102.0,        # below SMA50 — disqualifies reasonable_entry
        sma_200=95.0,        # above SMA200 — disqualifies breakdown_risk
        rsi_14=50.0,
        drawdown_current=-0.14,  # outside healthy_pullback window (-0.12 floor)
        return_63d=0.01,
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "neutral"
    assert out.reason == "no strong entry signal"


# ──────────────────────────────────────────────────────────────────
# Robustness / edge cases
# ──────────────────────────────────────────────────────────────────

def test_missing_data_falls_through_to_neutral():
    row = _etf("EMPTY")  # only symbol
    out = classify_etf(row, spy_features=None)
    assert out.label == "neutral"
    assert out.symbol == "EMPTY"


def test_classifier_tolerates_missing_spy_for_breakdown():
    # Without SPY, RS rule cannot fire, but the absolute-return rule
    # can still trigger breakdown_risk.
    row = _etf(
        "BAD",
        close=80.0, sma_50=85.0, sma_200=95.0,
        return_63d=-0.10,
    )
    out = classify_etf(row, spy_features=None)
    assert out.label == "breakdown_risk"


def test_components_are_populated():
    row = _etf("VUG", close=480, sma_50=485, sma_200=460, rsi_14=52,
               drawdown_current=-0.052, return_63d=0.04)
    out = classify_etf(row, _spy(0.05))
    assert out.components["close"] == 480
    assert out.components["sma_200"] == 460
    assert out.components["rs_vs_spy_63d"] == pytest.approx(-0.01, rel=1e-3)
    assert out.components["pct_above_sma200"] == pytest.approx((480 - 460) / 460, rel=1e-3)


def test_label_is_one_of_six_known_labels():
    # Sweep a handful of synthetic rows and ensure no rogue labels.
    rows = [
        _etf("A"),
        _etf("B", close=100, sma_50=95, sma_200=90, rsi_14=50, drawdown_current=-0.05, return_63d=0.03),
        _etf("C", close=80, sma_50=85, sma_200=95, return_63d=-0.10),
        _etf("D", close=520, sma_50=485, sma_200=460, rsi_14=70, drawdown_current=-0.005, return_63d=0.10),
    ]
    for r in rows:
        out = classify_etf(r, _spy(0.05))
        assert out.label in LABELS


def test_classify_universe_returns_one_per_symbol_sorted():
    etfs = {
        "ZZZ": _etf("ZZZ", close=100, sma_50=95, sma_200=90, rsi_14=55,
                    drawdown_current=-0.05, return_63d=0.04),
        "AAA": _etf("AAA", close=80, sma_50=85, sma_200=95, return_63d=-0.10),
        "SPY": _etf("SPY", close=550, sma_50=540, sma_200=520, rsi_14=55,
                    drawdown_current=-0.018, return_63d=0.05),
    }
    out = classify_universe(etfs)
    assert [e.symbol for e in out] == ["AAA", "SPY", "ZZZ"]
    assert all(isinstance(e, EtfEntryLabel) for e in out)


def test_data_anomaly_guard_short_circuits_to_neutral():
    # Mimics the live VUG/IWF case — close has been split-adjusted but
    # SMA values are still pre-split. The classifier should refuse to
    # call this "breakdown_risk" and instead emit a neutral with a
    # data-anomaly reason so the operator notices the upstream issue.
    row = _etf(
        "VUG",
        close=83.72,
        sma_50=397.26,
        sma_200=456.46,
        rsi_14=55.0,
        drawdown_current=-0.80,
        return_63d=-0.83,
    )
    out = classify_etf(row, _spy(0.05))
    assert out.label == "neutral"
    assert "data anomaly" in out.reason.lower()
    assert "split" in out.reason.lower()


def test_threshold_dict_is_complete():
    # Sanity guard so a future tweak doesn't drop a key the classifier reads.
    expected = {
        "near_high_dd", "stretched_above_sma50", "rsi_overbought",
        "rsi_oversold", "rsi_warm", "rsi_cool",
        "pullback_min_dd", "pullback_max_dd",
        "near_entry_min_dd", "near_entry_max_dd",
        "reasonable_max_above_sma50", "rs_weak_63d", "ret63d_weak",
        "pullback_sma50_band", "data_anomaly_sma50_gap",
    }
    assert expected.issubset(T.keys())
