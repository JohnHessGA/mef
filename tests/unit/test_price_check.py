"""Unit tests for the post-emission price-freshness check.

yfinance is monkeypatched at the module boundary so these tests run
without network I/O. The classifier (`_classify_delta`) is pure and
covered directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from mef import price_check as pc


# ─── classification ───

def test_classify_below_info_threshold_is_none():
    delta_abs, delta_pct, tier, note = pc._classify_delta(
        100.0, 100.5, info_threshold_pct=0.01, warn_threshold_pct=0.03,
    )
    assert tier == pc.TIER_NONE
    assert note is None


def test_classify_info_tier_positive_move():
    _, _, tier, note = pc._classify_delta(
        100.0, 102.0, info_threshold_pct=0.01, warn_threshold_pct=0.03,
    )
    assert tier == pc.TIER_INFO
    assert note is not None and "+2.0%" in note
    assert "warning" not in (note or "").lower()


def test_classify_info_tier_negative_move():
    _, _, tier, note = pc._classify_delta(
        100.0, 98.0, info_threshold_pct=0.01, warn_threshold_pct=0.03,
    )
    assert tier == pc.TIER_INFO
    # Unicode minus sign used for visual parity with the +/− in the note.
    assert "−2.0%" in note


def test_classify_warn_tier_on_large_move():
    _, _, tier, note = pc._classify_delta(
        100.0, 104.5, info_threshold_pct=0.01, warn_threshold_pct=0.03,
    )
    assert tier == pc.TIER_WARN
    assert note is not None and "⚠" in note
    assert "+4.5%" in note
    assert "entry zone may need refresh" in note


def test_classify_exact_threshold_is_next_tier_up():
    # At the boundary, magnitudes >= threshold flip to the next tier.
    _, _, tier, _ = pc._classify_delta(
        100.0, 101.0, info_threshold_pct=0.01, warn_threshold_pct=0.03,
    )
    assert tier == pc.TIER_INFO
    _, _, tier, _ = pc._classify_delta(
        100.0, 103.0, info_threshold_pct=0.01, warn_threshold_pct=0.03,
    )
    assert tier == pc.TIER_WARN


# ─── session classification ───

def test_classify_session_regular_hours():
    # 14:00 UTC in July ≈ 10:00 ET (EDT = −4).
    t = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    assert pc._classify_session(t) == "regular"


def test_classify_session_pre_market():
    # 12:00 UTC in July ≈ 08:00 ET (EDT).
    t = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert pc._classify_session(t) == "pre"


def test_classify_session_post_market():
    # 22:00 UTC in July ≈ 18:00 ET (EDT).
    t = datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)
    assert pc._classify_session(t) == "post"


def test_classify_session_closed_overnight():
    # 03:00 UTC ≈ 23:00 previous-day ET. Off the tape entirely.
    t = datetime(2026, 7, 15, 3, 0, tzinfo=timezone.utc)
    assert pc._classify_session(t) == "closed"


# ─── top-level check_prices behavior (fetch monkeypatched) ───

def _ideas(*pairs):
    """Build emitted_rows-shaped dicts from (symbol, last_close) pairs."""
    return [{"symbol": s, "current_price": c} for s, c in pairs]


def test_check_prices_disabled_returns_empty_summary():
    out = pc.check_prices(_ideas(("AAPL", 200.0)), enabled=False)
    assert out.results == {}
    assert out.fetch_error is None


def test_check_prices_empty_ideas_short_circuits():
    out = pc.check_prices([])
    assert out.results == {}


def test_check_prices_successful_fetch_classifies_each_symbol(monkeypatch):
    # Stub the network boundary.
    def stub_fetch(symbols):
        ts = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        return {
            "AAPL": (202.0, ts),   # +1% from 200 → info tier
            "MSFT": (290.0, ts),   # −3.33% from 300 → warn tier
        }
    monkeypatch.setattr(pc, "_fetch_bars", stub_fetch)

    out = pc.check_prices(_ideas(("AAPL", 200.0), ("MSFT", 300.0)))
    assert out.fetch_error is None

    aapl = out.results["AAPL"]
    msft = out.results["MSFT"]
    assert aapl.staleness_tier == pc.TIER_INFO
    assert aapl.source_session == "regular"
    assert msft.staleness_tier == pc.TIER_WARN
    assert "entry zone may need refresh" in (msft.note or "")


def test_check_prices_fail_silent_on_fetch_exception(monkeypatch):
    def stub_fetch(symbols):
        raise RuntimeError("yfinance blew up")
    monkeypatch.setattr(pc, "_fetch_bars", stub_fetch)

    out = pc.check_prices(_ideas(("AAPL", 200.0)))
    assert out.fetch_error is not None
    # Per-symbol entry still exists with tier=unavailable — callers can
    # render something ("not checked") without special-casing the error.
    assert out.results["AAPL"].staleness_tier == pc.TIER_UNAVAILABLE
    assert out.results["AAPL"].note is None


def test_check_prices_missing_symbol_in_response_is_unavailable(monkeypatch):
    def stub_fetch(symbols):
        # Pretend yfinance returned nothing for MSFT.
        return {"AAPL": (200.5, datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc))}
    monkeypatch.setattr(pc, "_fetch_bars", stub_fetch)

    out = pc.check_prices(_ideas(("AAPL", 200.0), ("MSFT", 300.0)))
    assert out.results["MSFT"].staleness_tier == pc.TIER_UNAVAILABLE
    assert out.results["AAPL"].staleness_tier == pc.TIER_NONE


def test_check_prices_dedups_same_symbol_across_engines(monkeypatch):
    # Same symbol emitted by both trend and value engines — only one
    # quote fetch should be attempted.
    calls = []
    def stub_fetch(symbols):
        calls.append(tuple(sorted(symbols)))
        ts = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        return {"JCI": (140.0, ts)}
    monkeypatch.setattr(pc, "_fetch_bars", stub_fetch)

    pc.check_prices(_ideas(("JCI", 140.0), ("JCI", 140.0)))
    assert calls == [("JCI",)]


# ─── annotate_ideas merges back into emitted_rows ───

def test_annotate_ideas_sets_expected_keys(monkeypatch):
    def stub_fetch(symbols):
        ts = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        return {"AAPL": (208.0, ts)}   # +4% from 200 → warn tier
    monkeypatch.setattr(pc, "_fetch_bars", stub_fetch)

    ideas: list[dict[str, Any]] = _ideas(("AAPL", 200.0))
    summary = pc.check_prices(ideas)
    pc.annotate_ideas(ideas, summary)

    assert ideas[0]["price_check_tier"] == pc.TIER_WARN
    assert ideas[0]["price_check_current"] == 208.0
    assert ideas[0]["price_check_session"] == "regular"
    assert ideas[0]["price_check_note"] is not None


def test_annotate_ideas_flags_unavailable_when_symbol_missing():
    ideas: list[dict[str, Any]] = _ideas(("AAPL", 200.0))
    empty_summary = pc.PriceCheckSummary()
    pc.annotate_ideas(ideas, empty_summary)
    assert ideas[0]["price_check_tier"] == pc.TIER_UNAVAILABLE
    assert ideas[0]["price_check_note"] is None
