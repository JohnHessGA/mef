"""Telemetry must never raise, even when overwatch is unreachable.

These tests monkey-patch ``connect_overwatch`` to throw so we can prove the
fail-silent contract without depending on the live database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import mef.telemetry as telemetry


def _explode(*args, **kwargs):
    raise ConnectionError("simulated overwatch outage")


@pytest.fixture
def overwatch_down(monkeypatch):
    monkeypatch.setattr(telemetry, "connect_overwatch", _explode)
    yield


def test_start_run_swallows_outage(overwatch_down, capsys):
    telemetry.start_run(
        run_uid="DR-999999",
        when_kind="premarket",
        intent="today_after_10am",
        started_at=datetime.now(timezone.utc),
    )
    err = capsys.readouterr().err
    assert "start_run(DR-999999) failed" in err


def test_complete_run_swallows_outage(overwatch_down, capsys):
    telemetry.complete_run(
        run_uid="DR-999999",
        started_at=datetime.now(timezone.utc),
        counts={"symbols_evaluated": 0},
        email_sent=False,
    )
    err = capsys.readouterr().err
    assert "complete_run(DR-999999) failed" in err


def test_fail_run_swallows_outage(overwatch_down, capsys):
    telemetry.fail_run(
        run_uid="DR-999999",
        started_at=datetime.now(timezone.utc),
        error_text="boom",
    )
    err = capsys.readouterr().err
    assert "fail_run(DR-999999) failed" in err


def test_event_swallows_outage(overwatch_down, capsys):
    telemetry.event(severity="warning", code="something", message="msg", run_uid="DR-999999")
    err = capsys.readouterr().err
    assert "event(something) failed" in err


def test_event_normalizes_unknown_severity(overwatch_down, capsys):
    # Unknown severity gets remapped to 'info' before the connection attempt.
    # We can't directly observe the remap (overwatch is down), but we can prove
    # the call doesn't raise and produces the same fail-silent log line.
    telemetry.event(severity="bogus", code="xyz", run_uid="DR-999999")
    err = capsys.readouterr().err
    assert "event(xyz) failed" in err
