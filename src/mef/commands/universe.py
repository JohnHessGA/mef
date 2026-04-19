"""`mef universe` — show or reload the 305-stock + 15-ETF universe.

Subcommands (dispatched via the ``action`` positional argument):

- ``show`` — print the current state of ``mef.universe_stock`` and ``mef.universe_etf``.
- ``load`` — parse the notes files and upsert their contents into MEFDB.
"""

from __future__ import annotations

from collections import Counter

from mef.config import load_app_config
from mef.universe_loader import (
    fetch_universe_etfs,
    fetch_universe_stocks,
    load_universe_etfs,
    load_universe_stocks,
    universe_counts,
)


def _run_load(args) -> int:
    cfg = load_app_config()
    universe_cfg = cfg.get("universe") or {}

    stocks_path = universe_cfg.get("stocks_notes_path", "notes/focus-universe-us-stocks-final.md")
    etfs_path = universe_cfg.get("etfs_notes_path", "notes/core-us-etfs-daily-final.md")

    print(f"Loading stocks from {stocks_path} ...")
    n_stocks = load_universe_stocks(stocks_path)
    print(f"  upserted {n_stocks} stock rows into mef.universe_stock")

    print(f"Loading ETFs from {etfs_path} ...")
    n_etfs = load_universe_etfs(etfs_path)
    print(f"  upserted {n_etfs} ETF rows into mef.universe_etf")

    counts = universe_counts()
    print()
    print(f"Current totals: stocks={counts['stocks']} etfs={counts['etfs']}")
    return 0


def _run_show(args) -> int:
    counts = universe_counts()
    print("MEF universe")
    print("============")
    print(f"stocks: {counts['stocks']} rows in mef.universe_stock")
    print(f"etfs:   {counts['etfs']} rows in mef.universe_etf")
    print()

    if counts["etfs"]:
        print("ETFs by role:")
        etfs = fetch_universe_etfs()
        for etf in etfs:
            print(f"  {etf['symbol']:<6} {etf['role']:<14} {etf['description']}")
        print()

    if counts["stocks"]:
        stocks = fetch_universe_stocks()
        sector_counter: Counter[str] = Counter(
            (s["sector"] or "Unknown") for s in stocks
        )
        print("Stocks by sector:")
        for sector, n in sector_counter.most_common():
            print(f"  {sector:<26} {n:>4}")
        print()

    return 0


def run(args) -> int:
    action = getattr(args, "action", "show")
    if action == "load":
        return _run_load(args)
    return _run_show(args)
