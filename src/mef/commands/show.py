"""`mef show <rec-uid>` — full detail on one recommendation.

Joins to:
- ``mef.candidate`` for evidence + gate decision/issue_type/reason
- ``mef.position_snapshot`` (via active_match_position_uid) for the
  matched holding when the rec is active or closed
- ``mef.paper_score`` for the synthetic forward-walked outcome
- ``mef.score`` for the realized outcome (when actual trade is linked)
- ``mef.recommendation_pnl_daily`` for the MTM time series
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
    r.provenance, r.provenance_set_by,
    r.created_at, r.updated_at,
    c.proposed_entry_zone, c.conviction_score, c.feature_json,
    c.llm_gate_decision, c.llm_gate_issue_type, c.llm_gate_reason
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

_PAPER_QUERY = """
SELECT uid, gate_decision, outcome,
       entry_price, exit_price, entry_date, exit_date, days_held,
       estimated_pnl_100_shares_usd,
       spy_return_same_window,
       sector_etf_symbol, sector_etf_return_same_window
  FROM mef.paper_score
 WHERE rec_uid = %s
"""

_SCORE_QUERY = """
SELECT uid, outcome,
       entry_price, exit_price, entry_date, exit_date, days_held,
       estimated_pnl_100_shares_usd,
       spy_return_same_window,
       sector_etf_symbol, sector_etf_return_same_window,
       realized_qty, realized_buy_price, realized_buy_date,
       realized_sell_price, realized_sell_date,
       realized_pnl_usd, realized_pnl_per_day
  FROM mef.score
 WHERE rec_uid = %s
"""

_PNL_DAILY_QUERY = """
SELECT as_of_date, last_price, market_value,
       unrealized_pnl_usd, unrealized_pnl_pct, days_held_so_far,
       is_close_day, price_source
  FROM mef.recommendation_pnl_daily
 WHERE rec_uid = %s
 ORDER BY as_of_date
"""


def _money(v) -> str:
    return f"${v:,.2f}" if v is not None else "-"


def _pct(v) -> str:
    return f"{v * 100:+.2f}%" if v is not None else "-"


def _fetch_one(cur, sql, params):
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _fetch_all(cur, sql, params):
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def run(args) -> int:
    rec_uid = args.uid
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            rec = _fetch_one(cur, _REC_QUERY, (rec_uid,))
            if rec is None:
                print(f"rec {rec_uid} not found.")
                return 1
            position = (
                _fetch_one(cur, _POSITION_QUERY, (rec["active_match_position_uid"],))
                if rec.get("active_match_position_uid") else None
            )
            paper = _fetch_one(cur, _PAPER_QUERY, (rec_uid,))
            score = _fetch_one(cur, _SCORE_QUERY, (rec_uid,))
            pnl_curve = _fetch_all(cur, _PNL_DAILY_QUERY, (rec_uid,))
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
    if rec.get("provenance"):
        print(f"provenance:       {rec['provenance']} (set by {rec.get('provenance_set_by') or '-'})")
    print()

    print("LLM gate:")
    print(f"  decision:       {rec['llm_gate_decision'] or '-'}")
    print(f"  issue_type:     {rec.get('llm_gate_issue_type') or '-'}")
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

    if paper:
        print("Paper-trade outcome (synthetic, close-of-run-day entry):")
        print(f"  paper uid:      {paper['uid']}")
        print(f"  outcome:        {paper['outcome']}")
        print(f"  entry → exit:   {_money(paper.get('entry_price'))} on {paper.get('entry_date')}"
              f"  →  {_money(paper.get('exit_price'))} on {paper.get('exit_date')}")
        print(f"  days held:      {paper.get('days_held') if paper.get('days_held') is not None else '-'}")
        print(f"  P&L / 100sh:    {_money(paper.get('estimated_pnl_100_shares_usd'))}")
        print(f"  vs SPY:         {_pct(paper.get('spy_return_same_window'))}"
              f"  vs {paper.get('sector_etf_symbol') or '-'}: {_pct(paper.get('sector_etf_return_same_window'))}")
        print()

    if score:
        print("Realized scoring (actual outcome):")
        print(f"  score uid:      {score['uid']}")
        print(f"  outcome:        {score['outcome']}")
        print(f"  est. P&L/100sh: {_money(score.get('estimated_pnl_100_shares_usd'))}")
        if score.get("realized_qty") is not None:
            print(f"  REAL qty:       {float(score['realized_qty']):,.4f}")
            print(f"  REAL buy:       {_money(score.get('realized_buy_price'))} on {score.get('realized_buy_date')}")
            print(f"  REAL sell:      {_money(score.get('realized_sell_price'))} on {score.get('realized_sell_date') or '(still holding)'}")
            print(f"  REAL P&L:       {_money(score.get('realized_pnl_usd'))}")
            if score.get("realized_pnl_per_day") is not None:
                print(f"  P&L / day:      ${float(score['realized_pnl_per_day']):,.4f}")
        else:
            print("  (no real trade linked — use `mef link-trade` to record actuals)")
        print()

    if pnl_curve:
        print(f"Daily P&L curve ({len(pnl_curve)} day(s)):")
        print(f"  {'date':<12} {'price':>10} {'mkt val':>14} {'unrealized':>14} {'%':>8} {'days':>5} {'src':<20}")
        for row in pnl_curve:
            tag = " ←CLOSE" if row.get("is_close_day") else ""
            print(
                f"  {str(row['as_of_date']):<12} "
                f"{_money(row.get('last_price')):>10} "
                f"{_money(row.get('market_value')):>14} "
                f"{_money(row.get('unrealized_pnl_usd')):>14} "
                f"{_pct(row.get('unrealized_pnl_pct')):>8} "
                f"{(row.get('days_held_so_far') if row.get('days_held_so_far') is not None else '-'):>5} "
                f"{(row.get('price_source') or '-'):<20}{tag}"
            )
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
