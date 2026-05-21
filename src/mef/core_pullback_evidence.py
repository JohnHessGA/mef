"""SHDB evidence for the Job 2 pullback engine — scoped to a small symbol set.

Returns a plain dict keyed by symbol so the deterministic engine in
``mef.core_pullback`` can be a pure function over (evidence_row, tier).

Why a dedicated reader instead of reusing ``mef.evidence.pull_latest_evidence``:
the existing puller pulls every column for all 325 Job 1 symbols. Job 2
needs only 60 symbols and a smaller column set, and ``mef status`` should
stay snappy.

Two queries:

1. **Latest-bar query** — the most recent bar per symbol with the
   pullback-relevant features. Uses the same CTE-then-join pattern as
   ``mef.evidence`` to dodge the TimescaleDB ``DISTINCT ON`` planner
   pitfall it documents.

2. **63-day high query** — ``MAX(high)`` over the most recent ~90
   calendar days (≈ 63 trading days) per symbol. SHDB does not
   materialize a ``high_63d`` column; we compute it on the fly because
   the alternative — using the 252-day peak for every buy-level
   calculation — would render starter/better levels meaningless when a
   stock has been steadily climbing for a year.

Stocks and ETFs are pulled separately because they live in different
mart tables with non-identical column sets (no ``sector`` / ``next_earnings_date``
on ETFs).

If SHDB returns nothing for a symbol (very new listing, or harvest gap),
the row is simply absent from the result. The engine treats absence as
"no evidence" and degrades to ``NO_PULLBACK`` with a missing-data caution.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mef.db.connection import connect_shdb


# Approximate trading-day window for high_63d. 90 calendar days covers
# 63 trading days even with US holidays/weekends in the worst case.
_HIGH_63D_LOOKBACK_DAYS = 90


_EQUITY_LATEST_SQL = """
WITH latest AS (
    SELECT symbol, MAX(bar_date) AS bar_date
      FROM mart.stock_equity_daily
     WHERE symbol = ANY(%s)
     GROUP BY symbol
)
SELECT  sed.symbol, sed.bar_date, sed.close, sed.high,
        sed.sma_50, sed.sma_200, sed.sma_50_slope, sed.sma_20_slope,
        sed.return_5d, sed.return_20d, sed.return_63d,
        sed.return_126d, sed.return_252d,
        sed.rsi_14, sed.macd_histogram,
        sed.atr_14, sed.realized_vol_20d, sed.realized_vol_63d,
        sed.drawdown_current, sed.drawdown_max_252d, sed.peak_date,
        sed.next_earnings_date
  FROM mart.stock_equity_daily sed
  JOIN latest l
    ON l.symbol = sed.symbol
   AND l.bar_date = sed.bar_date
"""


_ETF_LATEST_SQL = """
WITH latest AS (
    SELECT symbol, MAX(bar_date) AS bar_date
      FROM mart.stock_etf_daily
     WHERE symbol = ANY(%s)
     GROUP BY symbol
)
SELECT  sed.symbol, sed.bar_date, sed.close, sed.high,
        sed.sma_50, sed.sma_200,
        sed.return_5d, sed.return_20d, sed.return_63d,
        sed.return_126d, sed.return_252d,
        sed.rsi_14, sed.macd_histogram,
        sed.atr_14, sed.realized_vol_20d, sed.realized_vol_63d,
        sed.drawdown_current, sed.drawdown_max_252d, sed.peak_date
  FROM mart.stock_etf_daily sed
  JOIN latest l
    ON l.symbol = sed.symbol
   AND l.bar_date = sed.bar_date
"""
# Note: mart.stock_etf_daily has no sma_50_slope / sma_20_slope columns.
# The engine treats missing slope as None and degrades trend judgment to
# close-vs-SMA + return-based rules only — which is fine for the ETF tier.


# Trailing 63-trading-day high per symbol. Use bar_date >= (today - 90d)
# in the mart so we don't load decades of history. Per-symbol because
# the engine compares each symbol's close against its OWN trailing high.
_HIGH_63D_SQL = """
SELECT symbol, MAX(high) AS high_63d
  FROM {table}
 WHERE symbol = ANY(%s)
   AND bar_date >= (CURRENT_DATE - INTERVAL '{days} day')
 GROUP BY symbol
"""


def _fetch_rows(conn, sql: str, symbols: list[str]) -> list[dict[str, Any]]:
    """Run ``sql`` with ``symbols`` and return RealDict-style rows."""
    if not symbols:
        return []
    with conn.cursor() as cur:
        cur.execute(sql, (symbols,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_pullback_evidence(symbols_by_kind: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    """Pull pullback evidence for the given symbols.

    ``symbols_by_kind`` is a mapping like ``{"stock": [...], "etf": [...]}``.

    Returns ``{symbol: row}`` where each row is a dict with the latest-bar
    columns plus a derived ``high_63d`` (or None) and an injected
    ``asset_kind``. Symbols absent from SHDB are absent from the result.
    """
    stock_syms = list(symbols_by_kind.get("stock", []))
    etf_syms = list(symbols_by_kind.get("etf", []))
    if not stock_syms and not etf_syms:
        return {}

    out: dict[str, dict[str, Any]] = {}
    conn = connect_shdb()
    try:
        # Latest-bar features — stocks
        for raw in _fetch_rows(conn, _EQUITY_LATEST_SQL, stock_syms):
            raw["asset_kind"] = "stock"
            out[raw["symbol"]] = raw

        # Latest-bar features — ETFs (no next_earnings_date column)
        for raw in _fetch_rows(conn, _ETF_LATEST_SQL, etf_syms):
            raw["asset_kind"] = "etf"
            raw["next_earnings_date"] = None
            out[raw["symbol"]] = raw

        # 63-trading-day high — stocks
        if stock_syms:
            sql = _HIGH_63D_SQL.format(
                table="mart.stock_equity_daily", days=_HIGH_63D_LOOKBACK_DAYS,
            )
            for r in _fetch_rows(conn, sql, stock_syms):
                if r["symbol"] in out:
                    out[r["symbol"]]["high_63d"] = (
                        float(r["high_63d"]) if r["high_63d"] is not None else None
                    )

        # 63-trading-day high — ETFs
        if etf_syms:
            sql = _HIGH_63D_SQL.format(
                table="mart.stock_etf_daily", days=_HIGH_63D_LOOKBACK_DAYS,
            )
            for r in _fetch_rows(conn, sql, etf_syms):
                if r["symbol"] in out:
                    out[r["symbol"]]["high_63d"] = (
                        float(r["high_63d"]) if r["high_63d"] is not None else None
                    )
    finally:
        conn.close()

    # Normalise: make sure every returned row has the optional fields
    # present (as None) so the engine never has to hasattr-check.
    for row in out.values():
        row.setdefault("high_63d", None)
    return out


def latest_bar_date(symbols: list[str]) -> date | None:
    """Return the freshest bar_date across the requested symbols."""
    if not symbols:
        return None
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT GREATEST(
                    (SELECT MAX(bar_date) FROM mart.stock_equity_daily WHERE symbol = ANY(%s)),
                    (SELECT MAX(bar_date) FROM mart.stock_etf_daily    WHERE symbol = ANY(%s))
                )
                """,
                (symbols, symbols),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()
