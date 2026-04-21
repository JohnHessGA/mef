"""Post-emission price-freshness sanity check.

Fetches a "now" quote for every emitted idea and classifies how much
the live price has moved since the SHDB close used for scoring. The
result is purely informational — it never changes conviction, posture,
entry zones, stops, or targets. The email surfaces a short note when
the move is meaningful; otherwise the annotation is silent.

Scope:
  - runs on 5–10 emitted ideas per run, not the full 305+15 universe
  - single network call, fail-silent — a yfinance hiccup never
    blocks the email or the run
  - session-aware tagging: "regular" / "pre" / "post" / "closed"
    derived from the bar timestamp the quote arrived with

Why not run this on every candidate: the ranker decides which stocks
are interesting from multi-week signals; a 1-day move doesn't change
that judgment. Live pricing only matters for the user's question
"is the entry zone in this email still valid?" — and that question
only matters for what we're actually asking them to consider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

log = logging.getLogger("mef.price_check")


TIER_NONE = "none"                  # |delta| below info threshold → no note
TIER_INFO = "info"                  # moderate move → neutral annotation
TIER_WARN = "warn"                  # large move → ⚠ annotation
TIER_UNAVAILABLE = "unavailable"    # fetch failed or no data


@dataclass(frozen=True)
class PriceCheckResult:
    symbol: str
    last_close: float                   # SHDB close used at scoring time
    current_price: float | None = None  # best-available live print
    as_of: datetime | None = None       # timestamp of the live print (UTC)
    source_session: str = TIER_UNAVAILABLE  # regular | pre | post | closed | unavailable
    delta_abs: float | None = None      # current − last_close
    delta_pct: float | None = None      # delta_abs / last_close
    staleness_tier: str = TIER_UNAVAILABLE
    note: str | None = None             # short line for email, or None


@dataclass
class PriceCheckSummary:
    results: dict[str, PriceCheckResult] = field(default_factory=dict)
    fetch_error: str | None = None       # populated on yfinance failure
    fetched_at: datetime | None = None


# ─── Session classification — map ET wall-clock to session bucket ────────

def _et_offset_hours(dt_utc: datetime) -> int:
    """Approximate ET offset (−5 EST / −4 EDT) without a tz library.

    DST in the US: second Sun of March → first Sun of November.
    Close enough for session labeling; the actual fetch timestamp is
    stored so anyone who needs second-order accuracy has it.
    """
    year = dt_utc.year
    # Second Sunday of March, first Sunday of November, both 02:00 ET.
    # Compute in UTC by adding 7 hours (06:00 UTC boundary is a safe
    # approximation for our purposes).
    def nth_sunday(month: int, n: int) -> datetime:
        # Find the first Sunday of the month in UTC at 06:00.
        for day in range(1, 8):
            d = datetime(year, month, day, 6, 0, tzinfo=timezone.utc)
            if d.weekday() == 6:  # Sunday
                return d + (n - 1) * __import__("datetime").timedelta(days=7)
        # Unreachable.
        return datetime(year, month, 1, 6, 0, tzinfo=timezone.utc)

    dst_start = nth_sunday(3, 2)
    dst_end = nth_sunday(11, 1)
    return -4 if dst_start <= dt_utc < dst_end else -5


def _classify_session(bar_time_utc: datetime) -> str:
    """Classify a bar timestamp into the session it belongs to."""
    offset = _et_offset_hours(bar_time_utc)
    et_hour = (bar_time_utc.hour + offset) % 24
    et_min = bar_time_utc.minute
    et = time(et_hour, et_min)
    # Mon-Fri only would be ideal but our runs don't fire on weekends.
    if time(9, 30) <= et < time(16, 0):
        return "regular"
    if time(4, 0) <= et < time(9, 30):
        return "pre"
    if time(16, 0) <= et < time(20, 0):
        return "post"
    return "closed"


# ─── Network fetch (yfinance) — isolated so tests can mock it cleanly ────

def _fetch_bars(symbols: list[str]) -> dict[str, tuple[float, datetime]]:
    """Return {symbol: (last_close, bar_time_utc)} or raise on failure.

    Uses yfinance 1-minute bars with prepost=True so the most recent
    print — regular, pre, or post — lands in the series. Takes the
    last non-null close per symbol.
    """
    import yfinance as yf

    # Batch download — one HTTP request for all tickers.
    df = yf.download(
        tickers=symbols, period="1d", interval="1m",
        prepost=True, progress=False, group_by="ticker", auto_adjust=False,
        threads=True,
    )

    out: dict[str, tuple[float, datetime]] = {}
    if df is None or df.empty:
        return out

    # Single ticker case: df has no top-level ticker grouping.
    if len(symbols) == 1:
        sym = symbols[0]
        closes = df["Close"].dropna()
        if len(closes) > 0:
            last_idx = closes.index[-1]
            last_val = float(closes.iloc[-1])
            bar_time = last_idx.to_pydatetime()
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)
            out[sym] = (last_val, bar_time)
        return out

    # Multi-ticker case: df has a (ticker, field) MultiIndex on columns.
    for sym in symbols:
        try:
            series = df[sym]["Close"].dropna()
        except (KeyError, AttributeError):
            continue
        if len(series) == 0:
            continue
        last_idx = series.index[-1]
        last_val = float(series.iloc[-1])
        bar_time = last_idx.to_pydatetime()
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        else:
            bar_time = bar_time.astimezone(timezone.utc)
        out[sym] = (last_val, bar_time)
    return out


# ─── Classification ─────────────────────────────────────────────────────

def _classify_delta(
    last_close: float, current: float,
    *, info_threshold_pct: float, warn_threshold_pct: float,
) -> tuple[float, float, str, str | None]:
    """Return (delta_abs, delta_pct, tier, note)."""
    delta_abs = current - last_close
    delta_pct = delta_abs / last_close if last_close else 0.0
    mag = abs(delta_pct)
    if mag < info_threshold_pct:
        return delta_abs, delta_pct, TIER_NONE, None
    sign = "+" if delta_abs >= 0 else "−"
    pct_str = f"{sign}{abs(delta_pct) * 100:.1f}%"
    if mag < warn_threshold_pct:
        return (
            delta_abs, delta_pct, TIER_INFO,
            f"moved {pct_str} since close (live ~${current:,.2f})",
        )
    return (
        delta_abs, delta_pct, TIER_WARN,
        f"⚠ moved {pct_str} since close (live ~${current:,.2f}) — "
        f"entry zone may need refresh",
    )


# ─── Public entry point ─────────────────────────────────────────────────

def check_prices(
    ideas: list[dict[str, Any]],
    *,
    info_threshold_pct: float = 0.01,
    warn_threshold_pct: float = 0.03,
    enabled: bool = True,
    now_utc: datetime | None = None,
) -> PriceCheckSummary:
    """Fetch live prices for the given ideas and classify each delta.

    Accepts ``emitted_rows`` straight from ``run_pipeline`` (dicts with
    ``symbol`` and ``current_price`` keys — ``current_price`` is the
    SHDB close used at scoring time). Returns a summary that is safe to
    merge back into those dicts.

    Always returns a populated summary even on failure — network
    failures result in ``TIER_UNAVAILABLE`` entries, never a raised
    exception. This preserves the design rule that the price check is
    informational and must not block email delivery.
    """
    summary = PriceCheckSummary(fetched_at=now_utc or datetime.now(timezone.utc))
    if not enabled or not ideas:
        return summary

    # Dedup symbols — same symbol can appear under multiple engines.
    symbols_to_close: dict[str, float] = {}
    for idea in ideas:
        sym = idea.get("symbol")
        close = idea.get("current_price")
        if sym and close is not None and sym not in symbols_to_close:
            symbols_to_close[sym] = float(close)
    if not symbols_to_close:
        return summary

    symbols = sorted(symbols_to_close.keys())
    try:
        bars = _fetch_bars(symbols)
    except Exception as exc:
        summary.fetch_error = f"{type(exc).__name__}: {exc}"
        log.warning("price_check fetch failed: %s", summary.fetch_error)
        bars = {}

    for sym in symbols:
        last_close = symbols_to_close[sym]
        pair = bars.get(sym)
        if pair is None:
            summary.results[sym] = PriceCheckResult(
                symbol=sym, last_close=last_close,
                staleness_tier=TIER_UNAVAILABLE,
                source_session=TIER_UNAVAILABLE,
                note=None,
            )
            continue
        current, bar_time = pair
        delta_abs, delta_pct, tier, note = _classify_delta(
            last_close, current,
            info_threshold_pct=info_threshold_pct,
            warn_threshold_pct=warn_threshold_pct,
        )
        summary.results[sym] = PriceCheckResult(
            symbol=sym, last_close=last_close,
            current_price=current, as_of=bar_time,
            source_session=_classify_session(bar_time),
            delta_abs=round(delta_abs, 4),
            delta_pct=round(delta_pct, 6),
            staleness_tier=tier, note=note,
        )
    return summary


def annotate_ideas(
    ideas: list[dict[str, Any]], summary: PriceCheckSummary,
) -> None:
    """Merge price-check results back into the emitted_rows list in place.

    Adds keys: ``price_check_current``, ``price_check_delta_pct``,
    ``price_check_tier``, ``price_check_session``, ``price_check_note``.
    Ideas with no matching result (disabled, fetch-failure, or symbol
    absent from the response) get tier=``unavailable`` and note=None.
    """
    for idea in ideas:
        sym = idea.get("symbol")
        if not sym:
            continue
        r = summary.results.get(sym)
        if r is None:
            idea["price_check_tier"] = TIER_UNAVAILABLE
            idea["price_check_note"] = None
            idea["price_check_session"] = TIER_UNAVAILABLE
            continue
        idea["price_check_current"] = r.current_price
        idea["price_check_delta_pct"] = r.delta_pct
        idea["price_check_tier"] = r.staleness_tier
        idea["price_check_session"] = r.source_session
        idea["price_check_note"] = r.note
