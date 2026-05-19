"""ETF entry-condition classifier — reporting layer only.

Maps a single ETF feature row (latest mart bar) to one of six entry
labels for the MEF daily report. Pure function; no DB access, no
side effects, no influence on the stock ranker or recommendation
pipeline.

Labels (precedence order — first match wins):

    breakdown_risk     — long-term trend broken with weak RS
    extended_wait      — near recent high and stretched above trend
    healthy_pullback   — pulled back from recent high, long-term trend intact
    near_entry         — small pullback, almost at healthy-pullback territory
    reasonable_entry   — trend intact, not stretched, fine for measured deployment
    neutral            — no strong entry signal either way

The classifier tolerates missing fields by skipping rules that need
them; if not enough data is present, it falls through to ``neutral``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mef.dq_guardrails import safe_drawdown


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

LABELS = (
    "breakdown_risk",
    "extended_wait",
    "healthy_pullback",
    "near_entry",
    "reasonable_entry",
    "neutral",
)


@dataclass(frozen=True)
class EtfEntryLabel:
    symbol: str
    label: str
    reason: str
    components: dict[str, Any] = field(default_factory=dict)


# Thresholds — kept module-level so tests can reference them by name
# rather than re-deriving magic numbers. Tuned for a 305+20 universe of
# liquid US equity / equity-style ETFs; not for bond, leveraged, or
# inverse products (none of which are in the universe).
T = {
    "near_high_dd":          -0.02,   # within 2% of recent peak
    "stretched_above_sma50":  0.05,   # 5% above SMA50
    "rsi_overbought":         72.0,
    "rsi_oversold":           30.0,
    "rsi_warm":               65.0,
    "rsi_cool":               40.0,
    "pullback_min_dd":       -0.03,   # at least 3% off peak
    "pullback_max_dd":       -0.12,   # not more than 12% off peak
    "near_entry_min_dd":     -0.03,
    "near_entry_max_dd":     -0.005,
    "reasonable_max_above_sma50": 0.04,
    "rs_weak_63d":           -0.04,   # underperforming SPY by 4%+ over 63d
    "ret63d_weak":           -0.08,   # absolute weakness
    "pullback_sma50_band":    0.97,   # close not below SMA50 * 0.97
    "data_anomaly_sma50_gap": 0.30,   # |close/sma_50 - 1| above this looks like
                                      # an unadjusted split or stale SMA — flag,
                                      # don't try to classify
}


def classify_etf(
    features: dict[str, Any],
    spy_features: dict[str, Any] | None = None,
) -> EtfEntryLabel:
    """Classify a single ETF's entry condition from its latest features.

    Arguments
    ---------
    features
        Latest-bar feature dict for the ETF — same shape returned by
        ``mef.evidence._rows_to_dict`` for ``asset_kind="etf"``. Must
        include ``symbol``; all other fields are optional and the
        classifier tolerates missing values.
    spy_features
        Latest-bar feature dict for SPY (used to derive RS over 63d).
        Optional; if absent or missing ``return_63d``, RS-based rules
        degrade gracefully — they simply don't fire and other rules
        take precedence.
    """
    symbol = features.get("symbol", "?")

    close = features.get("close")
    sma_50 = features.get("sma_50")
    sma_200 = features.get("sma_200")
    rsi = features.get("rsi_14")
    # Wrap with safe_drawdown so split-cascade artifacts (drawdown ≈ -1.0
    # on micro-caps with multiple reverse splits) land as missing rather
    # than as a real extreme. See mef.dq_guardrails.
    dd = safe_drawdown(features.get("drawdown_current"))   # negative number, -0.05 = 5% off peak
    ret_63d = features.get("return_63d")

    spy_ret_63d = (spy_features or {}).get("return_63d") if spy_features else None
    rs_vs_spy_63d = (
        ret_63d - spy_ret_63d
        if (ret_63d is not None and spy_ret_63d is not None)
        else None
    )

    pct_above_sma50 = _pct_above(close, sma_50)
    pct_above_sma200 = _pct_above(close, sma_200)

    components = {
        "close": close,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi_14": rsi,
        "drawdown_current": dd,
        "return_63d": ret_63d,
        "pct_above_sma50": pct_above_sma50,
        "pct_above_sma200": pct_above_sma200,
        "rs_vs_spy_63d": rs_vs_spy_63d,
    }

    # Pre-check — data-anomaly guard.
    # A liquid equity / equity-style ETF that is genuinely in a bear
    # market does not sustain a 30%+ gap between close and SMA50; mean
    # reversion drags one toward the other. A gap that wide almost
    # always means the SMA was computed before a split that the close
    # has been adjusted for, or some other staleness on the upstream
    # mart row. Don't try to classify — emit neutral with a flag so the
    # operator knows to fix the data, not chase the symbol.
    if (
        pct_above_sma50 is not None
        and abs(pct_above_sma50) > T["data_anomaly_sma50_gap"]
    ):
        return EtfEntryLabel(
            symbol=symbol,
            label="neutral",
            reason=(
                f"data anomaly suspected — close/SMA50 gap "
                f"{pct_above_sma50*100:+.0f}% (likely unadjusted split)"
            ),
            components=components,
        )

    # Rule 1 — breakdown_risk
    # Long-term trend broken (close < SMA200) AND either RS is materially
    # weak vs SPY over 63d OR absolute 63d return is decisively negative.
    if (
        close is not None and sma_200 is not None and close < sma_200
        and (
            (rs_vs_spy_63d is not None and rs_vs_spy_63d < T["rs_weak_63d"])
            or (ret_63d is not None and ret_63d < T["ret63d_weak"])
            or (sma_50 is not None and close < sma_50)
        )
    ):
        reason_parts = ["below SMA200"]
        if rs_vs_spy_63d is not None and rs_vs_spy_63d < T["rs_weak_63d"]:
            reason_parts.append(f"RS vs SPY {rs_vs_spy_63d*100:+.1f}% (63d)")
        elif ret_63d is not None and ret_63d < T["ret63d_weak"]:
            reason_parts.append(f"63d return {ret_63d*100:+.1f}%")
        elif sma_50 is not None and close < sma_50:
            reason_parts.append("also below SMA50")
        return EtfEntryLabel(
            symbol=symbol,
            label="breakdown_risk",
            reason=", ".join(reason_parts),
            components=components,
        )

    # Rule 2 — extended_wait
    # Near recent high (drawdown shallower than -2%) and either stretched
    # above SMA50 (>5%) or RSI overbought (>72).
    near_high = dd is not None and dd > T["near_high_dd"]
    stretched_50 = (
        pct_above_sma50 is not None and pct_above_sma50 > T["stretched_above_sma50"]
    )
    overbought = rsi is not None and rsi > T["rsi_overbought"]
    if near_high and (stretched_50 or overbought):
        reason_parts = ["near recent high"]
        if stretched_50:
            reason_parts.append(f"{pct_above_sma50*100:+.1f}% above SMA50")
        elif overbought:
            reason_parts.append(f"RSI {rsi:.0f} overbought")
        return EtfEntryLabel(
            symbol=symbol,
            label="extended_wait",
            reason=", ".join(reason_parts),
            components=components,
        )

    # Rule 3 — healthy_pullback
    # Pulled back 3%-12% from recent peak, long-term trend intact
    # (close > SMA200), and not collapsing through SMA50.
    if (
        dd is not None and T["pullback_max_dd"] <= dd <= T["pullback_min_dd"]
        and close is not None and sma_200 is not None and close > sma_200
        and (sma_50 is None or close >= sma_50 * T["pullback_sma50_band"])
    ):
        reason = f"down {abs(dd)*100:.1f}% from recent high, above SMA200"
        return EtfEntryLabel(
            symbol=symbol,
            label="healthy_pullback",
            reason=reason,
            components=components,
        )

    # Rule 4 — near_entry
    # Small pullback (0.5%-3% from peak), trend still intact.
    # Approaching healthy-pullback territory but not there yet.
    if (
        dd is not None and T["near_entry_min_dd"] < dd <= T["near_entry_max_dd"]
        and close is not None and sma_200 is not None and close > sma_200
    ):
        reason = f"down {abs(dd)*100:.1f}% from recent high, approaching pullback"
        return EtfEntryLabel(
            symbol=symbol,
            label="near_entry",
            reason=reason,
            components=components,
        )

    # Rule 5 — reasonable_entry
    # Trend intact (above SMA200), above SMA50, not stretched (<4% above
    # SMA50), and RSI in a reasonable band (not overbought, not deeply
    # oversold). The Goldilocks region for measured deployment.
    if (
        close is not None and sma_200 is not None and close > sma_200
        and sma_50 is not None and close > sma_50
        and pct_above_sma50 is not None
        and pct_above_sma50 < T["reasonable_max_above_sma50"]
        and (rsi is None or T["rsi_cool"] <= rsi <= T["rsi_warm"])
    ):
        return EtfEntryLabel(
            symbol=symbol,
            label="reasonable_entry",
            reason="trend intact, entry not stretched",
            components=components,
        )

    # Rule 6 — neutral fallback
    return EtfEntryLabel(
        symbol=symbol,
        label="neutral",
        reason="no strong entry signal",
        components=components,
    )


def classify_universe(
    etf_features: dict[str, dict[str, Any]],
    spy_symbol: str = "SPY",
) -> list[EtfEntryLabel]:
    """Classify every ETF in ``etf_features`` and return a list sorted by symbol.

    ``etf_features`` is the dict-of-dicts returned by
    ``mef.evidence._rows_to_dict`` for ``asset_kind="etf"``. SPY is read
    from that same dict (it is part of the ETF universe) for RS-vs-SPY
    derivation.
    """
    spy = etf_features.get(spy_symbol)
    return sorted(
        (classify_etf(row, spy) for row in etf_features.values()),
        key=lambda e: e.symbol,
    )


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _pct_above(close: float | None, sma: float | None) -> float | None:
    if close is None or sma is None or sma == 0:
        return None
    return (close - sma) / sma
