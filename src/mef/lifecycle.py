"""Recommendation lifecycle sweeps.

Two idempotent transitions run after every import and at the start of every
``mef run``:

- **Expire proposed.** Any ``proposed`` rec with ``entry_window_end < today``
  is flipped to ``expired``. Catches recommendations the user never
  implemented before the entry window closed.

- **Close on disappearance.** Any ``active`` rec whose symbol is no longer
  present in the most recent ``mef.position_snapshot`` is flipped to one of
  ``closed_win`` / ``closed_loss`` / ``closed_timeout`` based on the last
  known price vs. the rec's target and stop.

Both sweeps are safe to re-run — they filter by current state.

P&L computation stays in milestone 8 (``mef score``). Here we only record
the final state so the state machine is consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from mef.db.connection import connect_mefdb


@dataclass
class LifecycleSummary:
    expired: list[dict[str, Any]]
    closed: list[dict[str, Any]]


def _expire_proposed(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.recommendation
               SET state            = 'expired',
                   state_changed_at = now(),
                   state_changed_by = 'run',
                   updated_at       = now()
             WHERE state = 'proposed'
               AND entry_window_end IS NOT NULL
               AND entry_window_end < CURRENT_DATE
         RETURNING uid, symbol, entry_window_end
            """
        )
        rows = cur.fetchall()
    conn.commit()
    return [{"rec_uid": r[0], "symbol": r[1], "entry_window_end": r[2]} for r in rows]


def _latest_as_of_date(conn) -> date | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(as_of_date) FROM mef.position_snapshot"
        )
        row = cur.fetchone()
    return row[0] if row else None


def _active_recs(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uid, symbol, stop_level, target_level, time_exit_date
              FROM mef.recommendation
             WHERE state = 'active'
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _latest_price_for_symbol(conn, symbol: str) -> tuple[Decimal | None, date | None]:
    """Last known price for a symbol from the most recent snapshot that held it."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(last_price, cost_basis_per_share), as_of_date
              FROM mef.position_snapshot
             WHERE symbol = %s
             ORDER BY as_of_date DESC, position_id DESC
             LIMIT 1
            """,
            (symbol,),
        )
        row = cur.fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _classify_close(
    *,
    last_price: Decimal | None,
    stop: Decimal | None,
    target: Decimal | None,
    time_exit: date | None,
    as_of: date | None,
) -> str:
    """Decide win/loss/timeout for an active rec that just disappeared from holdings."""
    if last_price is not None:
        if target is not None and last_price >= target:
            return "closed_win"
        if stop is not None and last_price <= stop:
            return "closed_loss"
    if time_exit is not None and as_of is not None and as_of >= time_exit:
        return "closed_timeout"
    return "closed_timeout"


def _close_on_disappearance(conn) -> list[dict[str, Any]]:
    """Close actives whose symbol isn't in the latest import."""
    latest_as_of = _latest_as_of_date(conn)
    if latest_as_of is None:
        return []

    # Symbols present in the most recent import batch.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT symbol
              FROM mef.position_snapshot
             WHERE as_of_date = %s
            """,
            (latest_as_of,),
        )
        latest_symbols: set[str] = {row[0] for row in cur.fetchall()}

    closed: list[dict[str, Any]] = []
    for rec in _active_recs(conn):
        if rec["symbol"] in latest_symbols:
            continue

        last_price, last_seen = _latest_price_for_symbol(conn, rec["symbol"])
        new_state = _classify_close(
            last_price=last_price,
            stop=rec.get("stop_level"),
            target=rec.get("target_level"),
            time_exit=rec.get("time_exit_date"),
            as_of=latest_as_of,
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE mef.recommendation
                   SET state            = %s,
                       state_changed_at = now(),
                       state_changed_by = 'import',
                       updated_at       = now()
                 WHERE uid = %s
                   AND state = 'active'
                """,
                (new_state, rec["uid"]),
            )
        conn.commit()
        closed.append({
            "rec_uid":    rec["uid"],
            "symbol":     rec["symbol"],
            "new_state":  new_state,
            "last_price": float(last_price) if last_price is not None else None,
            "last_seen":  last_seen.isoformat() if last_seen else None,
        })
    return closed


def sweep() -> LifecycleSummary:
    """Run both sweeps once. Idempotent."""
    conn = connect_mefdb()
    try:
        expired = _expire_proposed(conn)
        closed = _close_on_disappearance(conn)
        return LifecycleSummary(expired=expired, closed=closed)
    finally:
        conn.close()
