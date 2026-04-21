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
    assert "5 rejected" in email.body


def test_rejected_counter_when_partial():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-4", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        llm_gate_rejected=2,
    )
    assert "2 rejected" in email.body


def test_review_count_in_footer_when_present():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-7", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        llm_gate_review=3,
        llm_gate_rejected=2,
    )
    # Both held-and-rejected counts appear in the same "Also from this run" line.
    assert "3 held for review" in email.body
    assert "2 rejected" in email.body
    assert "Also from this run" in email.body


def test_review_only_no_rejected():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-8", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        llm_gate_review=2,
    )
    assert "2 held for review" in email.body
    assert "rejected" not in email.body.lower() or "Also from this run: 2 held" in email.body


def test_review_ideas_render_in_dedicated_section_with_reasoning():
    # When review_ideas is passed, the email must render them explicitly
    # (not just a footer count) and must include each idea's LLM reasoning
    # so the user can decide whether to act manually.
    email = render_daily_email(
        when_kind="postmarket", intent="next_trading_day",
        run_uid="DR-9", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea(symbol="WMT")],
        review_ideas=[
            _idea(
                rec_uid="R-REV-1", symbol="TSLA", llm_gate="review",
                reasoning_summary="RSI extended, entering near peak after -18% drawdown",
            ),
            _idea(
                rec_uid="R-REV-2", symbol="AEP", llm_gate="review",
                reasoning_summary="Current price exceeds entry range; MACD nearly flat",
            ),
        ],
    )
    body = email.body
    assert "Held for review (2)" in body
    assert "TSLA" in body and "AEP" in body
    assert "RSI extended" in body
    assert "MACD nearly flat" in body
    # When review_ideas are rendered, the footer must NOT double-count them.
    assert "held for review (logged" not in body


def test_review_footer_count_fallback_when_ideas_not_passed():
    # Staleness / abort paths may still pass only the integer count.
    # That path should keep rendering the footer summary.
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-10", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        llm_gate_review=3,
    )
    assert "3 held for review" in email.body


def test_earnings_annotation_on_idea_line():
    from datetime import date as _date, timedelta as _td
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-E1", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea(next_earnings_date=_date.today() + _td(days=14))],
    )
    assert "📅 earnings in 14d" in email.body


def test_upcoming_macro_banner_in_header():
    from datetime import date as _date, timedelta as _td
    events = [
        {"date": _date.today() + _td(days=1), "event": "Retail Sales MoM (Mar)"},
        {"date": _date.today() + _td(days=2), "event": "Fed Interest Rate Decision"},
    ]
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-M1", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        upcoming_macro_events=events,
    )
    assert "Upcoming high-impact US macro events" in email.body
    assert "Retail Sales MoM" in email.body
    assert "Fed Interest Rate Decision" in email.body


def test_macro_banner_hidden_when_no_events():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-M2", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        upcoming_macro_events=[],
    )
    assert "Upcoming high-impact" not in email.body


def test_staleness_warning_banner_when_warn_only():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-5", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[_idea()],
        staleness_warning="latest mart bar_date=2026-04-13 is 6 day(s) behind today",
    )
    assert "older than expected" in email.body
    assert "2026-04-13" in email.body
    assert "[STALE DATA]" not in email.subject  # warn-only doesn't tag the subject


def test_staleness_aborted_tags_subject_and_skips_ideas_section():
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-6", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=15,
        new_ideas=[],
        staleness_warning="latest mart bar_date=2026-04-10 is 9 day(s) behind today",
        staleness_aborted=True,
    )
    assert email.subject.startswith("[STALE DATA] ")
    assert "RUN ABORTED" in email.body
    assert "2026-04-10" in email.body
    # User should still see the universe header so they know what was checked.
    assert "Universe: 305 stocks" in email.body
