"""Data-freshness gate classifies the latest mart bar against thresholds.

The check is a pure function over an EvidenceBundle + a reference 'today',
so we can exercise every status branch without hitting the database.
"""

from __future__ import annotations

from datetime import date

from mef.evidence import EvidenceBundle, FreshnessReport, check_freshness


def _bundle(as_of: date | None, *, with_symbols: bool = True) -> EvidenceBundle:
    symbols = {"AAPL": {"close": 100.0}} if with_symbols else {}
    return EvidenceBundle(
        as_of_date=as_of or date(2026, 1, 1),
        baseline={},
        symbols=symbols,
    )


def test_status_ok_within_warn_threshold():
    today = date(2026, 4, 19)
    bundle = _bundle(date(2026, 4, 17))   # 2 days behind
    rep = check_freshness(bundle, today=today, warn_after_calendar_days=4, abort_after_calendar_days=7)
    assert rep.status == "ok"
    assert rep.age_days == 2
    assert not rep.should_warn
    assert not rep.should_abort


def test_status_ok_at_exact_warn_threshold():
    today = date(2026, 4, 19)
    bundle = _bundle(date(2026, 4, 15))   # 4 days behind == threshold
    rep = check_freshness(bundle, today=today, warn_after_calendar_days=4, abort_after_calendar_days=7)
    assert rep.status == "ok"
    assert not rep.should_warn


def test_status_warn_just_past_warn_threshold():
    today = date(2026, 4, 19)
    bundle = _bundle(date(2026, 4, 14))   # 5 days behind
    rep = check_freshness(bundle, today=today, warn_after_calendar_days=4, abort_after_calendar_days=7)
    assert rep.status == "warn"
    assert rep.should_warn
    assert not rep.should_abort


def test_status_abort_past_abort_threshold():
    today = date(2026, 4, 19)
    bundle = _bundle(date(2026, 4, 10))   # 9 days behind
    rep = check_freshness(bundle, today=today, warn_after_calendar_days=4, abort_after_calendar_days=7)
    assert rep.status == "abort"
    assert rep.should_warn
    assert rep.should_abort


def test_status_empty_when_no_symbols():
    today = date(2026, 4, 19)
    bundle = _bundle(date(2026, 4, 18), with_symbols=False)
    rep = check_freshness(bundle, today=today, warn_after_calendar_days=4, abort_after_calendar_days=7)
    assert rep.status == "empty"
    assert rep.age_days is None
    assert rep.should_abort
    assert rep.should_warn


def test_message_includes_dates_and_thresholds():
    today = date(2026, 4, 19)
    bundle = _bundle(date(2026, 4, 10))
    rep = check_freshness(bundle, today=today, warn_after_calendar_days=4, abort_after_calendar_days=7)
    assert "2026-04-10" in rep.message
    assert "2026-04-19" in rep.message
    assert "warn>4" in rep.message
    assert "abort>7" in rep.message


def test_freshness_report_is_immutable_dataclass():
    rep = FreshnessReport(
        status="ok", age_days=1, as_of_date=date(2026, 4, 18), today=date(2026, 4, 19),
        warn_threshold=4, abort_threshold=7, message="x",
    )
    # frozen dataclass: assignment must raise.
    try:
        rep.status = "abort"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("FreshnessReport should be frozen")
