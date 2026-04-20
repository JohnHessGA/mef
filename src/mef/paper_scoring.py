"""Paper-trade scoring for every emitted recommendation.

Same forward-walk algorithm shadow_scoring uses for rejected candidates,
applied here to *emitted* recs (gate_decision in approve / unavailable).
This collapses the validation horizon from "wait for John to actually
buy something and close it" (months) to "wait for time_exit to elapse
or for stop/target to hit" (typically 2-6 weeks).

Entry price = the candidate's ``feature_json->>'close'`` — the same
anchor shadow_scoring uses, so paper and shadow outcomes can be compared
apples-to-apples in audit queries.

Resolution rules: ``classify_walk`` from ``mef.shadow_scoring`` is the
single source of truth for outcome classification — the function is pure
and already tested, so this module is just orchestration.

Idempotent + incremental: skip recs already in ``mef.paper_score``,
defer recs whose time_exit hasn't elapsed and haven't hit stop/target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from mef.db.connection import connect_mefdb, connect_shdb
from mef.scoring import _SECTOR_TO_ETF, _spy_sector_returns
from mef.shadow_scoring import classify_walk
from mef.uid import next_uid


@dataclass
class PaperScoringSummary:
    new_rows: list[dict[str, Any]]
    deferred: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    already_scored: int


def _existing_paper_uids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT rec_uid FROM mef.paper_score")
        return {row[0] for row in cur.fetchall()}


def _emitted_recs(conn) -> list[dict[str, Any]]:
    """Recs that reached the gate as approve/unavailable, joined to their
    candidate's run-date and feature snapshot. Excludes rejects (those
    never become recommendations) and any rec lacking stop/target/time_exit.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.uid             AS rec_uid,
                   r.candidate_uid   AS candidate_uid,
                   r.symbol          AS symbol,
                   r.asset_kind      AS asset_kind,
                   r.stop_level      AS stop_level,
                   r.target_level    AS target_level,
                   r.time_exit_date  AS time_exit_date,
                   c.feature_json    AS feature_json,
                   c.llm_gate_decision AS gate_decision,
                   d.started_at::date  AS run_date
              FROM mef.recommendation r
              JOIN mef.candidate     c ON c.uid = r.candidate_uid
              JOIN mef.daily_run     d ON d.uid = r.run_uid
             ORDER BY d.started_at, r.uid
            """
        )
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _forward_bars(symbol: str, asset_kind: str, *, entry_date: date, time_exit: date):
    table = "mart.stock_etf_daily" if asset_kind == "etf" else "mart.stock_equity_daily"
    sql = f"""
        SELECT bar_date, close
          FROM {table}
         WHERE symbol = %s
           AND bar_date > %s
           AND bar_date <= %s
         ORDER BY bar_date
    """
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol, entry_date, time_exit))
            return [(d, Decimal(str(c)) if c is not None else None) for d, c in cur.fetchall()]
    finally:
        conn.close()


def _score_one(conn, rec: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    feat = rec.get("feature_json") or {}
    close_raw = feat.get("close")
    stop = rec.get("stop_level")
    target = rec.get("target_level")
    time_exit = rec.get("time_exit_date")
    entry_date = rec.get("run_date")
    symbol = rec["symbol"]
    asset_kind = rec["asset_kind"]
    gate = rec.get("gate_decision") or "unknown"

    if close_raw is None or stop is None or target is None or time_exit is None or entry_date is None:
        return "skipped", {
            "rec_uid": rec["rec_uid"], "symbol": symbol,
            "reason": "missing close/stop/target/time_exit",
        }

    entry_price = Decimal(str(close_raw))
    stop_d = Decimal(str(stop))
    target_d = Decimal(str(target))

    bars = _forward_bars(symbol, asset_kind, entry_date=entry_date, time_exit=time_exit)
    outcome, exit_price, exit_date = classify_walk(
        bars, stop=stop_d, target=target_d, time_exit=time_exit, today=date.today(),
    )
    if outcome is None:
        return "deferred", {
            "rec_uid": rec["rec_uid"], "symbol": symbol,
            "reason": f"time_exit {time_exit.isoformat()} not yet elapsed and no breach observed",
        }

    sector = feat.get("sector")
    sector_etf = _SECTOR_TO_ETF.get(sector) if sector else None

    days_held = (exit_date - entry_date).days if (exit_price is not None and exit_date is not None) else None
    pnl_100sh = float((exit_price - entry_price) * 100) if exit_price is not None else None
    spy_ret, sector_ret = (None, None)
    if exit_price is not None and exit_date is not None:
        spy_ret, sector_ret = _spy_sector_returns(entry_date, exit_date, sector_etf)

    score_uid = next_uid(conn, "paper_score")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.paper_score (
                uid, rec_uid, candidate_uid, gate_decision, outcome,
                entry_price, exit_price, entry_date, exit_date, days_held,
                estimated_pnl_100_shares_usd,
                spy_return_same_window,
                sector_etf_symbol, sector_etf_return_same_window,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                score_uid, rec["rec_uid"], rec["candidate_uid"], gate, outcome,
                entry_price, exit_price, entry_date, exit_date, days_held,
                round(pnl_100sh, 2) if pnl_100sh is not None else None,
                spy_ret,
                sector_etf, sector_ret,
                ("no mart bars between entry+1 and time_exit"
                 if exit_price is None else None),
            ),
        )
    conn.commit()

    return "written", {
        "paper_score_uid": score_uid,
        "rec_uid":         rec["rec_uid"],
        "symbol":          symbol,
        "gate_decision":   gate,
        "outcome":         outcome,
        "entry_price":     float(entry_price),
        "exit_price":      float(exit_price) if exit_price is not None else None,
        "entry_date":      entry_date.isoformat(),
        "exit_date":       exit_date.isoformat() if exit_date else None,
        "days_held":       days_held,
        "pnl_100sh":       round(pnl_100sh, 2) if pnl_100sh is not None else None,
        "spy_window":      spy_ret,
        "sector_etf":      sector_etf,
        "sector_window":   sector_ret,
    }


def paper_score_emitted() -> PaperScoringSummary:
    """Write paper_score rows for any emitted rec that doesn't have one.

    Idempotent: skips recs with an existing paper_score row.
    Incremental: defers recs whose time_exit hasn't elapsed and haven't
    hit stop/target — they'll be scored in a later run.
    """
    conn = connect_mefdb()
    try:
        existing = _existing_paper_uids(conn)
        new_rows: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for rec in _emitted_recs(conn):
            if rec["rec_uid"] in existing:
                continue
            status, row = _score_one(conn, rec)
            if status == "written" and row is not None:
                new_rows.append(row)
            elif status == "deferred" and row is not None:
                deferred.append(row)
            elif status == "skipped" and row is not None:
                skipped.append(row)
        return PaperScoringSummary(
            new_rows=new_rows, deferred=deferred, skipped=skipped,
            already_scored=len(existing),
        )
    finally:
        conn.close()
