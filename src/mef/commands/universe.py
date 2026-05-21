"""`mef universe` — show the Job 1 (305 stocks + 20 ETFs) universe state.

The universe lives in MEFDB (``mef.universe_stock`` / ``mef.universe_etf``)
and is seeded by SQL migrations under ``sql/mefdb/``. This command is
read-only — there is no longer a markdown loader to invoke.
"""

from __future__ import annotations

import sys
from collections import Counter

from mef.universe_loader import (
    fetch_universe_etfs,
    fetch_universe_stocks,
    universe_counts,
)


def _run_show() -> int:
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
        print(
            "mef universe load: removed — universe data now lives in MEFDB.\n"
            "  Apply migrations with `mef init-db` (idempotent).\n"
            "  Edit rows directly in mef.universe_stock / mef.universe_etf for ad-hoc changes.",
            file=sys.stderr,
        )
        return 2
    return _run_show()
