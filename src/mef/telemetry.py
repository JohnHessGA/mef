"""Fail-silent telemetry writes to the ``overwatch`` database.

Two tables, both in schema ``ow``:

- ``ow.mef_run``   — one row per scheduled MEF run (counts + status + duration).
- ``ow.mef_event`` — discrete events (info / warning / error) bound to a run.

Every public function in this module catches all exceptions and logs to
stderr — telemetry must **never** break a daily run. If overwatch is down,
MEF still emits its email and writes its rows in MEFDB.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from mef.db.connection import connect_overwatch


def _log(msg: str) -> None:
    """Last-resort stderr logger when telemetry can't reach overwatch."""
    print(f"[mef.telemetry] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────
# ow.mef_run lifecycle
# ─────────────────────────────────────────────────────────────────────────

def start_run(*, run_uid: str, when_kind: str, intent: str, started_at: datetime) -> None:
    """Insert a status='running' row at the start of a run."""
    try:
        conn = connect_overwatch()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ow.mef_run (
                        run_uid, when_kind, intent, started_at, status
                    )
                    VALUES (%s, %s, %s, %s, 'running')
                    ON CONFLICT (run_uid) DO UPDATE SET
                        when_kind  = EXCLUDED.when_kind,
                        intent     = EXCLUDED.intent,
                        started_at = EXCLUDED.started_at,
                        status     = 'running',
                        ended_at   = NULL,
                        error_text = NULL
                    """,
                    (run_uid, when_kind, intent, started_at),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _log(f"start_run({run_uid}) failed: {exc}")


def complete_run(
    *,
    run_uid: str,
    started_at: datetime,
    counts: dict[str, Any],
    email_sent: bool,
) -> None:
    """Update a run row to status='ok' with final counts and duration."""
    try:
        ended_at = datetime.now(timezone.utc)
        duration_s = round((ended_at - started_at).total_seconds(), 3)
        conn = connect_overwatch()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ow.mef_run SET
                        ended_at                = %s,
                        status                  = 'ok',
                        duration_seconds        = %s,
                        symbols_evaluated       = %s,
                        candidates_passed       = %s,
                        recommendations_emitted = %s,
                        gate_approved           = %s,
                        gate_review             = %s,
                        gate_rejected           = %s,
                        gate_unavailable        = %s,
                        lifecycle_expired       = %s,
                        lifecycle_closed        = %s,
                        scored                  = %s,
                        shadow_scored           = %s,
                        shadow_deferred         = %s,
                        paper_scored            = %s,
                        paper_deferred          = %s,
                        email_sent              = %s
                     WHERE run_uid = %s
                    """,
                    (
                        ended_at, duration_s,
                        counts.get("symbols_evaluated"),
                        counts.get("candidates_passed"),
                        counts.get("recommendations_emitted"),
                        counts.get("gate_approved"),
                        counts.get("gate_review"),
                        counts.get("gate_rejected"),
                        counts.get("gate_unavailable"),
                        counts.get("lifecycle_expired"),
                        counts.get("lifecycle_closed"),
                        counts.get("scored"),
                        counts.get("shadow_scored"),
                        counts.get("shadow_deferred"),
                        counts.get("paper_scored"),
                        counts.get("paper_deferred"),
                        bool(email_sent),
                        run_uid,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _log(f"complete_run({run_uid}) failed: {exc}")


def fail_run(*, run_uid: str, started_at: datetime, error_text: str) -> None:
    """Update a run row to status='failed' with the error text."""
    try:
        ended_at = datetime.now(timezone.utc)
        duration_s = round((ended_at - started_at).total_seconds(), 3)
        conn = connect_overwatch()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ow.mef_run SET
                        ended_at         = %s,
                        status           = 'failed',
                        duration_seconds = %s,
                        error_text       = %s
                     WHERE run_uid = %s
                    """,
                    (ended_at, duration_s, error_text[:8000], run_uid),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _log(f"fail_run({run_uid}) failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────
# ow.mef_event
# ─────────────────────────────────────────────────────────────────────────

def event(
    *,
    severity: str,
    code: str,
    message: str | None = None,
    run_uid: str | None = None,
) -> None:
    """Insert an event row. Severity ∈ {info, warning, error}."""
    if severity not in ("info", "warning", "error"):
        severity = "info"
    try:
        conn = connect_overwatch()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ow.mef_event (run_uid, severity, code, message)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (run_uid, severity, code, message),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _log(f"event({code}) failed: {exc}")
