"""Unit tests for the close classifier used by the lifecycle sweep."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from mef.lifecycle import _classify_close


def test_close_above_target_is_win():
    out = _classify_close(
        last_price=Decimal("1700"),
        stop=Decimal("1440"),
        target=Decimal("1672"),
        time_exit=date(2026, 5, 7),
        as_of=date(2026, 4, 30),
    )
    assert out == "closed_win"


def test_close_below_stop_is_loss():
    out = _classify_close(
        last_price=Decimal("430"),
        stop=Decimal("436"),
        target=Decimal("506"),
        time_exit=date(2026, 5, 7),
        as_of=date(2026, 4, 30),
    )
    assert out == "closed_loss"


def test_in_between_and_past_time_exit_is_timeout():
    out = _classify_close(
        last_price=Decimal("460"),
        stop=Decimal("436"),
        target=Decimal("506"),
        time_exit=date(2026, 4, 20),
        as_of=date(2026, 4, 22),
    )
    assert out == "closed_timeout"


def test_in_between_before_time_exit_still_timeout():
    # Position was closed manually with price in the middle of the plan.
    out = _classify_close(
        last_price=Decimal("460"),
        stop=Decimal("436"),
        target=Decimal("506"),
        time_exit=date(2026, 5, 7),
        as_of=date(2026, 4, 25),
    )
    assert out == "closed_timeout"


def test_missing_price_falls_back_to_timeout():
    out = _classify_close(
        last_price=None,
        stop=Decimal("436"),
        target=Decimal("506"),
        time_exit=date(2026, 5, 7),
        as_of=date(2026, 4, 25),
    )
    assert out == "closed_timeout"
