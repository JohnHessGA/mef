"""Apply MEFDB migration files under `sql/mefdb/` in numeric order.

Idempotent — each `.sql` file uses CREATE ... IF NOT EXISTS and safe DO blocks.
This module orchestrates discovery + ordered application only. No migrations-
tracking table; files are safe to re-apply.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from mef.db.connection import connect_mefdb

_SQL_DIR_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "sql" / "mefdb",
]

_FILENAME_RE = re.compile(r"^(\d+)_.+\.sql$")


def _find_sql_dir() -> Path:
    for candidate in _SQL_DIR_CANDIDATES:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not locate sql/mefdb/ directory. Tried: {_SQL_DIR_CANDIDATES}"
    )


def list_migrations(sql_dir: Path | None = None) -> list[Path]:
    """Return migration files sorted by their numeric prefix."""
    sql_dir = sql_dir or _find_sql_dir()
    entries: list[tuple[int, Path]] = []
    for p in sql_dir.iterdir():
        match = _FILENAME_RE.match(p.name)
        if not match:
            continue
        entries.append((int(match.group(1)), p))
    entries.sort(key=lambda pair: pair[0])
    return [p for _, p in entries]


def apply_migrations() -> list[tuple[Path, float]]:
    """Apply every migration in order. Return [(path, elapsed_seconds)]."""
    migrations = list_migrations()
    if not migrations:
        return []

    applied: list[tuple[Path, float]] = []
    conn = connect_mefdb()
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


def _strip_psql_directives(sql: str) -> str:
    """Remove psql-only backslash directives so psycopg2 can run the file.

    Lines starting with \\ (e.g. \\echo, \\set, \\gexec) are psql client
    features, not server SQL. They're harmless when the file is run via
    `psql -f`, but psycopg2 doesn't understand them.
    """
    keep: list[str] = []
    for line in sql.splitlines():
        if line.lstrip().startswith("\\"):
            continue
        keep.append(line)
    return "\n".join(keep)
