"""Daily mark-to-market P&L tracking for active recommendations.

Writes one row per (rec_uid, today) into ``mef.recommendation_pnl_daily``
for every rec currently in state ``active``. Also writes a close-day row
(is_close_day=TRUE) for any rec that transitioned to a closed state in
this run, so the series has a clean endpoint.

Source of truth for price: the **latest** ``mef.position_snapshot`` row
for the rec's symbol (any import batch). That's typically last night's
Fidelity CSV, which carries the end-of-day mark. Fallback is the latest
close in mart.stock_*_daily when no position snapshot is available for
the symbol (rare — usually means the user sold but we never reimported).

Idempotent: ON CONFLICT (rec_uid, as_of_date) DO UPDATE. Safe to re-run
the daily sweep mid-day or retry on failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from mef.db.connection import connect_mefdb, connect_shdb


@dataclass
class PnlSnapshotSummary:
    active_written: list[dict[str, Any]]        # per-rec rows just written for active recs
    close_day_written: list[dict[str, Any]]     # per-rec rows written for newly-closed recs
    skipped: list[dict[str, Any]]               # recs we couldn't price today


def compute_mtm(
    *,
    quantity: Decimal | None,
    cost_basis_per_share: Decimal | None,
    last_price: Decimal | None,
) -> dict[str, Any]:
    """Pure: MTM math from the three inputs. Any NULL → the derived
    values are NULL rather than zero — "we don't know" ≠ "it's flat"."""
    out: dict[str, Any] = {
        "market_value": None,
        "unrealized_pnl_usd": None,
        "unrealized_pnl_pct": None,
    }
    if quantity is None or last_price is None:
        return out
    out["market_value"] = round(float(quantity * last_price), 2)
    if cost_basis_per_share is None or cost_basis_per_share == 0:
        return out
    out["unrealized_pnl_usd"] = round(float((last_price - cost_basis_per_share) * quantity), 2)
    out["unrealized_pnl_pct"] = round(float((last_price - cost_basis_per_share) / cost_basis_per_share), 6)
    return out


def _active_recs(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uid, symbol, asset_kind, active_match_position_uid,
                   state_changed_at::date AS activated_date
              FROM mef.recommendation
             WHERE state = 'active'
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _just_closed_recs(conn) -> list[dict[str, Any]]:
    """Recs in a closed state that don't yet have a close-day row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.uid, r.symbol, r.asset_kind,
                   r.active_match_position_uid,
                   r.state_changed_at::date AS closed_date
              FROM mef.recommendation r
              LEFT JOIN mef.recommendation_pnl_daily p
                     ON p.rec_uid = r.uid AND p.is_close_day = TRUE
             WHERE r.state IN ('closed_win','closed_loss','closed_timeout')
               AND p.rec_uid IS NULL
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _latest_snapshot_for_symbol(conn, symbol: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uid, quantity, cost_basis_per_share, last_price, as_of_date
              FROM mef.position_snapshot
             WHERE symbol = %s
             ORDER BY as_of_date DESC NULLS LAST, position_id DESC
             LIMIT 1
            """,
            (symbol,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "uid": row[0], "quantity": row[1], "cost_basis_per_share": row[2],
        "last_price": row[3], "as_of_date": row[4],
    }


def _mart_close(symbol: str, asset_kind: str) -> tuple[Decimal | None, date | None]:
    table = "mart.stock_etf_daily" if asset_kind == "etf" else "mart.stock_equity_daily"
    sql = f"""
        SELECT bar_date, close
          FROM {table}
         WHERE symbol = %s
         ORDER BY bar_date DESC
         LIMIT 1
    """
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None, None
    return Decimal(str(row[1])) if row[1] is not None else None, row[0]


def _write_pnl_row(
    conn,
    *,
    rec_uid: str,
    as_of_date: date,
    quantity: Decimal | None,
    cost_basis_per_share: Decimal | None,
    last_price: Decimal | None,
    days_held_so_far: int | None,
    is_close_day: bool,
    price_source: str,
    notes: str | None = None,
) -> dict[str, Any]:
    mtm = compute_mtm(
        quantity=quantity,
        cost_basis_per_share=cost_basis_per_share,
        last_price=last_price,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.recommendation_pnl_daily (
                rec_uid, as_of_date, quantity, cost_basis_per_share, last_price,
                market_value, unrealized_pnl_usd, unrealized_pnl_pct,
                days_held_so_far, is_close_day, price_source, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (rec_uid, as_of_date) DO UPDATE SET
                quantity             = EXCLUDED.quantity,
                cost_basis_per_share = EXCLUDED.cost_basis_per_share,
                last_price           = EXCLUDED.last_price,
                market_value         = EXCLUDED.market_value,
                unrealized_pnl_usd   = EXCLUDED.unrealized_pnl_usd,
                unrealized_pnl_pct   = EXCLUDED.unrealized_pnl_pct,
                days_held_so_far     = EXCLUDED.days_held_so_far,
                is_close_day         = EXCLUDED.is_close_day OR mef.recommendation_pnl_daily.is_close_day,
                price_source         = EXCLUDED.price_source,
                notes                = EXCLUDED.notes
            """,
            (
                rec_uid, as_of_date,
                quantity, cost_basis_per_share, last_price,
                mtm["market_value"], mtm["unrealized_pnl_usd"], mtm["unrealized_pnl_pct"],
                days_held_so_far, is_close_day, price_source, notes,
            ),
        )
    conn.commit()
    return {
        "rec_uid": rec_uid, "as_of_date": as_of_date.isoformat(),
        "quantity": float(quantity) if quantity is not None else None,
        "last_price": float(last_price) if last_price is not None else None,
        **mtm,
        "days_held_so_far": days_held_so_far,
        "is_close_day": is_close_day,
        "price_source": price_source,
    }


