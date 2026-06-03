"""Unit tests for the ticker-reuse boundary guard in evidence loading.

A reused ticker splices two issuers under one symbol in the mart; the guard
nulls any return_Nd whose N-trading-day lookback would reach before the symbol's
boundary (the current entity's start). See
~/repos/aft-platform/docs/platform/security-identity-and-ticker-reuse.md.
"""

from __future__ import annotations

from datetime import date

from mef.evidence import _apply_boundary_guard


def _row(bar_date, **returns):
    base = {"symbol": "SYM", "bar_date": bar_date,
            "return_5d": 0.01, "return_20d": 0.02, "return_63d": 0.03,
            "return_126d": 0.04, "return_252d": 0.05}
    base.update(returns)
    return {"SYM": dict(base, **{"symbol": "SYM"})}


def test_nulls_only_windows_that_cross_the_boundary():
    # Current entity ~136 trading days old (~202 cal days): r252 crosses, r126/63 don't.
    rows = _row(date(2026, 6, 1))
    _apply_boundary_guard(rows, {"SYM": date(2025, 11, 11)})
    r = rows["SYM"]
    assert r["return_252d"] is None            # 252 > ~139 avail -> nulled
    assert r["return_126d"] == 0.04            # 126 < ~139 avail -> kept
    assert r["return_63d"] == 0.03
    assert r["return_5d"] == 0.01


def test_old_boundary_leaves_all_returns_intact():
    # Boundary ~2.75y ago: every window (<=252) fits inside the current entity.
    rows = _row(date(2026, 6, 1))
    _apply_boundary_guard(rows, {"SYM": date(2023, 8, 30)})
    r = rows["SYM"]
    assert r["return_252d"] == 0.05
    assert r["return_126d"] == 0.04


def test_no_boundary_is_a_noop():
    rows = _row(date(2026, 6, 1))
    _apply_boundary_guard(rows, {})
    assert rows["SYM"]["return_252d"] == 0.05


def test_brand_new_entity_nulls_all_trailing_returns():
    # Boundary 2 calendar days ago (~1 trading day): every window crosses it.
    rows = _row(date(2026, 6, 1))
    _apply_boundary_guard(rows, {"SYM": date(2026, 5, 30)})
    r = rows["SYM"]
    assert all(r[f"return_{n}d"] is None for n in (5, 20, 63, 126, 252))


def test_missing_bar_date_is_skipped_safely():
    rows = _row(None)
    _apply_boundary_guard(rows, {"SYM": date(2025, 11, 11)})
    # No bar_date -> cannot reason about the window -> leave untouched, no crash.
    assert rows["SYM"]["return_252d"] == 0.05
