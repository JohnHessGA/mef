"""Forward-walk classifier for shadow scoring of rejected candidates.

The pure classifier (``classify_walk``) takes the close series the
symbol *actually* traded at after the candidate's run-date and decides
win / loss / timeout / defer. We exercise every branch without a DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from mef.shadow_scoring import classify_walk


def _b(*pairs):
    """Convenience: build a bars list from (YYYY-MM-DD, close) pairs."""
    return [(date.fromisoformat(d), D(str(c)) if c is not None else None) for d, c in pairs]


def test_win_on_first_close_at_or_above_target():
    bars = _b(("2026-04-20", "100.00"), ("2026-04-21", "105.00"), ("2026-04-22", "110.00"))
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=D("90.00"), target=D("105.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome == "win"
    assert exit_price == D("105.00")
    assert exit_date == date(2026, 4, 21)


def test_loss_on_first_close_at_or_below_stop():
    bars = _b(("2026-04-20", "98.00"), ("2026-04-21", "92.00"), ("2026-04-22", "85.00"))
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=D("92.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome == "loss"
    assert exit_price == D("92.00")
    assert exit_date == date(2026, 4, 21)


def test_first_breach_wins_over_later_breach():
    # Bars hit stop on day 2 then target on day 3 — must settle on day 2.
    bars = _b(("2026-04-20", "98.00"), ("2026-04-21", "85.00"), ("2026-04-22", "120.00"))
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome == "loss"
    assert exit_date == date(2026, 4, 21)


def test_timeout_when_window_elapsed_with_no_breach():
    bars = _b(("2026-04-20", "100.00"), ("2026-04-21", "101.00"), ("2026-04-22", "100.50"))
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 4, 22), today=date(2026, 4, 22),
    )
    assert outcome == "timeout"
    assert exit_price == D("100.50")
    assert exit_date == date(2026, 4, 22)


def test_defer_when_window_not_elapsed_and_no_breach():
    bars = _b(("2026-04-20", "100.00"), ("2026-04-21", "101.00"))
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome is None
    assert exit_price is None
    assert exit_date is None


def test_empty_bars_with_elapsed_window_is_timeout_with_null_exit():
    outcome, exit_price, exit_date = classify_walk(
        [], stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 4, 22), today=date(2026, 4, 22),
    )
    assert outcome == "timeout"
    assert exit_price is None
    assert exit_date is None


def test_empty_bars_with_open_window_defers():
    outcome, exit_price, exit_date = classify_walk(
        [], stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome is None


def test_none_close_in_bars_is_skipped_not_treated_as_breach():
    bars = _b(("2026-04-20", None), ("2026-04-21", "120.00"))
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome == "win"
    assert exit_date == date(2026, 4, 21)


def test_target_hit_at_exact_threshold_is_win():
    bars = _b(("2026-04-20", "110.00"))
    outcome, _, _ = classify_walk(
        bars, stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome == "win"


def test_stop_hit_at_exact_threshold_is_loss():
    bars = _b(("2026-04-20", "90.00"))
    outcome, _, _ = classify_walk(
        bars, stop=D("90.00"), target=D("110.00"),
        time_exit=date(2026, 5, 30), today=date(2026, 4, 22),
    )
    assert outcome == "loss"
