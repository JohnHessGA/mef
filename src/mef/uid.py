"""Human-readable UID generation for MEFDB records.

Every MEFDB entity with a ``uid`` column follows the ``PREFIX-NNNNNN`` shape
(6-digit zero-padded suffix). The next UID for a given table is derived by
reading ``MAX(numeric suffix)`` from its ``uid`` column and incrementing.
This works even after manual deletes and keeps the prefix/table mapping
obvious without needing a sequence per table.

Prefixes are defined in ``docs/mef_design_spec.md`` §11.
"""

from __future__ import annotations

from psycopg2.extensions import connection as PGConnection

# Table → UID prefix. Keep in sync with docs/mef_design_spec.md §11.
UID_PREFIX: dict[str, str] = {
    "daily_run":             "DR",
    "candidate":             "C",
    "recommendation":        "R",
    "recommendation_update": "U",
    "import_batch":          "I",
    "position_snapshot":     "P",
    "score":                 "S",
    "shadow_score":          "SS",
    "paper_score":           "PS",
    "llm_trace":             "L",
}

# Tables intentionally without UIDs — keyed on symbol or (date, symbol).
NO_UID_TABLES: set[str] = {
    "universe_stock",
    "universe_etf",
    "benchmark_snapshot",
    "command_log",
}

_WIDTH = 6


def next_uid(conn: PGConnection, table: str) -> str:
    """Return the next UID for ``mef.<table>``.

    Caller owns the transaction. Intended usage is within the same cursor
    that performs the INSERT, so the UID is visible only after commit.
    """
    if table not in UID_PREFIX:
        raise ValueError(
            f"Table {table!r} has no UID prefix "
            f"(NO_UID_TABLES={sorted(NO_UID_TABLES)})"
        )

    prefix = UID_PREFIX[table]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COALESCE(
                MAX(CAST(SPLIT_PART(uid, '-', 2) AS INTEGER)),
                0
            ) + 1
            FROM mef.{table}
            """
        )
        next_n = cur.fetchone()[0]
    return f"{prefix}-{next_n:0{_WIDTH}d}"
