"""Unit tests for `mef status` render/format helpers (pure functions)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from datetime import date

from mef.commands.status import (
    _fmt_conf,
    _fmt_dollars,
    _fmt_duration,
    _fmt_entry_zone,
    _format_rec_block,
    _meaningful_hazards,
    _render_data_status,
    _render_etf_posture,
    _render_recommendations,
    _short_engine,
    _short_name,
    _short_reason,
)


# ── primitive formatters ──

def test_fmt_dollars_rounds_to_whole():
    assert _fmt_dollars(84.45) == "$84"
    assert _fmt_dollars(84.6) == "$85"


def test_fmt_dollars_handles_none():
    assert _fmt_dollars(None) == "?"


def test_fmt_conf_two_decimal():
    assert _fmt_conf(0.8745) == "0.87"
    assert _fmt_conf(None) == "?"


def test_fmt_entry_zone_parses_limit_order_string():
    assert _fmt_entry_zone("limit order $76.63-$78.19") == "$77-$78"
    assert _fmt_entry_zone("limit order $295.50-$301.53") == "$296-$302"


def test_fmt_entry_zone_handles_none():
    assert _fmt_entry_zone(None) == "?"


def test_short_engine_known_aliases():
    assert _short_engine("mean_reversion") == "mean_rev"
    assert _short_engine("trend") == "trend"
    assert _short_engine(None) == "?"


def test_short_reason_truncates_at_first_punct():
    assert (
        _short_reason("Coherent bullish continuation. Posture aligns with…")
        == "Coherent bullish continuation"
    )


def test_short_reason_handles_empty():
    assert _short_reason(None) == ""
    assert _short_reason("") == ""


def test_fmt_duration_minutes_seconds():
    start = datetime(2026, 5, 6, 17, 30, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 6, 17, 32, 51, tzinfo=timezone.utc)
    assert _fmt_duration(start, end) == "2m51s"


# ── recommendation block layout (head line + reason line) ──

def test_format_rec_block_two_lines_with_clean_data():
    rec = {
        "symbol": "KO",
        "company_name": "Coca-Cola Co",
        "engine": "trend",
        "posture": "bullish",
        "entry_method": "limit order $76.63-$78.19",
        "stop_level": 72.72,
        "target_level": 84.45,
        "confidence": 0.8745,
        "reasoning_summary": "Coherent bullish continuation in defensive name; trend intact.",
        "hazard_event_type": "other",
        "hazard_flags": ["macro:other"],
    }
    block = _format_rec_block(rec)
    assert len(block) == 2
    head, detail = block
    assert "KO" in head
    assert "Coca-Cola Co" in head
    assert "trend" in head
    assert "bullish" in head
    assert "$77-$78" in head
    assert "$73" in head
    assert "$84" in head
    assert "0.87" in head
    # Generic 'other' / 'macro:other' suppressed; no flag suffix.
    assert "[" not in detail
    assert "Coherent bullish continuation in defensive name" in detail


def test_format_rec_block_surfaces_meaningful_hazards():
    rec = {
        "symbol": "TRV",
        "company_name": "Travelers Cos",
        "engine": "trend",
        "posture": "bullish",
        "entry_method": "limit order $295.50-$301.53",
        "stop_level": 280.42,
        "target_level": 325.65,
        "confidence": 0.8455,
        "reasoning_summary": "Solid bullish continuation.",
        "hazard_event_type": "fomc",
        "hazard_flags": ["macro:fomc", "earn_prox:11-21d", "macro:other"],
    }
    detail = _format_rec_block(rec)[1]
    assert "[event:fomc, macro:fomc, earn_prox:11-21d]" in detail
    # Generic flag still suppressed.
    assert "macro:other" not in detail


def test_format_rec_block_no_reason_no_flags_emits_only_head():
    rec = {
        "symbol": "X",
        "confidence": 0.5,
        "engine": "trend",
        "posture": "bullish",
        "entry_method": None,
        "reasoning_summary": None,
        "hazard_event_type": "other",
        "hazard_flags": ["macro:other"],
    }
    block = _format_rec_block(rec)
    assert len(block) == 1


def test_short_name_truncation():
    assert _short_name("Verizon Communications Inc", 22) == "Verizon Communication…"
    assert _short_name("KO", 22) == "KO"
    assert _short_name(None, 22) == ""


def test_meaningful_hazards_suppresses_generic():
    assert _meaningful_hazards("other", ["macro:other"]) == []
    assert _meaningful_hazards("pce", ["macro:pce", "macro:other"]) == ["event:pce", "macro:pce"]


# ── data status freshness rendering (mirrors pipeline thresholds) ──

def _freshness(latest_bar, days, tier, warn=4, abort=7):
    return {
        "mart_freshness": {
            "latest_bar": latest_bar,
            "days_behind": days,
            "tier": tier,
            "warn_threshold": warn,
            "abort_threshold": abort,
        },
        "recent_alerts": {"error": [], "warning": []},
    }


def test_data_status_fresh():
    out = "\n".join(_render_data_status(_freshness(date(2026, 5, 5), 1, "ok")))
    assert "fresh" in out
    assert "STALE" not in out
    assert "ABORT" not in out


def test_data_status_stale():
    out = "\n".join(_render_data_status(_freshness(date(2026, 4, 30), 6, "stale")))
    assert "STALE (6d behind, warn>4)" in out


def test_data_status_abort():
    out = "\n".join(_render_data_status(_freshness(date(2026, 4, 25), 11, "abort")))
    assert "ABORT (11d behind, abort>7)" in out


def test_data_status_mart_unavailable():
    out = "\n".join(_render_data_status({
        "mart_freshness": {"latest_bar": None, "days_behind": None, "tier": None,
                           "warn_threshold": 4, "abort_threshold": 7},
        "recent_alerts": {"error": [], "warning": []},
    }))
    assert "unavailable" in out


# ── section renderers ──

def test_recommendations_empty_state():
    out = _render_recommendations({"recommendations": []})
    assert any("no recommendations" in line for line in out)


def test_etf_posture_empty_state():
    out = _render_etf_posture({"etf_posture": []})
    assert any("unavailable" in line for line in out)


def test_etf_posture_groups_by_label():
    labels = [
        SimpleNamespace(symbol="XLE", label="healthy_pullback", reason="down 5% from high"),
        SimpleNamespace(symbol="QQQ", label="extended_wait", reason="near recent high"),
        SimpleNamespace(symbol="XLF", label="breakdown_risk", reason="below SMA200"),
    ]
    out = "\n".join(_render_etf_posture({"etf_posture": labels}))
    # Order matches LABEL_ORDER constant
    assert out.index("extended_wait") < out.index("healthy_pullback")
    assert out.index("healthy_pullback") < out.index("breakdown_risk")
    # Counts surface correctly
    assert "extended_wait (1)" in out
    assert "healthy_pullback (1)" in out
    # Buckets with no entries are still listed with (0) and "(none)"
    assert "near_entry (0)" in out
    assert "reasonable_entry (0)" in out
    assert "neutral (0)" in out
