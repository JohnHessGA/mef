"""`mef status` — environment and data-source status overview.

Checks config files, DB connectivity, artifact root, and log directory.
Prints a compact green/red summary. Exits non-zero if any critical check fails.
"""

from __future__ import annotations

from pathlib import Path

from mef.config import load_app_config, load_postgres_config
from mef.db.connection import connect_mefdb, connect_overwatch, connect_shdb

OK = "\033[32mOK\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def _check(label: str, check_fn) -> bool:
    try:
        detail = check_fn()
        print(f"  [{OK}]  {label:<32} {detail}")
        return True
    except Exception as exc:
        print(f"  [{FAIL}] {label:<32} {exc}")
        return False


def _config_check() -> str:
    load_postgres_config()
    load_app_config()
    return "postgres.yaml + mef.yaml loaded"


def _mefdb_ping() -> str:
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_database(), current_user, "
                "  (SELECT count(*) FROM information_schema.schemata WHERE schema_name='mef'), "
                "  (SELECT count(*) FROM information_schema.tables    WHERE table_schema='mef')"
            )
            db, user, has_schema, table_count = cur.fetchone()
        if not has_schema:
            note = "schema mef NOT created yet (run `mef init-db`)"
        else:
            note = f"schema mef: {table_count} tables"
        return f"{db} as {user} — {note}"
    finally:
        conn.close()


def _shdb_ping() -> str:
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT "
                "  (SELECT count(*) FROM information_schema.tables WHERE table_schema='mart'), "
                "  (SELECT count(*) FROM information_schema.tables WHERE table_schema='shdb')"
            )
            mart_n, shdb_n = cur.fetchone()
        return f"mart={mart_n} tables, shdb={shdb_n} tables"
    finally:
        conn.close()


def _overwatch_ping() -> str:
    conn = connect_overwatch()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='ow' AND table_name LIKE 'mef_%'"
            )
            mef_tables = cur.fetchone()[0]
        return f"{mef_tables} ow.mef_* tables" if mef_tables else "no ow.mef_* tables yet"
    finally:
        conn.close()


def _artifact_root_check() -> str:
    cfg = load_app_config()
    root = Path(cfg["artifacts"]["root"])
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        return f"{root} (created)"
    return f"{root}"


def _log_dir_check() -> str:
    cfg = load_app_config()
    log_dir = Path(cfg["logging"]["dir"])
    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
        return f"{log_dir} (created)"
    return f"{log_dir}"


def run(args) -> int:
    print("MEF status")
    print("==========")

    results = [
        _check("config files",         _config_check),
        _check("mefdb connection",     _mefdb_ping),
        _check("shdb connection",      _shdb_ping),
        _check("overwatch connection", _overwatch_ping),
        _check("artifact root",        _artifact_root_check),
        _check("log directory",        _log_dir_check),
    ]

    print()
    if all(results):
        print(f"All checks passed ({len(results)}/{len(results)}).")
        return 0
    print(f"{sum(results)}/{len(results)} checks passed.")
    return 1
