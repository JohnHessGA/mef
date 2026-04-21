"""Shadow scoring for LLM-rejected candidates.

For every candidate where ``llm_gate_decision = 'reject'``, we
forward-simulate the trade that *would* have been emitted, using:

- entry_price = the candidate's ``feature_json->>'close'`` (same anchor
  real recs use as their entry mid in ``run_pipeline._estimated_pnl``)
- entry_date  = the parent ``daily_run.started_at::date``
- stop / target / time_exit = the values stamped on ``mef.candidate``
- forward walk over ``mart.stock_*_daily`` close prices

Outcome (matches ``mef.scoring._outcome`` for apples-to-apples):

  - win       — first close on or after entry_date+1 with close >= target
  - loss      — first close on or after entry_date+1 with close <= stop
  - timeout   — neither bound was crossed by the time we reach
                ``proposed_time_exit``; exit at the last available bar
                on or before time_exit

Scoring is deferred when the candidate is "still live" — i.e., neither
stop/target was hit yet and ``proposed_time_exit`` hasn't passed. Those
candidates are picked up automatically in a future run once enough data
has accrued. This makes the function idempotent and incremental.

Why this exists: without it, the LLM gate is unfalsifiable. Logging a
rejection is not enough — we need to know whether the rejection was
right. Comparing the outcome distribution of approved (``mef.score``)
vs rejected (``mef.shadow_score``) tells us if the gate is helping.

NOT backtesting: a backtest simulates a strategy over arbitrary history.
Shadow scoring only evaluates live decisions made by MEF (rejected at
time T) against subsequently-realized prices — same forward-test
discipline real recs use, just keyed on candidate_uid instead of rec_uid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from mef.db.connection import connect_mefdb, connect_shdb
from mef.scoring import _SECTOR_TO_ETF, _spy_sector_returns
from mef.uid import next_uid


@dataclass
class ShadowScoringSummary:
    new_rows: list[dict[str, Any]]      # newly written shadow_score rows
    deferred: list[dict[str, Any]]      # rejects we couldn't settle yet (time_exit in the future, no breach)
    skipped: list[dict[str, Any]]       # rejects we can't ever score (missing stop/target/time_exit/close)
    already_scored: int                 # candidate count with an existing shadow_score row


def _existing_shadow_uids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT candidate_uid FROM mef.shadow_score")
        return {row[0] for row in cur.fetchall()}


def _rejected_candidates(conn) -> list[dict[str, Any]]:
    """Return rejected candidates joined to their parent run's start date."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.uid, c.symbol, c.asset_kind, c.engine,
                   c.proposed_stop, c.proposed_target, c.proposed_time_exit,
                   c.feature_json,
                   c.llm_gate_decision,
                   d.started_at::date AS run_date
              FROM mef.candidate c
              JOIN mef.daily_run  d ON d.uid = c.run_uid
             WHERE c.llm_gate_decision = 'reject'
             ORDER BY d.started_at
            """
        )
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def classify_walk(
    bars: list[tuple[date, Decimal | None]],
    *,
    stop: Decimal,
    target: Decimal,
    time_exit: date,
    today: date,
) -> tuple[str | None, Decimal | None, date | None]:
    """Pure classifier — no DB. Given the close series the symbol traded
    at after the entry date, decide ``(outcome, exit_price, exit_date)``.

    Returns ``outcome=None`` to mean "defer — not enough time has passed
    AND no stop/target breach was observed". This is the only path that
    leaves the candidate un-scored.
    """
    if not bars:
        if time_exit <= today:
            return "timeout", None, None
        return None, None, None

    last_close: Decimal | None = None
    last_date: date | None = None
    for bar_date, close in bars:
        if close is None:
            continue
        last_close, last_date = close, bar_date
        if close >= target:
            return "win", close, bar_date
        if close <= stop:
            return "loss", close, bar_date

    if last_date is not None and last_date >= time_exit:
        return "timeout", last_close, last_date
    if time_exit <= today:
        return "timeout", last_close, last_date
    return None, None, None


def _forward_walk(
    symbol: str,
    asset_kind: str,
    *,
    entry_date: date,
    stop: Decimal,
    target: Decimal,
    time_exit: date,
) -> tuple[str | None, Decimal | None, date | None]:
    """Fetch the daily closes after entry_date and classify them."""
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
            bars = [(d, Decimal(str(c)) if c is not None else None) for d, c in cur.fetchall()]
    finally:
        conn.close()
    return classify_walk(bars, stop=stop, target=target, time_exit=time_exit, today=date.today())


def _score_one(conn, cand: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Score one rejected candidate. Returns ('written'|'deferred'|'skipped', row|None)."""
    feat = cand.get("feature_json") or {}
    close_raw = feat.get("close")
    stop = cand.get("proposed_stop")
    target = cand.get("proposed_target")
    time_exit = cand.get("proposed_time_exit")
    entry_date = cand.get("run_date")
    symbol = cand["symbol"]
    asset_kind = cand["asset_kind"]

    if close_raw is None or stop is None or target is None or time_exit is None or entry_date is None:
        return "skipped", {
            "candidate_uid": cand["uid"], "symbol": symbol,
            "reason": "missing close/stop/target/time_exit",
        }

    entry_price = Decimal(str(close_raw))
    stop_d = Decimal(str(stop))
    target_d = Decimal(str(target))

    outcome, exit_price, exit_date = _forward_walk(
        symbol, asset_kind,
        entry_date=entry_date, stop=stop_d, target=target_d, time_exit=time_exit,
    )
    if outcome is None:
        return "deferred", {
            "candidate_uid": cand["uid"], "symbol": symbol,
            "reason": f"time_exit {time_exit.isoformat()} not yet elapsed and no breach observed",
        }
    if exit_price is None or exit_date is None:
        # Can happen if the symbol has zero bars between entry+1 and time_exit AND
        # time_exit is in the past — we still record a timeout but with NULL exit.
        sector = feat.get("sector")
        sector_etf = _SECTOR_TO_ETF.get(sector) if sector else None
        score_uid = next_uid(conn, "shadow_score")
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mef.shadow_score (
                    uid, candidate_uid, gate_decision, outcome,
                    entry_price, exit_price, entry_date, exit_date, days_held,
                    estimated_pnl_100_shares_usd,
                    spy_return_same_window,
                    sector_etf_symbol, sector_etf_return_same_window,
                    notes, engine
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    score_uid, cand["uid"], cand["llm_gate_decision"], "timeout",
                    entry_price, None, entry_date, None, None,
                    None, None, sector_etf, None,
                    "no mart bars between entry+1 and time_exit",
                    cand.get("engine"),
                ),
            )
        conn.commit()
        return "written", {
            "shadow_score_uid": score_uid, "candidate_uid": cand["uid"],
            "symbol": symbol, "outcome": "timeout",
            "entry_price": float(entry_price),
        }

    days_held = (exit_date - entry_date).days
    pnl_100sh = float((exit_price - entry_price) * 100)
    sector = feat.get("sector")
    sector_etf = _SECTOR_TO_ETF.get(sector) if sector else None
    spy_ret, sector_ret = _spy_sector_returns(entry_date, exit_date, sector_etf)

    score_uid = next_uid(conn, "shadow_score")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.shadow_score (
                uid, candidate_uid, gate_decision, outcome,
                entry_price, exit_price, entry_date, exit_date, days_held,
                estimated_pnl_100_shares_usd,
                spy_return_same_window,
                sector_etf_symbol, sector_etf_return_same_window,
                engine
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                score_uid, cand["uid"], cand["llm_gate_decision"], outcome,
                entry_price, exit_price, entry_date, exit_date, days_held,
                round(pnl_100sh, 2),
                spy_ret,
                sector_etf, sector_ret,
                cand.get("engine"),
            ),
        )
    conn.commit()

    return "written", {
        "shadow_score_uid": score_uid,
        "candidate_uid":    cand["uid"],
        "symbol":           symbol,
        "outcome":          outcome,
        "entry_price":      float(entry_price),
        "exit_price":       float(exit_price),
        "entry_date":       entry_date.isoformat(),
        "exit_date":        exit_date.isoformat(),
        "days_held":        days_held,
        "pnl_100sh":        round(pnl_100sh, 2),
        "spy_window":       spy_ret,
        "sector_etf":       sector_etf,
        "sector_window":    sector_ret,
    }


def shadow_score_rejected() -> ShadowScoringSummary:
    """Write shadow_score rows for any rejected candidate that doesn't have one.

    Idempotent: skips candidates with an existing shadow_score row.
    Incremental: skips candidates whose time_exit hasn't passed and
    haven't hit stop/target yet — they'll be scored in a later run.
    """
    conn = connect_mefdb()
    try:
        existing = _existing_shadow_uids(conn)
        new_rows: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for cand in _rejected_candidates(conn):
            if cand["uid"] in existing:
                continue
            status, row = _score_one(conn, cand)
            if status == "written" and row is not None:
                new_rows.append(row)
            elif status == "deferred" and row is not None:
                deferred.append(row)
            elif status == "skipped" and row is not None:
                skipped.append(row)
        return ShadowScoringSummary(
            new_rows=new_rows, deferred=deferred, skipped=skipped,
            already_scored=len(existing),
        )
    finally:
        conn.close()
