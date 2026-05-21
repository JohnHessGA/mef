"""Integration test for the Core Pullback Watchlist repository.

Reads live MEFDB. Skips cleanly if migration 013 hasn't been applied.
"""

from __future__ import annotations

import pytest

from mef.core_pullback_repository import WatchlistRow, load_enabled_watchlist
from mef.db.connection import connect_mefdb


def _has_pullback_tables() -> bool:
    try:
        conn = connect_mefdb()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('mef.core_pullback_watchlist') IS NOT NULL")
            return bool(cur.fetchone()[0])
    finally:
        conn.close()


@pytest.fixture(scope="module")
def watchlist() -> list[WatchlistRow]:
    if not _has_pullback_tables():
        pytest.skip("mef.core_pullback_watchlist not present — run `mef init-db` first.")
    return load_enabled_watchlist()


def test_loads_60_enabled_rows(watchlist) -> None:
    assert len(watchlist) == 60, (
        f"expected 60 enabled rows from the seed; got {len(watchlist)}"
    )


def test_loads_10_etfs_and_50_stocks(watchlist) -> None:
    etfs   = [r for r in watchlist if r.asset_kind == "etf"]
    stocks = [r for r in watchlist if r.asset_kind == "stock"]
    assert len(etfs) == 10
    assert len(stocks) == 50


def test_every_row_carries_resolved_tier_thresholds(watchlist) -> None:
    """The join must populate thresholds on every row, never leave them None."""
    for r in watchlist:
        assert r.visibility_drawdown > 0, f"{r.symbol} missing visibility_drawdown"
        assert r.buy_zone_drawdown > 0,   f"{r.symbol} missing buy_zone_drawdown"
        assert r.deep_drawdown > 0,       f"{r.symbol} missing deep_drawdown"
        # Strict monotone — visibility < buy_zone < deep.
        assert r.visibility_drawdown < r.buy_zone_drawdown < r.deep_drawdown, (
            f"{r.symbol} ({r.tier_code}) thresholds out of order"
        )
        assert r.tier_display_name      # non-empty


def test_sorted_by_tier_display_order_then_row_display_order(watchlist) -> None:
    """Ordering matters for the renderer — ETFs first, then Tier 2 → 3 → 4."""
    previous = (-1, -1)
    for r in watchlist:
        current = (r.tier_display_order, r.row_display_order)
        assert current >= previous, (
            f"order violation at {r.symbol}: {current} after {previous}"
        )
        previous = current


def test_disabled_rows_are_excluded() -> None:
    """If we disable a row in a tx, the loader stops returning it.

    Uses a SAVEPOINT-style transaction that we roll back so the seed
    stays clean.
    """
    if not _has_pullback_tables():
        pytest.skip("schema absent")
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute(
                "UPDATE mef.core_pullback_watchlist SET enabled=false WHERE symbol='SPY'"
            )
            conn.commit()
            try:
                rows = load_enabled_watchlist()
                symbols = {r.symbol for r in rows}
                assert "SPY" not in symbols, "disabled row leaked into loader"
                assert len(rows) == 59
            finally:
                with conn.cursor() as cur2:
                    cur2.execute(
                        "UPDATE mef.core_pullback_watchlist SET enabled=true WHERE symbol='SPY'"
                    )
                conn.commit()
    finally:
        conn.close()
