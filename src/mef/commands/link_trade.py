"""`mef link-trade <rec-uid>` — record the actual buy/sell for a scored rec.

The score row carries synthetic 100-share estimated P&L by default.
This command layers your real trade data on top: realized_qty, actual
buy/sell prices and dates, computed realized_pnl_usd, and the headline
``realized_pnl_per_day`` metric.

Sell fields are optional — you can link a trade while still holding
and come back with --sell-price / --sell-date once you close. Re-running
the command on the same rec_uid re-writes the same row (idempotent).

Until PHDB has Fidelity transaction history, this is the manual bridge
between MEF's recommendations and your actual account outcomes.
"""

from __future__ import annotations

import sys
from datetime import date as date_cls, datetime
from decimal import Decimal

from mef.db.connection import connect_mefdb


def _parse_date(s: str | None, label: str) -> date_cls | None:
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        print(f"mef link-trade: --{label} must be YYYY-MM-DD, got {s!r}", file=sys.stderr)
        raise SystemExit(2)


def run(args) -> int:
    rec_uid = args.rec_uid
    qty = Decimal(str(args.qty))
    buy_price = Decimal(str(args.buy_price))
    buy_date = _parse_date(args.buy_date, "buy-date")
    sell_price = Decimal(str(args.sell_price)) if args.sell_price is not None else None
    sell_date = _parse_date(args.sell_date, "sell-date")

    if qty <= 0:
        print(f"mef link-trade: --qty must be > 0, got {qty}", file=sys.stderr)
        return 2
    if buy_price <= 0 or (sell_price is not None and sell_price <= 0):
        print("mef link-trade: prices must be > 0", file=sys.stderr)
        return 2

    realized_pnl_usd = None
    realized_pnl_per_day = None
    if sell_price is not None:
        realized_pnl_usd = float((sell_price - buy_price) * qty)
        if sell_date is not None and buy_date is not None:
            days = max((sell_date - buy_date).days, 1)
            realized_pnl_per_day = round(realized_pnl_usd / days, 4)
        realized_pnl_usd = round(realized_pnl_usd, 2)

    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE mef.score
                   SET realized_qty         = %s,
                       realized_buy_price   = %s,
                       realized_buy_date    = %s,
                       realized_sell_price  = %s,
                       realized_sell_date   = %s,
                       realized_pnl_usd     = %s,
                       realized_pnl_per_day = %s
                 WHERE rec_uid = %s
                 RETURNING uid, rec_uid
                """,
                (
                    qty, buy_price, buy_date, sell_price, sell_date,
                    realized_pnl_usd, realized_pnl_per_day, rec_uid,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if row is None:
        print(
            f"mef link-trade: no mef.score row found for rec_uid={rec_uid}. "
            "A score row is created only after the rec closes — run `mef score` first.",
            file=sys.stderr,
        )
        return 2

    score_uid, _ = row
    print(f"Linked real trade to score {score_uid} (rec_uid={rec_uid}):")
    print(f"  qty:         {qty}")
    print(f"  buy:         ${buy_price} on {buy_date}")
    if sell_price is not None:
        print(f"  sell:        ${sell_price}" + (f" on {sell_date}" if sell_date else ""))
        print(f"  realized P&L: ${realized_pnl_usd:,.2f}")
        if realized_pnl_per_day is not None:
            print(f"  P&L / day:   ${realized_pnl_per_day:,.4f}")
    else:
        print("  sell:        (still holding)")
    return 0
