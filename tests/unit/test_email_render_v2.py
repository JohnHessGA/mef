"""Tests for the v2 email renderer — R:R block and LLM-gate footer."""

from __future__ import annotations

from datetime import date, datetime, timezone

from mef.email_render import render_daily_email


def _time():
    return datetime(2026, 4, 19, 12, 30, tzinfo=timezone.utc)


def _idea(**kwargs):
    base = {
        "rec_uid":    "R-000001",
        "symbol":     "AAPL",
        "asset_kind": "stock",
        "posture":    "bullish",
        "expression": "buy_shares",
        "entry_zone": "$270-$275",
        "stop":       260.00,
        "target":     295.00,
        "time_exit":  date(2026, 5, 19),
        "potential_gain_100sh": 2500.00,
        "potential_loss_100sh": 1000.00,
        "risk_reward":          2.5,
        "reasoning_summary":    "coherent plan; above SMA50/200",
        "llm_gate": "approve",
    }
    base.update(kwargs)
    return base


def test_idea_includes_risk_reward_block():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-1", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
    )
    assert "Per 100 shares:" in email.body
    assert "+$2,500.00" in email.body
    assert "risk $1,000.00" in email.body
    assert "R:R 2.50:1" in email.body


def test_not_reviewed_footer_when_gate_unavailable_wholesale():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-2", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea(llm_gate="unavailable")],
        llm_gate_available=False,
    )
    assert "LLM gate was unavailable" in email.body
    assert "Not reviewed by LLM" in email.body


def test_rejected_counter_when_all_rejected():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-3", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[],
        llm_gate_rejected=5,
    )
    assert "No new trades today." in email.body
    assert "rejected 5 candidate(s)" in email.body


def test_rejected_counter_when_partial():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-4", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        llm_gate_rejected=2,
    )
    assert "rejected 2 candidate(s) from the top list" in email.body
