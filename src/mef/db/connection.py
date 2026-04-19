"""Database connection helpers for MEF.

Three connections are used:

- `connect_mefdb()`     — MEF's own database (schema `mef`). Read/write.
- `connect_shdb()`      — SHDB curated data (read-only, spans mart + shdb).
- `connect_overwatch()` — operational telemetry. Fail-silent on write errors.
"""

from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extensions import connection as PGConnection
from psycopg2.extras import RealDictCursor

from mef.config import load_postgres_config


def _connect(section: dict[str, Any], *, read_only: bool = False) -> PGConnection:
    conn = psycopg2.connect(
        host=section["host"],
        port=section["port"],
        database=section["database"],
        user=section["user"],
        password=section["password"],
        connect_timeout=section.get("connect_timeout", 10),
        application_name=section.get("application_name", "mef"),
    )
    if read_only:
        conn.set_session(readonly=True)
    return conn


def connect_mefdb() -> PGConnection:
    """Connect to mefdb with the mef_user role."""
    cfg = load_postgres_config()
    conn = _connect(cfg["mefdb"])
    schema = cfg["mefdb"].get("schema", "mef")
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
    return conn


def connect_shdb() -> PGConnection:
    """Connect to shdb as read-only. Search path includes mart and shdb."""
    cfg = load_postgres_config()
    conn = _connect(cfg["shdb"], read_only=True)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO mart, shdb, public")
    return conn


def connect_overwatch() -> PGConnection:
    """Connect to overwatch for telemetry writes."""
    cfg = load_postgres_config()
    conn = _connect(cfg["overwatch"])
    schema = cfg["overwatch"].get("schema", "ow")
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
    return conn


def query_mefdb(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """Run a SELECT against mefdb and return a list of dict rows."""
    conn = connect_mefdb()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def query_shdb(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """Run a SELECT against shdb (read-only) and return a list of dict rows."""
    conn = connect_shdb()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
