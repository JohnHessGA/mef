r"""Scoring for closed recommendations.

For every recommendation in state ``closed_win`` / ``closed_loss`` /
``closed_timeout`` we compute and persist one ``mef.score`` row containing:

- ``outcome`` — re-derived from the realized exit price vs. target/stop.
- ``entry_price`` — the matched holding's cost_basis_per_share.
- ``exit_price`` — last_price from the most recent ``position_snapshot``
  containing the symbol (since by definition the symbol disappeared from
  the latest snapshot).
- ``entry_date`` / ``exit_date`` / ``days_held``.
- ``estimated_pnl_100_shares_usd`` — ``(exit - entry) * 100``.
- ``spy_return_same_window`` — SPY total return between entry_date and exit_date.
- ``sector_etf_symbol`` + ``sector_etf_return_same_window`` — the matching
  XL\* sector ETF for the recommendation's sector (when one exists).

Scoring is idempotent — re-running ``score_all_pending`` only writes rows
for closed recs that don't yet have a ``mef.score`` row. If a score's
outcome disagrees with the recommendation's lifecycle state (e.g. lifecycle
saw timeout but the score-grade exit price actually closed above target),
the recommendation's ``state`` is updated to align — the score is the
authoritative outcome.

P&L uses the **estimated 100-share rule** described in
``docs/mef_design_spec.md`` §8 — ignores commissions, taxes, and the
user's actual share count. Real per-account P&L lands in a future
milestone via PHDB integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from mef.db.connection import connect_mefdb, connect_shdb
from mef.uid import next_uid


# Sector→ETF mapping lives in evidence.py so both the ranker's
# sector-relative signal and the post-hoc scoring benchmark share one
# source of truth.
from mef.evidence import SECTOR_TO_ETF as _SECTOR_TO_ETF  # noqa: E402


@dataclass
class ScoringSummary:
    new_rows: list[dict[str, Any]]      # newly written score rows
    skipped: list[dict[str, Any]]       # closed recs we couldn't score (missing data)
    already_scored: int                 # rec count with an existing score row


def _outcome(
    *, exit_price: Decimal | None, stop: Decimal | None, target: Decimal | None,
) -> str:
    if exit_price is not None:
        if target is not None and exit_price >= target:
            return "win"
        if stop is not None and exit_price <= stop:
            return "loss"
    return "timeout"


def _spy_sector_returns(
    entry_date: date,
    exit_date: date,
    sector_etf_symbol: str | None,
) -> tuple[float | None, float | None]:
    """Return (spy_window_return, sector_etf_window_return) over [entry, exit]."""
    symbols = ["SPY"]
    if sector_etf_symbol:
        symbols.append(sector_etf_symbol)

    sql = """
        SELECT symbol, bar_date, close
          FROM mart.stock_etf_daily
         WHERE symbol = ANY(%s)
           AND bar_date IN (
                 (SELECT max(bar_date) FROM mart.stock_etf_daily
                   WHERE symbol = ANY(%s) AND bar_date <= %s),
                 (SELECT max(bar_date) FROM mart.stock_etf_daily
                   WHERE symbol = ANY(%s) AND bar_date <= %s)
               )
    """
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (symbols, symbols, entry_date, symbols, exit_date))
            rows = cur.fetchall()
    finally:
        conn.close()

    closes: dict[str, dict[date, float]] = {}
    for sym, bar_date, close in rows:
        closes.setdefault(sym, {})[bar_date] = float(close) if close is not None else None

    def _ret(sym: str) -> float | None:
        bars = closes.get(sym, {})
        if not bars:
            return None
        on_or_before_entry = max((d for d in bars if d <= entry_date), default=None)
        on_or_before_exit = max((d for d in bars if d <= exit_date), default=None)
        if on_or_before_entry is None or on_or_before_exit is None:
            return None
        ep = bars[on_or_before_entry]
        xp = bars[on_or_before_exit]
        if ep is None or xp is None or ep == 0:
            return None
        return (xp / ep) - 1.0

    return _ret("SPY"), (_ret(sector_etf_symbol) if sector_etf_symbol else None)


def _last_known_price(conn, symbol: str) -> tuple[Decimal | None, date | None]:
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


def _matched_position(conn, position_uid: str | None) -> dict[str, Any] | None:
    if not position_uid:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cost_basis_per_share, as_of_date
              FROM mef.position_snapshot
             WHERE uid = %s
            """,
            (position_uid,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"entry_price": row[0], "entry_date": row[1]}


