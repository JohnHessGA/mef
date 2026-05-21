"""Read accessors for the Job 1 universe tables.

Operational universe data (305 stocks + 20 ETFs) lives in MEFDB and is
seeded by SQL migrations under ``sql/mefdb/``. There is no markdown
loader — runtime code reads ``mef.universe_stock`` / ``mef.universe_etf``
directly via these helpers.
"""

from __future__ import annotations

from typing import Any

from mef.db.connection import connect_mefdb


def universe_counts() -> dict[str, int]:
    """Return current row counts for the two Job 1 universe tables."""
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM mef.universe_stock")
            stocks = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM mef.universe_etf")
            etfs = cur.fetchone()[0]
        return {"stocks": stocks, "etfs": etfs}
    finally:
        conn.close()


def fetch_universe_stocks() -> list[dict[str, Any]]:
    """Return all rows from ``mef.universe_stock`` sorted by symbol."""
    from psycopg2.extras import RealDictCursor
    conn = connect_mefdb()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT symbol, company_name, sector, industry "
                "FROM mef.universe_stock ORDER BY symbol"
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def fetch_universe_etfs() -> list[dict[str, Any]]:
    """Return all rows from ``mef.universe_etf`` sorted by role then symbol."""
    from psycopg2.extras import RealDictCursor
    conn = connect_mefdb()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT symbol, role, description "
                "FROM mef.universe_etf ORDER BY role, symbol"
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
