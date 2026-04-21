"""Unit tests for Layer A eligibility."""

from __future__ import annotations

from datetime import date

from mef.eligibility import EARNINGS_WINDOW_DAYS, check


def _stock(**over):
    base = {
        "symbol": "AAA", "asset_kind": "stock",
        "bar_date": date(2026, 4, 17),
        "close": 100.0, "next_earnings_date": None,
    }
    base.update(over)
    return base


def _etf(**over):
    base = {
        "symbol": "SPY", "asset_kind": "etf",
        "bar_date": date(2026, 4, 17),
        "close": 500.0, "next_earnings_date": None,
    }
    base.update(over)
    return base


def test_no_row_fails():
    r = check("X", None, engine="trend")
    assert r.passed is False
    assert any("no mart evidence" in reason for reason in r.reasons)


def test_null_close_fails():
    r = check("X", _stock(close=None), engine="trend")
    assert r.passed is False
    assert any("close is null" in reason for reason in r.reasons)


def test_no_earnings_date_passes():
    r = check("X", _stock(), engine="trend")
    assert r.passed is True
    assert r.reasons == []


def test_trend_blocks_earnings_within_5_days():
    # 3 days to earnings, trend window is 5d → blackout.
    row = _stock(next_earnings_date=date(2026, 4, 20))
    r = check("X", row, engine="trend")
    assert r.passed is False
    assert any("earnings in 3d" in reason for reason in r.reasons)


def test_trend_passes_earnings_past_5_day_window():
    # 7 days out → outside trend's 5d blackout → Layer A passes.
    row = _stock(next_earnings_date=date(2026, 4, 24))
    r = check("X", row, engine="trend")
    assert r.passed is True


def test_mean_rev_blocks_earnings_within_10_days():
    # 8 days out: still inside mean_rev's 10d blackout.
    row = _stock(next_earnings_date=date(2026, 4, 25))
    r = check("X", row, engine="mean_reversion")
    assert r.passed is False


def test_value_blocks_earnings_within_10_days():
    # 8 days out: inside value's 10d blackout.
    row = _stock(next_earnings_date=date(2026, 4, 25))
    r = check("X", row, engine="value")
    assert r.passed is False


def test_per_engine_windows_differ():
    # 7 days out → trend passes (5d), mean_rev + value block (10d).
    row = _stock(next_earnings_date=date(2026, 4, 24))
    assert check("X", row, engine="trend").passed is True
    assert check("X", row, engine="mean_reversion").passed is False
    assert check("X", row, engine="value").passed is False


def test_etfs_skip_earnings_check():
    # ETFs don't report earnings — any earnings-date field on an ETF row
    # is ignored by Layer A.
    row = _etf(next_earnings_date=date(2026, 4, 20))  # nonsensical but possible
    assert check("SPY", row, engine="trend").passed is True


def test_earnings_date_in_past_does_not_block():
    # Only 0 ≤ days_to_earn ≤ window blocks — past-dated announcements
    # are ignored.
    row = _stock(next_earnings_date=date(2026, 4, 10))  # 7d ago
    assert check("X", row, engine="trend").passed is True


def test_window_table_values_match_expectations():
    # Guards against accidental off-by-one changes during future refactors.
    assert EARNINGS_WINDOW_DAYS["trend"] == 5
    assert EARNINGS_WINDOW_DAYS["mean_reversion"] == 10
    assert EARNINGS_WINDOW_DAYS["value"] == 10
