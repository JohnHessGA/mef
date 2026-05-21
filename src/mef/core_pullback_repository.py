"""Read accessors for the Job 2 Core Pullback Watchlist tables.

Joins ``mef.core_pullback_watchlist`` with ``mef.core_pullback_tier`` and
returns a sorted list of plain dicts — no engine logic here, no SHDB
reads. The tables are seeded by ``sql/mefdb/013_core_pullback_watchlist.sql``.

Rule (per CLAUDE.md boundary 0): operational symbol lists live in MEFDB.
Nothing in this module reads markdown, YAML, or anything outside MEFDB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg2.extras import RealDictCursor

from mef.db.connection import connect_mefdb


@dataclass(frozen=True)
class WatchlistRow:
    """One enabled Job 2 symbol with the tier thresholds resolved."""
    symbol: str
    asset_kind: str             # 'stock' | 'etf'
    tier_code: str
    tier_display_name: str
    asset_group: str            # 'stock' | 'etf'
    visibility_drawdown: float
    buy_zone_drawdown: float
    deep_drawdown: float
    min_risk_reward: float | None
    requires_stabilization: bool
    tier_display_order: int
    row_display_order: int
    rationale: str | None


# Single join. The WHERE clause silently skips watchlist rows whose tier
# is disabled — operators can pause a whole tier without having to flip
# every symbol individually.
_WATCHLIST_SQL = """
SELECT  w.symbol,
        w.asset_kind,
        w.tier_code,
        t.display_name           AS tier_display_name,
        t.asset_group,
        t.visibility_drawdown,
        t.buy_zone_drawdown,
        t.deep_drawdown,
        t.min_risk_reward,
        t.requires_stabilization,
        t.display_order           AS tier_display_order,
        w.display_order           AS row_display_order,
        w.rationale
  FROM mef.core_pullback_watchlist w
  JOIN mef.core_pullback_tier t ON t.tier_code = w.tier_code
 WHERE w.enabled
   AND t.enabled
 ORDER BY t.display_order ASC, w.display_order ASC, w.symbol ASC
"""


def load_enabled_watchlist() -> list[WatchlistRow]:
    """Return every enabled watchlist row joined with its tier metadata.

    Order: tier display_order, then per-row display_order, then symbol.
    """
    conn = connect_mefdb()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_WATCHLIST_SQL)
            raw = cur.fetchall()
    finally:
        conn.close()

    return [_row(r) for r in raw]


def _row(r: dict[str, Any]) -> WatchlistRow:
    return WatchlistRow(
        symbol=r["symbol"],
        asset_kind=r["asset_kind"],
        tier_code=r["tier_code"],
        tier_display_name=r["tier_display_name"],
        asset_group=r["asset_group"],
        visibility_drawdown=float(r["visibility_drawdown"]),
        buy_zone_drawdown=float(r["buy_zone_drawdown"]),
        deep_drawdown=float(r["deep_drawdown"]),
        min_risk_reward=(
            float(r["min_risk_reward"]) if r["min_risk_reward"] is not None else None
        ),
        requires_stabilization=bool(r["requires_stabilization"]),
        tier_display_order=int(r["tier_display_order"]),
        row_display_order=int(r["row_display_order"]),
        rationale=r["rationale"],
    )
