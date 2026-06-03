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


# Map UDC sector names → the matching XL* sector ETF in our universe.
# Shared source of truth for the ranker's sector-relative signal and the
# post-hoc scoring benchmark (mef.scoring re-exports this).
SECTOR_TO_ETF = {
    "Technology":             "XLK",
    "Financial Services":     "XLF",
    "Healthcare":             "XLV",
    "Energy":                 "XLE",
    "Industrials":            "XLI",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    # No mapped sector ETF in our 20-ETF universe for:
    #   Communication Services, Utilities, Real Estate, Basic Materials.
    # Stocks in those sectors fall through — no sector-relative score.
}


@dataclass(frozen=True)
class EvidenceBundle:
    as_of_date: date
    baseline: dict[str, Any]               # SPY returns, sector returns, upcoming macro events
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
       sed.realized_vol_20d, sed.realized_vol_63d, sed.bb_width,
       sed.rs_vs_spy_20d, sed.rs_vs_spy_63d, sed.rs_vs_qqq_63d,
       sed.drawdown_current,
       sed.volume_z_score,
       sed.atr_14,
       sed.pe_trailing, sed.free_cash_flow, sed.earnings_yield
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
       sed.realized_vol_20d, sed.realized_vol_63d, sed.bb_width,
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


# Ticker-reuse guard. A reused ticker (a delisted issuer's symbol later adopted
# by a different company) splices two issuers under one symbol in the mart, so a
# trailing return whose window reaches before the boundary compares two
# companies. shdb.security_ticker_boundary (the platform SSOT mirror) records the
# date the current entity's series begins; we null any return_Nd whose N-trading-
# day lookback would cross it. Only 2 universe names carry a boundary today
# (COR, FISV) and only their longest windows are affected, but the guard is
# general. See ~/repos/aft-platform/docs/platform/security-identity-and-ticker-reuse.md.
_BOUNDARY_SQL = """
SELECT symbol, MAX(boundary_date) AS boundary_date
  FROM shdb.security_ticker_boundary
 WHERE symbol = ANY(%s)
 GROUP BY symbol
"""

_RETURN_WINDOWS = (5, 20, 63, 126, 252)          # trading days; mirrors return_*d cols
_TRADING_DAYS_PER_CAL_DAY = 252 / 365.0


def _fetch_boundaries(cur, symbols: list[str]) -> dict[str, Any]:
    """Map symbol -> current-entity start (max boundary_date). Empty + fail-open
    if the boundary view is absent (older SHDB) — never blocks a run."""
    try:
        cur.execute(_BOUNDARY_SQL, (symbols,))
        return {sym: bnd for sym, bnd in cur.fetchall()}
    except Exception:
        return {}


def _apply_boundary_guard(rows: dict[str, dict[str, Any]], boundaries: dict[str, Any]) -> None:
    """Null any return_Nd whose N-trading-day lookback reaches before the symbol's
    ticker-reuse boundary (the window would splice two issuers). The ranker already
    treats None as 'signal unavailable'."""
    for sym, bnd in boundaries.items():
        row = rows.get(sym)
        if row is None or bnd is None or row.get("bar_date") is None:
            continue
        avail_trading_days = int((row["bar_date"] - bnd).days * _TRADING_DAYS_PER_CAL_DAY)
        for n in _RETURN_WINDOWS:
            if n > avail_trading_days:
                row[f"return_{n}d"] = None


_UPCOMING_EARNINGS_SQL = """
SELECT symbol, MIN(announcement_date) AS next_earnings_date
  FROM shdb.earnings_calendar_upcoming
 WHERE symbol = ANY(%s)
   AND announcement_date >= %s
 GROUP BY symbol
"""

# Upcoming macro-calendar events — scalar per run (not per symbol), so
# scoped to a single bundle-level fetch. Only US High-impact events
# within a short horizon count; lower-impact events are routine noise.
_UPCOMING_MACRO_EVENTS_SQL = """
SELECT bar_date, event
  FROM shdb.economic_calendar
 WHERE country = 'US' AND impact = 'High'
   AND bar_date BETWEEN %s AND %s
 ORDER BY bar_date, event
"""


def _fetch_earnings_context(symbols: list[str], as_of: date) -> dict[str, date]:
    """Return {symbol: next_earnings_date} for each symbol with an upcoming announcement."""
    if not symbols:
        return {}
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(_UPCOMING_EARNINGS_SQL, (symbols, as_of))
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def _fetch_upcoming_macro_events(as_of: date, horizon_days: int = 3) -> list[dict[str, Any]]:
    """Return upcoming US High-impact macro events within the horizon."""
    from datetime import timedelta
    conn = connect_shdb()
    try:
        with conn.cursor() as cur:
            cur.execute(_UPCOMING_MACRO_EVENTS_SQL, (as_of, as_of + timedelta(days=horizon_days)))
            return [{"date": row[0], "event": row[1]} for row in cur.fetchall()]
    finally:
        conn.close()


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
            boundaries = _fetch_boundaries(cur, stock_symbols + etf_symbols)
    finally:
        conn.close()

    # Null any trailing return whose window crosses a ticker-reuse boundary,
    # before the baseline / ranker consume the feature rows.
    _apply_boundary_guard(stocks, boundaries)
    _apply_boundary_guard(etfs, boundaries)

    symbols = {**stocks, **etfs}

    # Latest bar_date across both asset kinds.
    dates = [r["bar_date"] for r in symbols.values() if r.get("bar_date") is not None]
    as_of = max(dates) if dates else date.today()

    # SPY baseline: 20d / 63d return, taken directly from the ETF feature row.
    spy_row = etfs.get("SPY", {})
    # Sector ETF 63d returns, for the ranker's sector-relative signal.
    # Sector ETFs are part of the ETF universe so they're already loaded
    # in `etfs`; no extra query needed.
    sector_returns_63d = {
        etf: etfs[etf].get("return_63d")
        for etf in SECTOR_TO_ETF.values()
        if etf in etfs and etfs[etf].get("return_63d") is not None
    }
    # Upcoming earnings dates per stock — stitched into each stock's
    # feature dict. Coverage ≈99% of the universe; symbols without an
    # upcoming announcement just get next_earnings_date=None.
    earnings_map = _fetch_earnings_context(stock_symbols, as_of)
    for sym, row in stocks.items():
        row["next_earnings_date"] = earnings_map.get(sym)

    # Upcoming macro events — bundle-level scalar (not per symbol).
    upcoming_macro_events = _fetch_upcoming_macro_events(as_of, horizon_days=3)

    baseline = {
        "spy_return_20d":              spy_row.get("return_20d"),
        "spy_return_63d":              spy_row.get("return_63d"),
        "sector_returns_63d":          sector_returns_63d,
        "upcoming_high_impact_events": upcoming_macro_events,
    }

    return EvidenceBundle(as_of_date=as_of, baseline=baseline, symbols=symbols)
