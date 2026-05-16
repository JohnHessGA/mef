"""`mef health` — operational + environment health view.

Combines:
  - environment & connectivity probes (config, MEFDB, SHDB, Overwatch,
    artifact root, log directory)
  - latest-run summary (uid, when, duration, pipeline counts)
  - data-source freshness (mart bar date vs configured warn/abort
    thresholds, mirroring the pipeline's `mef.evidence.check_freshness`)
  - recent OW mef_event activity (last 24h warnings + errors)

This is the operator's dashboard. `mef status` is the *user-facing*
recommendation report; this command holds everything else.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mef.config import load_app_config, load_postgres_config
from mef.db.connection import connect_mefdb, connect_overwatch, connect_shdb

OK = "\033[32mOK\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


# ───────────────────────────── env probes ─────────────────────────────

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
    return "postgres.secrets.yaml + mef.yaml loaded"


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
            note = "schema mef NOT created yet (apply sql/mefdb/*.sql migrations)"
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


# ───────────────────────────── operational probes ─────────────────────────────

def fetch_latest_run() -> dict[str, Any] | None:
    try:
        conn = connect_mefdb()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT uid, when_kind, intent, status, started_at, ended_at,
                       symbols_evaluated, candidates_passed, recommendations_emitted,
                       email_sent_at
                  FROM mef.daily_run
                 ORDER BY started_at DESC
                 LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    finally:
        conn.close()


def fetch_mart_freshness() -> dict[str, Any]:
    """Mirror the pipeline's freshness check (mef.evidence.check_freshness).

    Strict-greater semantics:
        age <= warn_after_calendar_days   → ok
        age >  warn_after_calendar_days   → stale
        age >  abort_after_calendar_days  → abort
    """
    out: dict[str, Any] = {
        "latest_bar": None, "days_behind": None, "tier": None,
        "warn_threshold": 4, "abort_threshold": 7,
    }

    try:
        cfg = (load_app_config() or {}).get("data_freshness", {}) or {}
        out["warn_threshold"] = int(cfg.get("warn_after_calendar_days", 4))
        out["abort_threshold"] = int(cfg.get("abort_after_calendar_days", 7))
    except Exception:
        pass

    try:
        conn = connect_shdb()
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT GREATEST(
                    (SELECT max(bar_date) FROM mart.stock_equity_daily),
                    (SELECT max(bar_date) FROM mart.stock_etf_daily)
                )
            """)
            latest = cur.fetchone()[0]
    finally:
        conn.close()

    if latest is None:
        return out

    days = (date.today() - latest).days
    out["latest_bar"] = latest
    out["days_behind"] = days
    if days > out["abort_threshold"]:
        out["tier"] = "abort"
    elif days > out["warn_threshold"]:
        out["tier"] = "stale"
    else:
        out["tier"] = "ok"
    return out


def fetch_recent_alerts(hours: int = 24) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {"error": [], "warning": []}
    try:
        conn = connect_overwatch()
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT severity, code, count(*)
                  FROM ow.mef_event
                 WHERE severity IN ('error','warning')
                   AND created_at > now() - (%s || ' hours')::interval
                 GROUP BY severity, code
                 ORDER BY 1, 3 DESC
                """,
                (str(hours),),
            )
            for severity, code, n in cur.fetchall():
                out.setdefault(severity, []).append((code, int(n)))
    finally:
        conn.close()
    return out


# ───────────────────────────── operational rendering ─────────────────────────────

def render_latest_run(run: dict[str, Any] | None) -> list[str]:
    if not run:
        return ["Latest run", "  (none — MEF has not been run yet)"]
    started = _fmt_dt(run.get("started_at"))
    ended = run.get("ended_at")
    duration = _fmt_duration(run.get("started_at"), ended) if ended else "running"
    lines = [
        "Latest run",
        f"  uid:           {run['uid']}",
        f"  started:       {started} ({run.get('when_kind','?')}, {duration}, status={run.get('status','?')})",
    ]
    pipeline = (
        f"{run.get('symbols_evaluated','?')} evaluated → "
        f"{run.get('candidates_passed','?')} passed → "
        f"{run.get('recommendations_emitted','?')} emitted"
    )
    lines.append(f"  pipeline:      {pipeline}")
    return lines


def render_data_status(freshness: dict[str, Any], alerts: dict[str, list[tuple[str, int]]]) -> list[str]:
    lines = ["Data status"]
    if freshness.get("latest_bar") is None:
        lines.append("  SHDB mart:     unavailable")
    else:
        tier = freshness.get("tier")
        if tier == "ok":
            tag = "fresh"
        elif tier == "stale":
            tag = f"STALE ({freshness['days_behind']}d behind, warn>{freshness['warn_threshold']})"
        elif tier == "abort":
            tag = f"ABORT ({freshness['days_behind']}d behind, abort>{freshness['abort_threshold']})"
        else:
            tag = f"unknown ({freshness.get('days_behind','?')}d)"
        lines.append(f"  SHDB mart:     latest bar {freshness['latest_bar']} ({tag})")

    err_total = sum(n for _, n in alerts.get("error", []))
    warn_total = sum(n for _, n in alerts.get("warning", []))
    if not err_total and not warn_total:
        lines.append("  Alerts (24h):  none")
    else:
        parts = []
        if err_total:
            err_codes = ", ".join(f"{c}×{n}" for c, n in alerts["error"])
            parts.append(f"{err_total} error ({err_codes})")
        if warn_total:
            warn_codes = ", ".join(f"{c}×{n}" for c, n in alerts["warning"])
            parts.append(f"{warn_total} warning ({warn_codes})")
        lines.append(f"  Alerts (24h):  {' · '.join(parts)}")
    return lines


# ───────────────────────────── small formatters ─────────────────────────────

def _fmt_dt(dt) -> str:
    if dt is None:
        return "?"
    if isinstance(dt, datetime):
        local = dt.astimezone() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone()
        return local.strftime("%Y-%m-%d %H:%M %Z").strip()
    return str(dt)


def _fmt_duration(start, end) -> str:
    if start is None or end is None:
        return "?"
    try:
        secs = int((end - start).total_seconds())
    except Exception:
        return "?"
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m{secs % 60:02d}s"


# ───────────────────────────── entry ─────────────────────────────

def run(args) -> int:
    print("MEF health")
    print("==========")
    print()
    print("Environment")

    results = [
        _check("config files",         _config_check),
        _check("mefdb connection",     _mefdb_ping),
        _check("shdb connection",      _shdb_ping),
        _check("overwatch connection", _overwatch_ping),
        _check("artifact root",        _artifact_root_check),
        _check("log directory",        _log_dir_check),
    ]

    print()
    for line in render_latest_run(fetch_latest_run()):
        print(line)
    print()
    for line in render_data_status(fetch_mart_freshness(), fetch_recent_alerts()):
        print(line)

    print()
    if all(results):
        print(f"All environment checks passed ({len(results)}/{len(results)}).")
        return 0
    print(f"{sum(results)}/{len(results)} environment checks passed.")
    return 1
