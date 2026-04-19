"""Skeleton daily-run pipeline.

v0 behaviour:

1. Open a ``mef.daily_run`` row (status='running').
2. Read current universe counts from MEFDB.
3. Dummy ranker — always emits zero new ideas.
4. Close ``daily_run`` (status='ok', counts, ended_at).
5. Render the email body via ``mef.email_render``.
6. Print the subject + body to stdout.

Not yet wired:
- Evidence pull from SHDB
- Real ranking / candidate writes
- LLM review
- Active-position lifecycle transitions
- notify.py delivery — the rendered body is printed; `mef run` becomes
  the same as `mef report` until delivery is wired.

Each of those lands in its own milestone per docs/README_mef.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mef.db.connection import connect_mefdb
from mef.email_render import render_daily_email
from mef.uid import next_uid

_INTENT = {
    "premarket":  "today_after_10am",
    "postmarket": "next_trading_day",
}


def _universe_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM mef.universe_stock")
        stocks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mef.universe_etf")
        etfs = cur.fetchone()[0]
    return {"stocks": stocks, "etfs": etfs}


def _open_daily_run(conn, when_kind: str) -> tuple[str, datetime]:
    uid = next_uid(conn, "daily_run")
    started_at = datetime.now(timezone.utc)
    intent = _INTENT[when_kind]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.daily_run (uid, when_kind, intent, started_at, status)
            VALUES (%s, %s, %s, %s, 'running')
            """,
            (uid, when_kind, intent, started_at),
        )
    conn.commit()
    return uid, started_at


def _close_daily_run(
    conn,
    *,
    run_uid: str,
    symbols_evaluated: int,
    candidates_passed: int,
    recommendations_emitted: int,
    notes: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.daily_run
               SET ended_at                = now(),
                   status                  = 'ok',
                   symbols_evaluated       = %s,
                   candidates_passed       = %s,
                   recommendations_emitted = %s,
                   notes                   = COALESCE(%s, notes)
             WHERE uid = %s
            """,
            (symbols_evaluated, candidates_passed, recommendations_emitted, notes, run_uid),
        )
    conn.commit()


def _mark_failed(conn, *, run_uid: str, error_text: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.daily_run
               SET ended_at   = now(),
                   status     = 'failed',
                   error_text = %s
             WHERE uid = %s
            """,
            (error_text, run_uid),
        )
    conn.commit()


def execute(when_kind: str) -> dict[str, Any]:
    """Execute one scheduled run. Returns a summary dict suitable for CLI output."""
    if when_kind not in _INTENT:
        raise ValueError(f"when_kind must be premarket|postmarket, got {when_kind!r}")

    conn = connect_mefdb()
    try:
        run_uid, started_at = _open_daily_run(conn, when_kind)
        try:
            counts = _universe_counts(conn)
            symbols_evaluated = counts["stocks"] + counts["etfs"]

            # v0 dummy ranker: no candidates, no recommendations.
            candidates_passed = 0
            recommendations_emitted = 0

            _close_daily_run(
                conn,
                run_uid=run_uid,
                symbols_evaluated=symbols_evaluated,
                candidates_passed=candidates_passed,
                recommendations_emitted=recommendations_emitted,
                notes="skeleton run — dummy ranker, no evidence pull, no email delivery",
            )

            email = render_daily_email(
                when_kind=when_kind,
                intent=_INTENT[when_kind],
                run_uid=run_uid,
                started_at=started_at,
                stocks_in_universe=counts["stocks"],
                etfs_in_universe=counts["etfs"],
                new_ideas=[],
                active_updates=[],
            )
            return {
                "run_uid":                 run_uid,
                "when_kind":               when_kind,
                "intent":                  _INTENT[when_kind],
                "stocks_in_universe":      counts["stocks"],
                "etfs_in_universe":        counts["etfs"],
                "recommendations_emitted": recommendations_emitted,
                "email_subject":           email.subject,
                "email_body":              email.body,
            }
        except Exception as exc:
            _mark_failed(conn, run_uid=run_uid, error_text=repr(exc))
            raise
    finally:
        conn.close()
