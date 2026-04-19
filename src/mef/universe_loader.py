"""Load the parsed stock/ETF universe into MEFDB.

Idempotent: re-running ``load_universe_stocks`` / ``load_universe_etfs`` over
an already-populated table leaves the table in the same state. Uses
``INSERT ... ON CONFLICT (symbol) DO UPDATE`` so subsequent loads refresh
the metadata columns and the ``last_refreshed_at`` timestamp.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mef.db.connection import connect_mefdb
from mef.universe_parser import parse_etfs, parse_stocks


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_notes(relative_path: str) -> str:
    return (_repo_root() / relative_path).read_text()


def load_universe_stocks(notes_path: str) -> int:
    """Parse ``notes_path`` and upsert every row into ``mef.universe_stock``.

    Returns the number of rows upserted.
    """
    rows = parse_stocks(_read_notes(notes_path))

    sql = """
        INSERT INTO mef.universe_stock (
            symbol, company_name, sector, industry,
            avg_close_90d, avg_volume_90d, avg_dollar_volume_90d,
            market_cap_usd, options_expirations, total_open_interest,
            last_refreshed_at
        )
        VALUES (
            %(symbol)s, %(company_name)s, %(sector)s, %(industry)s,
            %(avg_close_90d)s, %(avg_volume_90d)s, %(avg_dollar_volume_90d)s,
            %(market_cap_usd)s, %(options_expirations)s, %(total_open_interest)s,
            now()
        )
        ON CONFLICT (symbol) DO UPDATE SET
            company_name           = EXCLUDED.company_name,
            sector                 = EXCLUDED.sector,
            industry               = EXCLUDED.industry,
            avg_close_90d          = EXCLUDED.avg_close_90d,
            avg_volume_90d         = EXCLUDED.avg_volume_90d,
            avg_dollar_volume_90d  = EXCLUDED.avg_dollar_volume_90d,
            market_cap_usd         = EXCLUDED.market_cap_usd,
            options_expirations    = EXCLUDED.options_expirations,
            total_open_interest    = EXCLUDED.total_open_interest,
            last_refreshed_at      = now()
    """

    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def load_universe_etfs(notes_path: str) -> int:
    """Parse ``notes_path`` and upsert every row into ``mef.universe_etf``.

    Returns the number of rows upserted.
    """
    rows = parse_etfs(_read_notes(notes_path))

    sql = """
        INSERT INTO mef.universe_etf (symbol, role, description, last_refreshed_at)
        VALUES (%(symbol)s, %(role)s, %(description)s, now())
        ON CONFLICT (symbol) DO UPDATE SET
            role              = EXCLUDED.role,
            description       = EXCLUDED.description,
            last_refreshed_at = now()
    """

    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def universe_counts() -> dict[str, int]:
    """Return current row counts for the two universe tables."""
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
