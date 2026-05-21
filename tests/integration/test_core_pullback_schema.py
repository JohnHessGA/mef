"""Integration tests for the Job 2 Core Pullback Watchlist DB schema.

Requires:
- a live ``mefdb`` reachable via ``config/postgres.secrets.yaml``
- migration ``sql/mefdb/013_core_pullback_watchlist.sql`` already applied
  (run ``mef init-db`` once)

Skips cleanly when the migration has not been applied, so CI/dev machines
without a freshly migrated DB don't false-fail.
"""

from __future__ import annotations

import pytest

from mef.db.connection import connect_mefdb


def _table_exists(conn, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            (f"{schema}.{table}",),
        )
        return bool(cur.fetchone()[0])


@pytest.fixture(scope="module")
def mefdb():
    conn = connect_mefdb()
    if not _table_exists(conn, "mef", "core_pullback_tier"):
        conn.close()
        pytest.skip(
            "mef.core_pullback_tier does not exist — run `mef init-db` first."
        )
    yield conn
    conn.close()


# ─────────────────────────────────────────────────────────────────────────
# Tier seed
# ─────────────────────────────────────────────────────────────────────────


def test_tier_seed_present(mefdb) -> None:
    """All five tiers should be seeded with thresholds matching the spec."""
    expected = {
        "core_market_etf":            ("etf",   0.0300, 0.0500, 0.0800),
        "core_growth_etf":            ("etf",   0.0400, 0.0700, 0.1200),
        "elite_compounder":           ("stock", 0.0500, 0.0800, 0.1500),
        "quality_growth":             ("stock", 0.0700, 0.1000, 0.1800),
        "volatile_special_situation": ("stock", 0.1000, 0.1500, 0.2500),
    }
    with mefdb.cursor() as cur:
        cur.execute("""
            SELECT tier_code, asset_group,
                   visibility_drawdown, buy_zone_drawdown, deep_drawdown
              FROM mef.core_pullback_tier
        """)
        rows = {r[0]: (r[1], float(r[2]), float(r[3]), float(r[4])) for r in cur.fetchall()}
    assert set(rows) == set(expected)
    for tier, (ag, vis, bz, deep) in expected.items():
        assert rows[tier][0] == ag, f"{tier} asset_group"
        assert abs(rows[tier][1] - vis) < 1e-6, f"{tier} visibility"
        assert abs(rows[tier][2] - bz) < 1e-6, f"{tier} buy_zone"
        assert abs(rows[tier][3] - deep) < 1e-6, f"{tier} deep"


# ─────────────────────────────────────────────────────────────────────────
# Watchlist seed
# ─────────────────────────────────────────────────────────────────────────


def test_watchlist_enabled_counts(mefdb) -> None:
    """The seed should produce exactly 10 enabled ETFs and 50 enabled stocks."""
    with mefdb.cursor() as cur:
        cur.execute("""
            SELECT asset_kind, count(*)
              FROM mef.core_pullback_watchlist
             WHERE enabled
             GROUP BY asset_kind
        """)
        counts = {kind: n for kind, n in cur.fetchall()}
    assert counts.get("etf") == 10, f"expected 10 enabled ETFs, got {counts.get('etf')}"
    assert counts.get("stock") == 50, f"expected 50 enabled stocks, got {counts.get('stock')}"


def test_all_enabled_have_valid_tier(mefdb) -> None:
    """Every enabled watchlist row must reference an existing, enabled tier."""
    with mefdb.cursor() as cur:
        cur.execute("""
            SELECT w.symbol, w.tier_code
              FROM mef.core_pullback_watchlist w
              LEFT JOIN mef.core_pullback_tier t ON t.tier_code = w.tier_code
             WHERE w.enabled
               AND (t.tier_code IS NULL OR NOT t.enabled)
        """)
        bad = cur.fetchall()
    assert bad == [], f"watchlist rows without a valid enabled tier: {bad}"


@pytest.mark.parametrize("symbol, expected_tier", [
    ("SPY",  "core_market_etf"),
    ("QQQ",  "core_growth_etf"),
    ("NVDA", "elite_compounder"),
    ("MSFT", "elite_compounder"),
    ("JPM",  "quality_growth"),
    ("TSLA", "volatile_special_situation"),
    ("INTC", "volatile_special_situation"),
    ("NVO",  "volatile_special_situation"),
])
def test_tier_assignment_for_representative_symbols(mefdb, symbol, expected_tier) -> None:
    with mefdb.cursor() as cur:
        cur.execute(
            "SELECT tier_code FROM mef.core_pullback_watchlist WHERE symbol = %s",
            (symbol,),
        )
        row = cur.fetchone()
    assert row is not None, f"{symbol} missing from watchlist"
    assert row[0] == expected_tier, f"{symbol} tier expected {expected_tier}, got {row[0]}"


# ─────────────────────────────────────────────────────────────────────────
# Snapshot table — schema only (no rows produced yet)
# ─────────────────────────────────────────────────────────────────────────


def test_snapshot_table_present_and_empty(mefdb) -> None:
    """The snapshot table exists, has the status CHECK, and starts empty."""
    assert _table_exists(mefdb, "mef", "core_pullback_snapshot")
    with mefdb.cursor() as cur:
        cur.execute("SELECT count(*) FROM mef.core_pullback_snapshot")
        assert cur.fetchone()[0] == 0
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
              FROM pg_constraint
             WHERE conname = 'core_pullback_snapshot_status_chk'
        """)
        row = cur.fetchone()
    assert row is not None
    chkdef = row[0]
    for status in (
        "NO_PULLBACK", "PULLBACK_FORMING", "BUY_ZONE_ACTIVE",
        "DEEP_PULLBACK_OPPORTUNITY", "FALLING_KNIFE_WAIT", "THESIS_BROKEN_REVIEW",
    ):
        assert status in chkdef, f"snapshot status {status} missing from CHECK"


# ─────────────────────────────────────────────────────────────────────────
# Job 1 universe still DB-backed (regression guard)
# ─────────────────────────────────────────────────────────────────────────


def test_job1_universe_counts_still_match(mefdb) -> None:
    """Job 1 stays at 305 stocks + 20 ETFs in MEFDB. This step does not change them."""
    with mefdb.cursor() as cur:
        cur.execute("SELECT count(*) FROM mef.universe_stock")
        stocks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mef.universe_etf")
        etfs = cur.fetchone()[0]
    assert stocks == 305
    assert etfs == 20
