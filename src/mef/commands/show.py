"""`mef show <rec-uid>` — full detail on one recommendation.

Joins to ``mef.candidate`` for evidence + gate reason, and to
``mef.position_snapshot`` (via active_match_position_uid) for holdings
context when the rec is active or closed.
"""

from __future__ import annotations

import json

from mef.db.connection import connect_mefdb


_REC_QUERY = """
SELECT
    r.uid, r.run_uid, r.candidate_uid, r.symbol, r.asset_kind, r.posture,
    r.expression, r.entry_method, r.entry_window_end,
    r.stop_level, r.invalidation_rule,
    r.target_level, r.target_rule,
    r.time_exit_date, r.confidence, r.reasoning_summary,
    r.llm_review_color, r.llm_review_concern,
    r.state, r.state_changed_at, r.state_changed_by,
    r.active_match_position_uid,
    r.created_at, r.updated_at,
    c.proposed_entry_zone, c.conviction_score, c.feature_json,
    c.llm_gate_decision, c.llm_gate_reason
  FROM mef.recommendation r
  LEFT JOIN mef.candidate c ON c.uid = r.candidate_uid
 WHERE r.uid = %s
"""

_POSITION_QUERY = """
SELECT symbol, quantity, cost_basis_per_share, last_price, market_value,
       as_of_date, import_uid
  FROM mef.position_snapshot
 WHERE uid = %s
"""


def _money(v) -> str:
    return f"${v:,.2f}" if v is not None else "-"


def run(args) -> int:
    rec_uid = args.uid
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute(_REC_QUERY, (rec_uid,))
            row = cur.fetchone()
            if row is None:
                print(f"rec {rec_uid} not found.")
                return 1
            cols = [d[0] for d in cur.description]
            rec = dict(zip(cols, row))

            position = None
            if rec.get("active_match_position_uid"):
                cur.execute(_POSITION_QUERY, (rec["active_match_position_uid"],))
                pos_row = cur.fetchone()
                if pos_row is not None:
                    pcols = [d[0] for d in cur.description]
                    position = dict(zip(pcols, pos_row))
    finally:
        conn.close()

    print(f"{rec['uid']}  {rec['symbol']} ({rec['asset_kind']})  state={rec['state']}")
    print("─" * 60)
    print(f"posture:          {rec['posture']}")
    print(f"expression:       {rec['expression']}")
    print(f"entry method:     {rec['entry_method']}")
    print(f"entry window:     {rec['proposed_entry_zone']} (closes {rec['entry_window_end']})")
    print(f"stop:             {_money(rec['stop_level'])}  rule: {rec['invalidation_rule']}")
    print(f"target:           {_money(rec['target_level'])}  rule: {rec['target_rule']}")
    print(f"time exit:        {rec['time_exit_date']}")
    print(f"conviction:       {rec['conviction_score']}  confidence stamp: {rec['confidence']}")
    print()

    print("LLM gate:")
    print(f"  decision:       {rec['llm_gate_decision'] or '-'}")
    print(f"  reason:         {rec['llm_gate_reason'] or '-'}")
    print(f"  ship reasoning: {rec['reasoning_summary']}")
    print()

    if position:
        print("Matched holding:")
        print(f"  position uid:   {rec['active_match_position_uid']}")
        qty = position.get("quantity")
        if qty is not None:
            print(f"  quantity:       {float(qty):,.0f}")
        print(f"  cost basis/sh:  {_money(position.get('cost_basis_per_share'))}")
        print(f"  last price:     {_money(position.get('last_price'))}")
        print(f"  market value:   {_money(position.get('market_value'))}")
        print(f"  as-of:          {position.get('as_of_date')}")
        print()

    print("Lineage:")
    print(f"  run:            {rec['run_uid']}")
    print(f"  candidate:      {rec['candidate_uid']}")
    print(f"  created:        {rec['created_at']}")
    print(f"  last change:    {rec['state_changed_at']} by {rec['state_changed_by']}")
    if rec.get("feature_json"):
        feats = rec["feature_json"] if isinstance(rec["feature_json"], dict) else json.loads(rec["feature_json"])
        print()
        print("Evidence at emission:")
        for key in ("close", "return_20d", "return_63d", "rsi_14",
                    "macd_histogram", "realized_vol_20d",
                    "drawdown_current", "volume_z_score", "sector"):
            if key in feats:
                val = feats[key]
                print(f"  {key:<20} {val}")
    return 0
