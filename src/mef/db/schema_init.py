"""Apply MEFDB and Overwatch migration files.

- ``sql/mefdb/*.sql``     → applied to the ``mefdb`` database (schema ``mef``)
- ``sql/overwatch/*.sql`` → applied to the ``overwatch`` database (schema ``ow``)

Each `.sql` file is idempotent (CREATE ... IF NOT EXISTS, ALTER TABLE ADD
COLUMN IF NOT EXISTS, DO blocks for constraints). The runner just discovers
files in numeric order and ships them through psycopg2 with psql backslash
directives stripped.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from mef.db.connection import connect_mefdb, connect_overwatch

_MEFDB_DIR = Path(__file__).resolve().parents[3] / "sql" / "mefdb"
_OVERWATCH_DIR = Path(__file__).resolve().parents[3] / "sql" / "overwatch"

_FILENAME_RE = re.compile(r"^(\d+)_.+\.sql$")


def _list_migrations(sql_dir: Path) -> list[Path]:
    if not sql_dir.is_dir():
        return []
    entries: list[tuple[int, Path]] = []
    for p in sql_dir.iterdir():
        match = _FILENAME_RE.match(p.name)
        if not match:
            continue
        entries.append((int(match.group(1)), p))
    entries.sort(key=lambda pair: pair[0])
    return [p for _, p in entries]


def list_migrations(sql_dir: Path | None = None) -> list[Path]:
    """Backwards-compatible: defaults to mefdb migrations only."""
    return _list_migrations(sql_dir or _MEFDB_DIR)


def _apply(sql_dir: Path, connect: Callable) -> list[tuple[Path, float]]:
    migrations = _list_migrations(sql_dir)
    if not migrations:
        return []

    applied: list[tuple[Path, float]] = []
    conn = connect()
    try:
        for path in migrations:
            start = time.monotonic()
            sql_text = _strip_psql_directives(path.read_text())
            with conn.cursor() as cur:
                cur.execute(sql_text)
            conn.commit()
            applied.append((path, time.monotonic() - start))
    finally:
        conn.close()
    return applied


def apply_migrations() -> list[tuple[Path, float]]:
    """Apply MEFDB migrations only (preserved for callers that don't want overwatch)."""
    return _apply(_MEFDB_DIR, connect_mefdb)


def apply_overwatch_migrations() -> list[tuple[Path, float]]:
    """Apply overwatch migrations against the overwatch database."""
    return _apply(_OVERWATCH_DIR, connect_overwatch)


def apply_all_migrations() -> dict[str, list[tuple[Path, float]]]:
    """Apply both MEFDB and overwatch migrations. Each set runs in its own connection."""
    return {
        "mefdb":     apply_migrations(),
        "overwatch": apply_overwatch_migrations(),
    }


def _strip_psql_directives(sql: str) -> str:
    """Remove psql-only backslash directives so psycopg2 can run the file."""
    keep: list[str] = []
    for line in sql.splitlines():
        if line.lstrip().startswith("\\"):
            continue
        keep.append(line)
    return "\n".join(keep)
