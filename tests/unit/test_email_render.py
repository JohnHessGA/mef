"""Unit tests for mef.email_render."""

from __future__ import annotations

from datetime import datetime, timezone

from mef.email_render import render_daily_email


def _fixed_time():
    return datetime(2026, 4, 19, 12, 30, tzinfo=timezone.utc)


def test_render_empty_is_no_new_trades():
    email = render_daily_email(
        when_kind="premarket",
        intent="today_after_10am",
        run_uid="DR-000001",
        started_at=_fixed_time(),
        stocks_in_universe=305,
        etfs_in_universe=15,
    )
    assert email.subject.startswith("MEF pre-market report")
    assert "2026-04-19" in email.subject
    assert "No new trades today." in email.body
    assert "305 stocks, 15 ETFs" in email.body
    assert "DR-000001" in email.body


def test_render_postmarket_subject():
    email = render_daily_email(
        when_kind="postmarket",
        intent="next_trading_day",
        run_uid="DR-000002",
        started_at=_fixed_time(),
        stocks_in_universe=305,
        etfs_in_universe=15,
    )
    assert email.subject.startswith("MEF post-market report")
    assert "next trading day" in email.subject


def test_render_new_ideas_listed():
    email = render_daily_email(
        when_kind="premarket",
        intent="today_after_10am",
        run_uid="DR-000003",
        started_at=_fixed_time(),
        stocks_in_universe=305,
        etfs_in_universe=15,
        new_ideas=[
            {"symbol": "AAPL", "posture": "bullish", "expression": "buy_shares",
             "reasoning_summary": "Above 50d, near support."},
            {"symbol": "SPY",  "posture": "range_bound", "expression": "covered_call",
             "reasoning_summary": "Low-vol regime."},
        ],
    )
    assert "New ideas (2):" in email.body
    assert "AAPL" in email.body and "SPY" in email.body
    assert "Above 50d" in email.body
    assert "No new trades today." not in email.body