def _candidate_sector(conn, candidate_uid: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT feature_json->>'sector' FROM mef.candidate WHERE uid = %s",
            (candidate_uid,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _existing_score_uids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT rec_uid FROM mef.score")
        return {row[0] for row in cur.fetchall()}


def _closed_recs(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uid, candidate_uid, symbol, asset_kind,
                   stop_level, target_level, state,
                   active_match_position_uid
              FROM mef.recommendation
             WHERE state IN ('closed_win', 'closed_loss', 'closed_timeout')
             ORDER BY state_changed_at
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _align_state(conn, rec_uid: str, target_outcome: str, current_state: str) -> bool:
    """If the score's outcome differs from the rec's state, align the rec.

    Returns True if a state update happened.
    """
    target_state = f"closed_{target_outcome}"
    if target_state == current_state:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.recommendation
               SET state            = %s,
                   state_changed_at = now(),
                   state_changed_by = 'score',
                   updated_at       = now()
             WHERE uid = %s
            """,
            (target_state, rec_uid),
        )
    conn.commit()
    return True


def score_one(conn, rec: dict[str, Any]) -> dict[str, Any] | None:
    """Compute + write a score row for one closed rec. None if not scoreable."""
    matched = _matched_position(conn, rec.get("active_match_position_uid"))
    if not matched or matched["entry_price"] is None or matched["entry_date"] is None:
        return None

    entry_price: Decimal = Decimal(str(matched["entry_price"]))
    entry_date: date = matched["entry_date"]

    exit_price, exit_date = _last_known_price(conn, rec["symbol"])
    if exit_price is None or exit_date is None:
        return None
    exit_price = Decimal(str(exit_price))

    days_held = (exit_date - entry_date).days
    pnl_100sh = float((exit_price - entry_price) * 100)

    sector = _candidate_sector(conn, rec["candidate_uid"]) if rec.get("candidate_uid") else None
    sector_etf_symbol = _SECTOR_TO_ETF.get(sector) if sector else None
    spy_ret, sector_ret = _spy_sector_returns(entry_date, exit_date, sector_etf_symbol)

    outcome = _outcome(
        exit_price=exit_price, stop=rec.get("stop_level"), target=rec.get("target_level"),
    )

    score_uid = next_uid(conn, "score")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.score (
                uid, rec_uid, outcome,
                entry_price, exit_price, entry_date, exit_date, days_held,
                estimated_pnl_100_shares_usd,
                spy_return_same_window,
                sector_etf_symbol, sector_etf_return_same_window
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                score_uid, rec["uid"], outcome,
                entry_price, exit_price, entry_date, exit_date, days_held,
                round(pnl_100sh, 2),
                spy_ret,
                sector_etf_symbol, sector_ret,
            ),
        )
    conn.commit()

    state_aligned = _align_state(conn, rec["uid"], outcome, rec["state"])

    return {
        "score_uid":     score_uid,
        "rec_uid":       rec["uid"],
        "symbol":        rec["symbol"],
        "outcome":       outcome,
        "entry_price":   float(entry_price),
        "exit_price":    float(exit_price),
        "entry_date":    entry_date.isoformat(),
        "exit_date":     exit_date.isoformat(),
        "days_held":     days_held,
        "pnl_100sh":     round(pnl_100sh, 2),
        "spy_window":    spy_ret,
        "sector_etf":   sector_etf_symbol,
        "sector_window": sector_ret,
        "state_aligned": state_aligned,
    }


def score_all_pending() -> ScoringSummary:
    """Write score rows for any closed rec that doesn't have one. Idempotent."""
    conn = connect_mefdb()
    try:
        existing = _existing_score_uids(conn)
        new_rows: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for rec in _closed_recs(conn):
            if rec["uid"] in existing:
                continue
            written = score_one(conn, rec)
            if written is None:
                skipped.append({
                    "rec_uid": rec["uid"], "symbol": rec["symbol"],
                    "reason":  "no matched position or no last known price",
                })
            else:
                new_rows.append(written)
        return ScoringSummary(
            new_rows=new_rows, skipped=skipped, already_scored=len(existing),
        )
    finally:
        conn.close()
