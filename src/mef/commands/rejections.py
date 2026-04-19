"""`mef rejections` — list LLM-rejected candidates for audit/tuning.

Filters: --since YYYY-MM-DD, --symbol SYM, --limit N. Defaults to the
20 most recent rejections.
"""

from __future__ import annotations

from typing import Any

from mef.db.connection import connect_mefdb


def _build_query(args) -> tuple[str, list[Any]]:
    wheres = ["c.llm_gate_decision = 'reject'"]
    params: list[Any] = []

    if args.symbol:
        wheres.append("c.symbol = %s")
        params.append(args.symbol.upper())

    if args.since:
        wheres.append("c.created_at::date >= %s")
        params.append(args.since)

    sql = f"""
        SELECT c.uid, c.symbol, c.posture, c.conviction_score,
               c.llm_gate_reason,
               r.uid AS run_uid, r.when_kind, r.intent, r.started_at::date AS run_date
          FROM mef.candidate c
          JOIN mef.daily_run r ON r.uid = c.run_uid
         WHERE {" AND ".join(wheres)}
         ORDER BY r.started_at DESC
    """
    if args.limit:
        sql += " LIMIT %s"
        params.append(args.limit)
    else:
        sql += " LIMIT 20"
    return sql, params


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
        print("No LLM rejections matched.")
        return 0

    print(f"{'date':<11} {'run':<11} {'when':<11} "
          f"{'cand':<10} {'symbol':<6} {'posture':<16} {'conv':>5}  reason")
    print("─" * 110)
    for r in rows:
        reason = (r['llm_gate_reason'] or '').replace("\n", " ")
        if len(reason) > 80:
            reason = reason[:77] + "..."
        print(
            f"{str(r['run_date']):<11} {r['run_uid']:<11} {r['when_kind']:<11} "
            f"{r['uid']:<10} {r['symbol']:<6} {r['posture']:<16} "
            f"{r['conviction_score']:.2f}  {reason}"
        )
    print()
    print(f"{len(rows)} rejection(s).")
    return 0
