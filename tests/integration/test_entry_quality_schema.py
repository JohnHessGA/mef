"""Integration check that migration 015 ships the Entry Quality columns.

Skips cleanly when mefdb is unavailable or the migration hasn't been
applied yet so this test won't false-fail in a dev environment.
"""

from __future__ import annotations

import pytest

from mef.db.connection import connect_mefdb


@pytest.fixture(scope="module")
def mefdb():
    try:
        conn = connect_mefdb()
    except Exception as e:
        pytest.skip(f"mefdb unavailable: {e}")
    yield conn
    conn.close()


def _columns_on(conn, table: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type
              FROM information_schema.columns
             WHERE table_schema='mef' AND table_name=%s
            """,
            (table,),
        )
        return {name: dtype for name, dtype in cur.fetchall()}


def test_migration_015_added_entry_quality_columns(mefdb):
    cols = _columns_on(mefdb, "candidate")
    if "entry_quality_status" not in cols:
        pytest.skip("migration 015 not applied — run `mef init-db`")
    assert cols["entry_quality_status"] == "text"
    assert cols["entry_quality_flags"] == "ARRAY"
    assert cols["entry_quality_summary"] == "text"
    assert cols["entry_quality_risk_reward"] == "numeric"


def test_status_check_constraint_present(mefdb):
    with mefdb.cursor() as cur:
        cur.execute("""
            SELECT pg_get_constraintdef(oid)
              FROM pg_constraint
             WHERE conname = 'candidate_entry_quality_status_chk'
        """)
        row = cur.fetchone()
    if row is None:
        pytest.skip("migration 015 not applied — run `mef init-db`")
    chkdef = row[0]
    for value in ("pass", "watch"):
        assert value in chkdef, (
            f"entry_quality_status CHECK missing {value!r}: {chkdef}"
        )
