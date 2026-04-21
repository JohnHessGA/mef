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


@dataclass(frozen=True)
class FreshnessReport:
    """How stale the latest mart bar is, relative to a reference 'today'.

    ``status`` is one of:
      - ``ok``    — within ``warn_after_calendar_days``
      - ``warn``  — past warn threshold, still under abort threshold
      - ``abort`` — past abort threshold; pipeline must short-circuit
      - ``empty`` — no bars at all (universe symbols have no mart coverage)

    ``message`` is a short human-readable summary safe to put in an email
    banner or a telemetry event. Pure data — no I/O.
    """
    status: str          # ok | warn | abort | empty
    age_days: int | None
    as_of_date: date | None
    today: date
    warn_threshold: int
    abort_threshold: int
    message: str

    @property
    def should_abort(self) -> bool:
        return self.status in ("abort", "empty")

    @property
    def should_warn(self) -> bool:
        return self.status in ("warn", "abort", "empty")


def check_freshness(
    bundle: EvidenceBundle,
    *,
    today: date,
    warn_after_calendar_days: int,
    abort_after_calendar_days: int,
) -> FreshnessReport:
    """Classify how stale the bundle's latest bar is relative to ``today``.

    Pure function — caller injects ``today`` so this is testable without
    freezing the clock. Threshold semantics are *strictly greater than*:
    age == warn_threshold is still ok; age == warn_threshold + 1 warns.
    """
    if not bundle.symbols:
        return FreshnessReport(
            status="empty", age_days=None, as_of_date=None, today=today,
            warn_threshold=warn_after_calendar_days,
            abort_threshold=abort_after_calendar_days,
            message="No mart data found for any universe symbol.",
        )

    age = (today - bundle.as_of_date).days
    if age > abort_after_calendar_days:
        status = "abort"
    elif age > warn_after_calendar_days:
        status = "warn"
    else:
        status = "ok"

    msg = (
        f"latest mart bar_date={bundle.as_of_date.isoformat()} is "
        f"{age} day(s) behind today ({today.isoformat()}); "
        f"warn>{warn_after_calendar_days}, abort>{abort_after_calendar_days}"
    )
    return FreshnessReport(
        status=status, age_days=age, as_of_date=bundle.as_of_date, today=today,
        warn_threshold=warn_after_calendar_days,
        abort_threshold=abort_after_calendar_days,
        message=msg,
    )


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


# Latest-bar-per-symbol via CTE. The more obvious
# ``DISTINCT ON (symbol) … WHERE symbol = ANY(%s) ORDER BY symbol,
# bar_date DESC`` pattern silently returns stale rows when the universe
# array is large against the TimescaleDB-chunked mart tables — the
# planner's Merge Append truncates per-chunk before the DISTINCT picks,
# so the "latest" becomes an older bar. The CTE forces MAX(bar_date)
# per symbol first, then joins back.

_EQUITY_SQL = """
WITH latest AS (
    SELECT symbol, MAX(bar_date) AS bar_date
      FROM mart.stock_equity_daily
     WHERE symbol = ANY(%s)
     GROUP BY symbol
)
SELECT sed.symbol, sed.bar_date, sed.sector, sed.close,
       sed.return_5d, sed.return_20d, sed.return_63d,
       sed.return_126d, sed.return_252d,
       sed.sma_20, sed.sma_50, sed.sma_200,
       sed.sma_20_slope, sed.sma_50_slope,
       sed.rsi_14, sed.macd_histogram,
       sed.realized_vol_20d,
       sed.drawdown_current,
       sed.volume_z_score,
       sed.atr_14
  FROM mart.stock_equity_daily sed
  JOIN latest l
    ON l.symbol = sed.symbol
   AND l.bar_date = sed.bar_date
"""

_ETF_SQL = """
WITH latest AS (
    SELECT symbol, MAX(bar_date) AS bar_date
      FROM mart.stock_etf_daily
     WHERE symbol = ANY(%s)
     GROUP BY symbol
)
SELECT sed.symbol, sed.bar_date, sed.close,
       sed.return_5d, sed.return_20d, sed.return_63d,
       sed.return_126d, sed.return_252d,
       sed.sma_20, sed.sma_50, sed.sma_200,
       sed.rsi_14, sed.macd_histogram,
       sed.realized_vol_20d,
       sed.drawdown_current,
       sed.volume_z_score,
       sed.atr_14
  FROM mart.stock_etf_daily sed
  JOIN latest l
    ON l.symbol = sed.symbol
   AND l.bar_date = sed.bar_date
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
