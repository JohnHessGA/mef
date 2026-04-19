"""Pull per-symbol evidence for the MEF universe from SHDB.

v0 evidence set (small on purpose):

- close, return_20d, return_63d
- sma_20 / sma_50 / sma_200 (and derived trend_above_sma50 / trend_above_sma200)
- rsi_14, macd_histogram
- realized_vol_20d
- drawdown_current
- volume_z_score
- sector (stocks only)
- spy-relative 20-day return

Both ``mart.stock_equity_daily`` and ``mart.stock_etf_daily`` carry these
columns. We pull the latest ``bar_date`` per symbol, filtered by the MEF
universe list stored in MEFDB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from mef.db.connection import connect_mefdb, connect_shdb


@dataclass(frozen=True)
class EvidenceBundle:
    as_of_date: date
    baseline: dict[str, Any]               # {"spy_return_20d": ..., "spy_return_63d": ...}
    symbols: dict[str, dict[str, Any]]     # {"AAPL": {...features...}, ...}


def _fetch_universe_symbols() -> tuple[list[str], list[str]]:
    """Return (stock_symbols, etf_symbols) from MEFDB."""
    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM mef.universe_stock ORDER BY symbol")
            stocks = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT symbol FROM mef.universe_etf ORDER BY symbol")
            etfs = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    return stocks, etfs


_EQUITY_SQL = """
SELECT DISTINCT ON (symbol)
    symbol, bar_date, sector, close,
    return_20d, return_63d,
    sma_20, sma_50, sma_200,
    rsi_14, macd_histogram,
    realized_vol_20d,
    drawdown_current,
    volume_z_score
FROM mart.stock_equity_daily
WHERE symbol = ANY(%s)
ORDER BY symbol, bar_date DESC
"""

_ETF_SQL = """
SELECT DISTINCT ON (symbol)
    symbol, bar_date, close,
    return_20d, return_63d,
    sma_20, sma_50, sma_200,
    rsi_14, macd_histogram,
    realized_vol_20d,
    drawdown_current,
    volume_z_score
FROM mart.stock_etf_daily
WHERE symbol = ANY(%s)
ORDER BY symbol, bar_date DESC
"""


def _derive_trend_flags(row: dict[str, Any]) -> None:
    """Attach trend_above_sma50 / trend_above_sma200 based on close and SMA values."""
    close = row.get("close")
    row["trend_above_sma50"] = (
        close is not None and row.get("sma_50") is not None and close > row["sma_50"]
    )
    row["trend_above_sma200"] = (
        close is not None and row.get("sma_200") is not None and close > row["sma_200"]
    )


def _rows_to_dict(cur, asset_kind: str) -> dict[str, dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    out: dict[str, dict[str, Any]] = {}
    for raw in cur.fetchall():
        row = dict(zip(cols, raw))
        row["asset_kind"] = asset_kind
        _derive_trend_flags(row)
        out[row["symbol"]] = row
    return out


def pull_latest_evidence() -> EvidenceBundle:
    """Pull the latest-bar evidence for every universe symbol with coverage.

    Symbols that have no row in the mart table are simply absent from the
    returned bundle. Callers treat "no evidence" as ``no_edge``.
    """
    stock_symbols, etf_symbols = _fetch_universe_symbols()

    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(_EQUITY_SQL, (stock_symbols,))
            stocks = _rows_to_dict(cur, "stock")
            cur.execute(_ETF_SQL, (etf_symbols,))
            etfs = _rows_to_dict(cur, "etf")
    finally:
        conn.close()

    symbols = {**stocks, **etfs}

    # Latest bar_date across both asset kinds.
    dates = [r["bar_date"] for r in symbols.values() if r.get("bar_date") is not None]
    as_of = max(dates) if dates else date.today()

    # SPY baseline: 20d / 63d return, taken directly from the ETF feature row.
    spy_row = etfs.get("SPY", {})
    baseline = {
        "spy_return_20d": spy_row.get("return_20d"),
        "spy_return_63d": spy_row.get("return_63d"),
    }

    return EvidenceBundle(as_of_date=as_of, baseline=baseline, symbols=symbols)
