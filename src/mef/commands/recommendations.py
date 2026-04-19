"""`mef recommendations` — list recommendations by state / symbol / date.

Defaults: show proposed + active recs only (the "live" ones). Use --all or
--state closed_win to reach closed history.
"""

from __future__ import annotations

from typing import Any

from mef.db.connection import connect_mefdb

_LIVE_STATES = ("proposed", "active")
_ALL_STATES = (
    "proposed", "active", "dismissed", "expired",
    "closed_win", "closed_loss", "closed_timeout",
)


def _build_query(args) -> tuple[str, list[Any]]:
    wheres: list[str] = []
    params: list[Any] = []

    if args.state:
        wheres.append("state = %s")
        params.append(args.state)
    elif args.all:
        wheres.append("state = ANY(%s)")
        params.append(list(_ALL_STATES))
    else:
        wheres.append("state = ANY(%s)")
        params.append(list(_LIVE_STATES))

    if args.symbol:
        wheres.append("symbol = %s")
        params.append(args.symbol.upper())

    if args.since:
        wheres.append("created_at::date >= %s")
        params.append(args.since)

    sql = """
        SELECT uid, symbol, asset_kind, posture, expression, state,
               stop_level, target_level, time_exit_date, confidence,
               created_at, state_changed_at, state_changed_by
          FROM mef.recommendation
    """
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY created_at DESC"
    if args.limit:
        sql += " LIMIT %s"
        params.append(args.limit)
    else:
        sql += " LIMIT 30"
    return sql, params


_STATE_GLYPH = {
    "proposed":       "·",
    "active":         "▲",
    "dismissed":      "×",
    "expired":        "⌛",
    "closed_win":     "✔",
    "closed_loss":    "✘",
    "closed_timeout": "◇",
}


def run(args) -> int:
    sql, params = _build_query(args)
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    if not rows:
        print("No recommendations matched.")
        return 0

    print(f"{'glyph':<5} {'uid':<11} {'symbol':<6} {'state':<15} "
          f"{'posture':<16} {'expression':<18} "
          f"{'stop':>10} {'target':>10} {'conv':>5}")
    print("─" * 107)
    for r in rows:
        glyph = _STATE_GLYPH.get(r["state"], "?")
        stop = f"${r['stop_level']:,.2f}" if r['stop_level'] is not None else "-"
        target = f"${r['target_level']:,.2f}" if r['target_level'] is not None else "-"
        conv = f"{r['confidence']:.2f}" if r['confidence'] is not None else "-"
        print(
            f"{glyph:<5} {r['uid']:<11} {r['symbol']:<6} {r['state']:<15} "
            f"{r['posture']:<16} {r['expression']:<18} "
            f"{stop:>10} {target:>10} {conv:>5}"
        )
    print()
    print(f"{len(rows)} recommendation(s).")
    return 0
