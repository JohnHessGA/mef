"""Aggregator for the LLM-gate audit. Pure: feed in row dicts, get
back an OutcomeStats. The CLI formatter is exercised separately via
end-to-end runs against the live DB.
"""

from __future__ import annotations

from mef.gate_audit import MIN_SAMPLE_FOR_SIGNAL, OutcomeStats, aggregate


def _row(**kwargs):
    base = {
        "outcome": "win",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "days_held": 10,
        "estimated_pnl_100_shares_usd": 1000.00,
        "spy_return_same_window": 0.02,
        "sector_etf_return_same_window": 0.04,
    }
    base.update(kwargs)
    return base


def test_empty_aggregate():
    s = aggregate([], label="approved")
    assert s.n == 0
    assert s.win_rate is None
    assert s.avg_pnl_100sh is None
    assert s.avg_spy_relative is None
    assert s.avg_sector_relative is None
    assert s.avg_days_held is None
    assert not s.has_signal_quality_sample


def test_win_rate_and_pnl_basic():
    rows = [
        _row(outcome="win",     estimated_pnl_100_shares_usd=1000.00),
        _row(outcome="win",     estimated_pnl_100_shares_usd=500.00),
        _row(outcome="loss",    estimated_pnl_100_shares_usd=-700.00),
        _row(outcome="timeout", estimated_pnl_100_shares_usd=200.00),
    ]
    s = aggregate(rows, label="approved")
    assert s.n == 4
    assert s.wins == 2 and s.losses == 1 and s.timeouts == 1
    assert s.win_rate == 0.5
    assert s.avg_pnl_100sh == (1000.00 + 500.00 - 700.00 + 200.00) / 4


def test_spy_relative_uses_per_row_paper_return_minus_spy():
    # entry=100, exit=110 → paper_return = +10%. spy=+2% → spy_rel = +8%.
    rows = [_row(entry_price=100.0, exit_price=110.0, spy_return_same_window=0.02)]
    s = aggregate(rows, label="x")
    assert s.avg_spy_relative is not None
    assert abs(s.avg_spy_relative - 0.08) < 1e-9


def test_sector_relative_separate_from_spy():
    # entry=100, exit=90 → paper_return = -10%. sector=-3% → sector_rel = -7%.
    rows = [_row(entry_price=100.0, exit_price=90.0, sector_etf_return_same_window=-0.03,
                 spy_return_same_window=None)]
    s = aggregate(rows, label="x")
    assert s.avg_spy_relative is None  # missing field skipped
    assert s.avg_sector_relative is not None
    assert abs(s.avg_sector_relative - (-0.07)) < 1e-9


def test_missing_optional_fields_dont_break_or_pollute_averages():
    rows = [
        _row(estimated_pnl_100_shares_usd=None, days_held=None,
             spy_return_same_window=None, sector_etf_return_same_window=None),
        _row(estimated_pnl_100_shares_usd=300.00, days_held=5,
             spy_return_same_window=0.01, sector_etf_return_same_window=0.02),
    ]
    s = aggregate(rows, label="x")
    assert s.n == 2
    assert s.avg_pnl_100sh == 300.00       # only the row with data contributes
    assert s.avg_days_held == 5.0


def test_zero_entry_price_does_not_divide_by_zero():
    rows = [_row(entry_price=0.0, exit_price=10.0)]
    s = aggregate(rows, label="x")
    # spy_relative requires entry != 0; the row should be silently skipped
    # for the relative-return averages, but still count toward n / win_rate.
    assert s.n == 1
    assert s.spy_rel_count == 0
    assert s.avg_spy_relative is None


def test_signal_quality_threshold():
    s = OutcomeStats(label="x")
    s.n = MIN_SAMPLE_FOR_SIGNAL - 1
    assert not s.has_signal_quality_sample
    s.n = MIN_SAMPLE_FOR_SIGNAL
    assert s.has_signal_quality_sample


def test_outcome_breakdown_counts_each_kind_independently():
    rows = [
        _row(outcome="win"),  _row(outcome="win"),  _row(outcome="win"),
        _row(outcome="loss"), _row(outcome="loss"),
        _row(outcome="timeout"),
    ]
    s = aggregate(rows, label="x")
    assert s.by_outcome == {"win": 3, "loss": 2, "timeout": 1}
