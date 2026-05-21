"""Unit tests for `mef status` render/format helpers (pure functions)."""

from __future__ import annotations

from types import SimpleNamespace

from mef.commands.status import (
    _action_label,
    _actionable_status,
    _classify_actionable,
    _entry_zone_hi,
    _fmt_conf,
    _fmt_dollars,
    _fmt_entry_zone,
    _format_idea_block,
    _render_actionable,
    _render_etf_posture,
    _render_watch,
    _short_reason,
    _watch_status,
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


def test_entry_zone_hi_returns_top_of_band():
    assert _entry_zone_hi("limit order $76.63-$78.19") == 78.19
    assert _entry_zone_hi(None) is None


def test_short_reason_truncates_at_first_punct():
    assert (
        _short_reason("Coherent bullish continuation. Posture aligns with…")
        == "Coherent bullish continuation"
    )


def test_short_reason_handles_empty():
    assert _short_reason(None) == ""
    assert _short_reason("") == ""


def test_action_label_buy_shares():
    assert _action_label("buy_shares") == "Buy"
    assert _action_label("sell_shares") == "Sell"
    assert _action_label(None) == "?"
    assert _action_label("custom_action") == "Custom Action"


# ── actionable / watch classification ──

def test_classify_actionable_approves_only():
    assert _classify_actionable({"llm_gate_decision": "approve"}) == "actionable"
    assert _classify_actionable({"llm_gate_decision": "review"}) == "watch"
    assert _classify_actionable({"llm_gate_decision": "unavailable"}) == "watch"
    assert _classify_actionable({"llm_gate_decision": None}) == "watch"


def test_actionable_status_wait_for_pullback_when_close_above_entry():
    rec = {"close": 219.87, "entry_method": "limit order $212.07-$216.35"}
    assert _actionable_status(rec) == "Wait for pullback"


def test_actionable_status_ready_when_close_inside_zone():
    rec = {"close": 78.19, "entry_method": "limit order $76.63-$78.19"}
    assert _actionable_status(rec) == "Ready"


def test_actionable_status_ready_when_data_missing():
    rec = {"close": None, "entry_method": "limit order $50-$60"}
    assert _actionable_status(rec) == "Ready"


def test_watch_status_uses_structured_issue_type_when_set():
    rec = {"llm_gate_decision": "review", "llm_gate_issue_type": "posture_mismatch"}
    assert _watch_status(rec) == "Posture mismatch"


def test_watch_status_falls_back_to_text_patterns():
    rec = {
        "llm_gate_decision": "review",
        "llm_gate_issue_type": None,
        "reasoning_summary": "Posture/evidence mismatch: tagged value but reads as momentum.",
    }
    assert _watch_status(rec) == "Posture mismatch"


def test_watch_status_detects_no_stabilization():
    rec = {
        "llm_gate_decision": "review",
        "reasoning_summary": "Oversold reading but no clear sign of stabilization yet.",
    }
    assert _watch_status(rec) == "No stabilization"


def test_watch_status_detects_low_conviction():
    rec = {
        "llm_gate_decision": "review",
        "reasoning_summary": "Mild signal but conviction is low and trend not repaired.",
    }
    assert _watch_status(rec) == "Low conviction"


def test_watch_status_unavailable_gate_marks_unreviewed():
    rec = {"llm_gate_decision": "unavailable"}
    assert _watch_status(rec) == "Unreviewed"


def test_watch_status_default_held_for_review():
    rec = {"llm_gate_decision": "review", "reasoning_summary": "Some unrelated text."}
    assert _watch_status(rec) == "Held for review"


# ── per-idea block layout ──

def _sample_actionable_rec():
    return {
        "symbol": "KO",
        "company_name": "Coca-Cola Co",
        "engine": "trend",
        "posture": "bullish",
        "expression": "buy_shares",
        "entry_method": "limit order $76.63-$78.19",
        "stop_level": 72.72,
        "target_level": 84.45,
        "confidence": 0.8745,
        "reasoning_summary": "Coherent bullish continuation in defensive name.",
        "llm_gate_decision": "approve",
        "llm_gate_issue_type": None,
        "llm_gate_key_judgment": "High conviction with internally consistent trend.",
        "close": 78.19,
    }


def test_format_idea_block_three_lines_for_actionable():
    rec = _sample_actionable_rec()
    block = _format_idea_block(rec, "Buy", "Ready")
    assert len(block) == 3
    head, plan, detail = block
    assert "KO" in head
    assert "Buy / Ready" in head
    assert "Coherent bullish continuation in defensive name" in head
    assert "Entry $77-$78" in plan
    assert "Stop $73" in plan
    assert "Target $84" in plan
    assert "0.87 conv" in plan
    assert "High conviction with internally consistent trend" in detail


def test_format_idea_block_two_lines_when_no_detail_text():
    rec = _sample_actionable_rec()
    rec["llm_gate_key_judgment"] = None
    rec["reasoning_summary"] = ""
    block = _format_idea_block(rec, "Buy", "Ready")
    assert len(block) == 2  # head + plan only


def test_format_idea_block_watch_action_label_replaces_buy():
    """Watch entries never use the buy verb in the header."""
    rec = _sample_actionable_rec()
    rec["llm_gate_decision"] = "review"
    block = _format_idea_block(rec, "Watch", "Posture mismatch")
    head = block[0]
    assert "Watch / Posture mismatch" in head
    assert "Buy" not in head


def test_render_watch_section_never_contains_buy_in_headers():
    """End-to-end: rendering a Watch list must not produce 'Buy' in any header line."""
    watch_recs = [
        {
            "symbol": "COP",
            "expression": "buy_shares",  # underlying expression is still a buy plan
            "entry_method": "limit order $123.66-$126.16",
            "stop_level": 112.42,
            "target_level": 137.40,
            "confidence": 0.78,
            "reasoning_summary": "Posture/evidence mismatch: tagged value but reads as momentum.",
            "llm_gate_decision": "review",
            "llm_gate_issue_type": "posture_mismatch",
            "llm_gate_key_judgment": "Worth a human look but conflicts with the named posture.",
            "close": 124.91,
        },
    ]
    out = "\n".join(_render_watch(watch_recs))
    # Header line specifically — entry plan still mentions dollar amounts, that's fine.
    head_line = next(line for line in out.splitlines() if "COP —" in line)
    assert "Watch" in head_line
    assert "Buy" not in head_line


# ── section renderers ──

def test_actionable_empty_state():
    out = "\n".join(_render_actionable([]))
    assert "Actionable Stock Ideas (0)" in out
    assert "No actionable ideas right now." in out


def test_watch_empty_state():
    out = "\n".join(_render_watch([]))
    assert "Watch / Not Actionable (0)" in out
    assert "Nothing on watch." in out


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
    assert out.index("extended_wait") < out.index("healthy_pullback")
    assert out.index("healthy_pullback") < out.index("breakdown_risk")
    assert "extended_wait (1)" in out
    assert "near_entry (0)" in out


# ─────────────────────────────────────────────────────────────────────────
# Default-report contract (2026-05-21): ETF-posture section removed.
# The full _render() must include Actionable / Watch / Core Pullback
# but NOT the standalone ETF posture readout (it now overlaps with the
# Core Pullback Watchlist and confused the reader).
# ─────────────────────────────────────────────────────────────────────────

def _build_report_dict():
    """Minimal fixture for the full-render contract tests."""
    from datetime import datetime, timezone
    return {
        "now": datetime(2026, 5, 21, 9, 30, tzinfo=timezone.utc),
        "universe": {"stocks": 305, "etfs": 20},
        "data_through": None,
        "recommendations": [],
        "pullback_signals": [],
        # Note: no "etf_posture" key — _gather() no longer populates it.
    }


def test_full_render_includes_core_pullback_watchlist_header():
    from mef.commands.status import _render
    body = _render(_build_report_dict())
    assert "CORE PULLBACK WATCHLIST" in body


def test_full_render_does_not_include_etf_posture_section():
    """The old `ETF posture (N)` header must not appear by default.
    Removing it eliminates the conflicting ETF readout."""
    from mef.commands.status import _render
    body = _render(_build_report_dict())
    assert "ETF posture" not in body


def test_full_render_keeps_actionable_and_watch_headers_when_recs_exist():
    from mef.commands.status import _render
    r = _build_report_dict()
    r["recommendations"] = [{
        "symbol": "AAPL", "asset_kind": "stock", "posture": "bullish",
        "expression": "buy_shares", "entry_method": "limit order $100-$102",
        "stop_level": 95.0, "target_level": 110.0, "confidence": 0.80,
        "state": "proposed", "reasoning_summary": "trend intact",
        "engine": "trend",
        "llm_gate_decision": "approve", "llm_gate_issue_type": None,
        "llm_gate_key_judgment": None, "close": 101.0, "company_name": "Apple",
    }]
    body = _render(r)
    assert "Actionable Stock Ideas" in body
    assert "Watch / Not Actionable" in body
    assert "ETF posture" not in body
