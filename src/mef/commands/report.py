"""`mef report --when {premarket|postmarket}` — render the email body for a run.

Reconstructs the daily email from existing MEFDB state, no LLM call,
no SMTP send. Useful for previewing what tomorrow's run will look like
without firing the pipeline, or replaying any historical run.

Selects the latest run matching ``--when`` unless ``--run`` overrides
with a specific UID. Staleness banners are not reconstructed (we don't
re-check freshness on demand) — the rendered body shows the run as if
data was healthy at the time. The DB-stored ``daily_run.notes`` carries
the original staleness disposition for that run if needed.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from mef.db.connection import connect_mefdb
from mef.email_render import render_daily_email


_RUN_BY_UID = """
    SELECT uid, when_kind, intent, started_at
      FROM mef.daily_run
     WHERE uid = %s
"""

_LATEST_RUN_BY_KIND = """
    SELECT uid, when_kind, intent, started_at
      FROM mef.daily_run
     WHERE when_kind = %s
     ORDER BY started_at DESC
     LIMIT 1
"""

_RECS_FOR_RUN = """
    SELECT r.uid, r.symbol, r.asset_kind, r.posture, r.expression,
           r.stop_level, r.target_level, r.time_exit_date,
           c.proposed_entry_zone,
           c.llm_gate_decision,
           c.llm_gate_issue_type,
           c.feature_json,
           r.reasoning_summary
      FROM mef.recommendation r
      LEFT JOIN mef.candidate c ON c.uid = r.candidate_uid
     WHERE r.run_uid = %s
     ORDER BY r.created_at
"""

_GATE_COUNTS = """
    SELECT llm_gate_decision, COUNT(*)
      FROM mef.candidate
     WHERE run_uid = %s
       AND llm_gate_decision IS NOT NULL
     GROUP BY llm_gate_decision
"""

_UNIVERSE = """
    SELECT
       (SELECT COUNT(*) FROM mef.universe_stock) AS stocks,
       (SELECT COUNT(*) FROM mef.universe_etf)   AS etfs
"""


def _estimated_pnl(close, stop, target) -> dict[str, float | None]:
    """Mirror of run_pipeline._estimated_pnl so reports match live emails."""
    if close is None or stop is None or target is None:
        return {"potential_gain_100sh": None, "potential_loss_100sh": None, "risk_reward": None}
    close_f, stop_f, target_f = float(close), float(stop), float(target)
    gain = round((target_f - close_f) * 100, 2)
    loss = round((close_f - stop_f) * 100, 2)
    rr = round(gain / loss, 2) if loss > 0 else None
    return {"potential_gain_100sh": gain, "potential_loss_100sh": loss, "risk_reward": rr}


def _build_idea(rec: dict[str, Any]) -> dict[str, Any]:
    fjson = rec.get("feature_json") or {}
    if isinstance(fjson, str):
        try:
            fjson = json.loads(fjson)
        except Exception:
            fjson = {}
    pnl = _estimated_pnl(fjson.get("close"), rec.get("stop_level"), rec.get("target_level"))
    return {
        "rec_uid":           rec["uid"],
        "symbol":            rec["symbol"],
        "asset_kind":        rec["asset_kind"],
        "posture":           rec["posture"],
        "expression":        rec["expression"],
        "entry_zone":        rec.get("proposed_entry_zone"),
        "stop":              rec.get("stop_level"),
        "target":            rec.get("target_level"),
        "time_exit":         rec.get("time_exit_date"),
        "llm_gate":          rec.get("llm_gate_decision") or "unavailable",
        "issue_type":        rec.get("llm_gate_issue_type"),
        "reasoning_summary": rec.get("reasoning_summary"),
        **pnl,
    }


def run(args) -> int:
    when_kind = args.when
    target_uid = args.run

    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            if target_uid:
                cur.execute(_RUN_BY_UID, (target_uid,))
            else:
                cur.execute(_LATEST_RUN_BY_KIND, (when_kind,))
            run_row = cur.fetchone()
            if run_row is None:
                if target_uid:
                    print(f"mef report: no daily_run with uid={target_uid}", file=sys.stderr)
                else:
                    print(f"mef report: no daily_run yet for when={when_kind}", file=sys.stderr)
                return 1
            run_uid, run_when, intent, started_at = run_row

            cur.execute(_RECS_FOR_RUN, (run_uid,))
            rcols = [d[0] for d in cur.description]
            recs = [dict(zip(rcols, row)) for row in cur.fetchall()]

            cur.execute(_GATE_COUNTS, (run_uid,))
            gate_counts: dict[str, int] = {row[0]: int(row[1]) for row in cur.fetchall()}

            cur.execute(_UNIVERSE)
            stocks, etfs = cur.fetchone()
    finally:
        conn.close()

    ideas = [_build_idea(r) for r in recs]
    email_ideas = [i for i in ideas if i["llm_gate"] in ("approve", "unavailable")]

    email = render_daily_email(
        when_kind=run_when,
        intent=intent,
        run_uid=run_uid,
        started_at=started_at,
        stocks_in_universe=int(stocks),
        etfs_in_universe=int(etfs),
        new_ideas=email_ideas,
        active_updates=[],
        llm_gate_available=("unavailable" not in gate_counts or len(gate_counts) > 1),
        llm_gate_rejected=gate_counts.get("reject", 0),
        llm_gate_review=gate_counts.get("review", 0),
    )

    print(f"Subject: {email.subject}")
    print()
    print(email.body)
    return 0