def _snapshot_for_rec(
    conn,
    rec: dict[str, Any],
    *,
    as_of_date: date,
    is_close_day: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve price + qty + cost_basis for one rec, write the row.

    Returns (written_row, skip_reason) — exactly one is non-None.
    """
    sym = rec["symbol"]
    snap = _latest_snapshot_for_symbol(conn, sym)
    start_date = rec.get("activated_date") or rec.get("closed_date")
    days_held = (as_of_date - start_date).days if start_date else None

    if snap and snap.get("last_price") is not None:
        written = _write_pnl_row(
            conn,
            rec_uid=rec["uid"],
            as_of_date=as_of_date,
            quantity=Decimal(str(snap["quantity"])) if snap.get("quantity") is not None else None,
            cost_basis_per_share=(
                Decimal(str(snap["cost_basis_per_share"]))
                if snap.get("cost_basis_per_share") is not None else None
            ),
            last_price=Decimal(str(snap["last_price"])),
            days_held_so_far=days_held,
            is_close_day=is_close_day,
            price_source="position_snapshot",
            notes=(f"from position_snapshot as_of={snap['as_of_date']}"
                   if snap.get("as_of_date") else None),
        )
        return written, None

    mart_close, mart_date = _mart_close(sym, rec.get("asset_kind") or "stock")
    if mart_close is not None:
        written = _write_pnl_row(
            conn,
            rec_uid=rec["uid"],
            as_of_date=as_of_date,
            quantity=None,                                    # no holding — mark-only
            cost_basis_per_share=None,
            last_price=mart_close,
            days_held_so_far=days_held,
            is_close_day=is_close_day,
            price_source="mart",
            notes=(f"no position_snapshot for {sym}; mart bar_date={mart_date}"
                   if mart_date else None),
        )
        return written, None

    return None, {
        "rec_uid": rec["uid"], "symbol": sym,
        "reason": f"no position_snapshot and no mart price for {sym}",
    }


def snapshot_daily_pnl(*, as_of_date: date | None = None) -> PnlSnapshotSummary:
    """Write today's MTM row for every active rec + close-day rows for newly closed ones.

    ``as_of_date`` defaults to today; tests inject a fixed date for stability.
    """
    as_of = as_of_date or date.today()
    conn = connect_mefdb()
    try:
        active = _active_recs(conn)
        just_closed = _just_closed_recs(conn)
        active_written: list[dict[str, Any]] = []
        close_day_written: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for rec in active:
            row, skip = _snapshot_for_rec(conn, rec, as_of_date=as_of, is_close_day=False)
            if row is not None:
                active_written.append(row)
            elif skip is not None:
                skipped.append(skip)
        for rec in just_closed:
            # Close-day row gets stamped at the rec's state_changed_at::date, not "today",
            # so the time series lines up with the close event.
            close_date = rec.get("closed_date") or as_of
            row, skip = _snapshot_for_rec(conn, rec, as_of_date=close_date, is_close_day=True)
            if row is not None:
                close_day_written.append(row)
            elif skip is not None:
                skipped.append(skip)
        return PnlSnapshotSummary(
            active_written=active_written,
            close_day_written=close_day_written,
            skipped=skipped,
        )
    finally:
        conn.close()
