"""MEF consumes its canonical Investing Track identity from aft_core."""

from __future__ import annotations

from datetime import datetime, timezone

from aft_core.tracks import Track, primary_track_for_tool

from mef.aft_track import MEF_TRACK, MEF_TRACK_LABEL
from mef.commands.status import _render_header
from mef.email_render import render_daily_email


# ───────────────────────── aft_core wiring ─────────────────────────

def test_mef_is_track_4_via_aft_core_registry():
    assert primary_track_for_tool("mef") == Track.CAPITAL_APPRECIATION


def test_mef_aft_track_constants_match_registry():
    assert MEF_TRACK == Track.CAPITAL_APPRECIATION
    assert MEF_TRACK_LABEL == "Track 4 — Capital Appreciation"


# ───────────────────────── status header ─────────────────────────

def _header_input():
    return {
        "now": datetime(2026, 5, 21, 12, 30, tzinfo=timezone.utc),
        "universe": {"stocks": 305, "etfs": 20},
        "data_through": "2026-05-20",
    }


def test_status_header_contains_track_4_line():
    lines = _render_header(_header_input())
    assert lines[0] == "MEF — Muse Engine Forecaster"
    assert lines[1] == "Investing Track: Track 4 — Capital Appreciation"
    # Existing third line (report metadata) still renders.
    assert "2026-05-20" in lines[2]
    assert "305 stocks / 20 ETFs" in lines[2]


# ───────────────────────── email subject ─────────────────────────

def test_email_subject_carries_track_4_label():
    email = render_daily_email(
        when_kind="premarket",
        intent="today_after_10am",
        run_uid="DR-000010",
        started_at=datetime(2026, 5, 21, 12, 30, tzinfo=timezone.utc),
        stocks_in_universe=305,
        etfs_in_universe=20,
    )
    # Backwards-compatible prefix preserved (existing tests use startswith).
    assert email.subject.startswith("MEF daily report")
    # New Track 4 identity appears in the subject and in the body header.
    assert "Track 4 — Capital Appreciation" in email.subject
    assert "Track 4 — Capital Appreciation" in email.body


# ─────────────── full status render: three sections still present ───────────────

def test_status_render_still_emits_three_sections():
    """M2 must not regress section structure — Actionable / Watch / Pullback."""
    from mef.commands.status import _render

    one_actionable = {
        "symbol": "KO", "company_name": "Coca-Cola",
        "engine": "trend", "posture": "bullish",
        "expression": "buy_shares",
        "entry_method": "limit order $76.63-$78.19",
        "stop_level": 72.72, "target_level": 84.45, "confidence": 0.87,
        "reasoning_summary": "Coherent bullish continuation.",
        "llm_gate_decision": "approve",
        "llm_gate_issue_type": None,
        "llm_gate_key_judgment": "High conviction.",
        "close": 78.19,
    }
    one_watch = dict(one_actionable, symbol="MSFT", llm_gate_decision="review",
                     llm_gate_issue_type="posture_mismatch")
    out = _render({
        "now": datetime(2026, 5, 21, 12, 30, tzinfo=timezone.utc),
        "universe": {"stocks": 305, "etfs": 20},
        "data_through": "2026-05-20",
        "recommendations": [one_actionable, one_watch],
        "pullback_signals": [],
    })
    # Header still has the MEF title and the new Track line.
    assert "MEF — Muse Engine Forecaster" in out
    assert "Investing Track: Track 4 — Capital Appreciation" in out
    # All three sections still render.
    assert "Actionable Stock Ideas" in out
    assert "Watch" in out
    assert "CORE PULLBACK RADAR" in out

