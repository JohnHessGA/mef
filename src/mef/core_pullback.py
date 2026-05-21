"""MEF Job 2 — Core Pullback Watchlist engine (deterministic v1).

Given one evidence row (from ``mef.core_pullback_evidence``) and one
tier (from ``mef.core_pullback_repository``), produce a single
``PullbackSignal`` with a status drawn from the six-value vocabulary
in ``docs/mef_core_pullback_watchlist.md`` §Status Vocabulary.

Boundaries (CLAUDE.md §0, README §Hard Boundaries):
- No LLM. No external APIs. No CIA overlay.
- No reads from markdown, YAML, docs, or notes.
- Operational symbol lists and tier thresholds come from MEFDB only.

Degradation: when an optional feature is missing the engine returns a
valid signal with a caution string rather than raising. The only fatal
condition is no ``close`` price at all (the symbol falls through to
``NO_PULLBACK`` with a "no_evidence" caution — never to a buyable state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from mef.core_pullback_repository import WatchlistRow
from mef.dq_guardrails import safe_drawdown, safe_short_horizon_drawdown


# ─────────────────────────────────────────────────────────────────────────
# Status vocabulary — must match the CHECK constraint on
# mef.core_pullback_snapshot (migration 013).
# ─────────────────────────────────────────────────────────────────────────

STATUS_NO_PULLBACK              = "NO_PULLBACK"
STATUS_PULLBACK_FORMING         = "PULLBACK_FORMING"
STATUS_BUY_ZONE_ACTIVE          = "BUY_ZONE_ACTIVE"
STATUS_DEEP_PULLBACK_OPPORTUNITY = "DEEP_PULLBACK_OPPORTUNITY"
STATUS_FALLING_KNIFE_WAIT       = "FALLING_KNIFE_WAIT"
STATUS_THESIS_BROKEN_REVIEW     = "THESIS_BROKEN_REVIEW"

# Human display labels (also used by the renderer)
DISPLAY_LABEL = {
    STATUS_NO_PULLBACK:               "No meaningful pullback yet",
    STATUS_PULLBACK_FORMING:          "Pullback forming",
    STATUS_BUY_ZONE_ACTIVE:           "Buy zone active",
    STATUS_DEEP_PULLBACK_OPPORTUNITY: "Deep pullback opportunity",
    STATUS_FALLING_KNIFE_WAIT:        "Falling knife — wait",
    STATUS_THESIS_BROKEN_REVIEW:      "Thesis/risk changed — review before buying",
}

# Order for rendering — most-actionable first.
NOTABLE_STATUS_ORDER = (
    STATUS_DEEP_PULLBACK_OPPORTUNITY,
    STATUS_BUY_ZONE_ACTIVE,
    STATUS_PULLBACK_FORMING,
    STATUS_FALLING_KNIFE_WAIT,
    STATUS_THESIS_BROKEN_REVIEW,
)
NOTABLE_STATUSES = set(NOTABLE_STATUS_ORDER)


# ─────────────────────────────────────────────────────────────────────────
# Trend health + stabilization vocabularies — internal only
# ─────────────────────────────────────────────────────────────────────────

TREND_HEALTHY  = "healthy"
TREND_DAMAGED  = "damaged"
TREND_BROKEN   = "broken"
TREND_UNKNOWN  = "unknown"   # not enough evidence to judge

STAB_OK        = "ok"
STAB_NOT_OK    = "not_ok"
STAB_UNKNOWN   = "unknown"


# Pragmatic thresholds. These are deliberately tier-agnostic for v1 trend
# health; tier-awareness lives in the pullback thresholds (already loaded
# from mef.core_pullback_tier) and in the stabilization rule below.
_BROKEN_RETURN_252D       = -0.30   # -30% trailing-year return → trend broken
_BROKEN_BELOW_SMA200_PCT  = -0.10   # close more than 10% below SMA200 → broken
_DAMAGED_BELOW_SMA200_PCT = -0.02   # 2-10% below SMA200 → damaged (not broken)

# Stabilization: tier-4 must clear a stricter bar before a pullback is
# treated as a buy zone. ETFs (any tier-1) and Tier-2 share the looser
# threshold; quality_growth (Tier-3) sits in between.
_STAB_RETURN_5D_BY_TIER = {
    "core_market_etf":            -0.05,
    "core_growth_etf":            -0.05,
    "elite_compounder":           -0.05,
    "quality_growth":             -0.06,
    "volatile_special_situation": -0.08,
}
_STAB_RETURN_5D_DEFAULT = -0.06

# RSI floor for stabilization — below this we treat the move as still
# collapsing regardless of return_5d.
_STAB_RSI_PANIC_FLOOR = 22.0


# ─────────────────────────────────────────────────────────────────────────
# Output object
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PullbackSignal:
    symbol: str
    asset_kind: str
    tier_code: str
    tier_display_name: str
    status: str
    display_label: str
    close: float | None
    as_of_date: date | None
    drawdown_63d: float | None       # negative number (e.g. -0.06 = 6% below 63d high)
    drawdown_252d: float | None
    starter_buy_level: float | None
    better_buy_level: float | None
    deep_buy_level: float | None
    trend_health: str                # healthy | damaged | broken | unknown
    stabilization: str               # ok | not_ok | unknown
    risk_reward: float | None
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _recover_peak_252d(close: float | None, drawdown_current: float | None) -> float | None:
    """Back out the trailing-252d peak from close + drawdown_current.

    SHDB's ``drawdown_current`` is negative when price is below the peak,
    so peak = close / (1 + drawdown_current). Returns None if either
    input is missing or the math is degenerate.
    """
    if close is None or drawdown_current is None:
        return None
    denom = 1.0 + drawdown_current
    if denom <= 0:
        return None
    return close / denom


def _classify_trend(
    *, close: float | None, sma_200: float | None,
    sma_50_slope: float | None, return_252d: float | None,
) -> tuple[str, list[str]]:
    """Healthy / damaged / broken from close vs SMA200, slope, and yearly return.

    The "broken" rule fires on the first hit:
      - return_252d <= -30%
      - close > 10% below SMA200
    "damaged" fires on a milder version of either. Otherwise "healthy".
    """
    reasons: list[str] = []
    if close is None or sma_200 is None:
        return TREND_UNKNOWN, ["trend_unknown: missing close or SMA200"]

    rel_to_sma200 = (close - sma_200) / sma_200
    if return_252d is not None and return_252d <= _BROKEN_RETURN_252D:
        reasons.append(f"return_252d {return_252d:.0%} ≤ -30%")
        return TREND_BROKEN, reasons
    if rel_to_sma200 <= _BROKEN_BELOW_SMA200_PCT:
        reasons.append(f"close {rel_to_sma200:.1%} below SMA200")
        return TREND_BROKEN, reasons
    if rel_to_sma200 <= _DAMAGED_BELOW_SMA200_PCT:
        reasons.append(f"close {rel_to_sma200:.1%} below SMA200")
        return TREND_DAMAGED, reasons
    if sma_50_slope is not None and sma_50_slope < 0 and rel_to_sma200 < 0:
        reasons.append("SMA50 falling while below SMA200")
        return TREND_DAMAGED, reasons
    reasons.append("close above SMA200")
    return TREND_HEALTHY, reasons


def _classify_stabilization(
    *, tier_code: str, return_5d: float | None, rsi_14: float | None,
) -> tuple[str, list[str]]:
    """Decide whether the recent decline has paused enough to call buyable.

    Tier 4 requires a stricter return_5d floor than ETFs / Tier 2.
    A panic-low RSI overrides return_5d and forces ``not_ok``.
    """
    reasons: list[str] = []
    if return_5d is None and rsi_14 is None:
        return STAB_UNKNOWN, ["stabilization_unknown: missing return_5d and RSI14"]

    if rsi_14 is not None and rsi_14 <= _STAB_RSI_PANIC_FLOOR:
        reasons.append(f"RSI14 {rsi_14:.0f} ≤ {_STAB_RSI_PANIC_FLOOR:.0f} (panic)")
        return STAB_NOT_OK, reasons

    threshold = _STAB_RETURN_5D_BY_TIER.get(tier_code, _STAB_RETURN_5D_DEFAULT)
    if return_5d is not None and return_5d <= threshold:
        reasons.append(f"return_5d {return_5d:.1%} ≤ {threshold:.0%} (tier floor)")
        return STAB_NOT_OK, reasons

    reasons.append("recent slide not catastrophic")
    return STAB_OK, reasons


def _risk_reward(
    *, close: float | None, target: float | None,
    sma_200: float | None, atr_14: float | None,
) -> float | None:
    """upside / downside ratio. Returns None if either side can't be computed.

    Upside  = target - close.
    Downside reference = max(distance to SMA200, 2 * ATR14). Using the larger
    keeps R:R honest when price is already near SMA200 but ATR is wide.
    """
    if close is None or target is None or target <= close:
        return None
    upside = target - close
    sma_distance = (close - sma_200) if sma_200 is not None and close > sma_200 else None
    atr_distance = (2.0 * atr_14) if atr_14 is not None else None
    if sma_distance is None and atr_distance is None:
        return None
    downside = max(d for d in (sma_distance, atr_distance) if d is not None)
    if downside <= 0:
        return None
    return upside / downside


# ─────────────────────────────────────────────────────────────────────────
# Engine entry point
# ─────────────────────────────────────────────────────────────────────────

def compute_pullback_signal(
    tier: WatchlistRow,
    evidence: dict[str, Any] | None,
) -> PullbackSignal:
    """Pure: tier + evidence row → PullbackSignal.

    ``evidence is None`` means SHDB had no row for this symbol. We still
    return a valid signal (status=NO_PULLBACK with a missing-data caution)
    rather than raising — Job 2 should degrade quietly per the spec.
    """
    cautions: list[str] = []
    reasons: list[str] = []

    if evidence is None:
        cautions.append("no_evidence: symbol absent from SHDB")
        return PullbackSignal(
            symbol=tier.symbol,
            asset_kind=tier.asset_kind,
            tier_code=tier.tier_code,
            tier_display_name=tier.tier_display_name,
            status=STATUS_NO_PULLBACK,
            display_label=DISPLAY_LABEL[STATUS_NO_PULLBACK],
            close=None,
            as_of_date=None,
            drawdown_63d=None,
            drawdown_252d=None,
            starter_buy_level=None,
            better_buy_level=None,
            deep_buy_level=None,
            trend_health=TREND_UNKNOWN,
            stabilization=STAB_UNKNOWN,
            risk_reward=None,
            reasons=["no evidence"],
            cautions=cautions,
        )

    close = _as_float(evidence.get("close"))
    sma_50 = _as_float(evidence.get("sma_50"))
    sma_200 = _as_float(evidence.get("sma_200"))
    sma_50_slope = _as_float(evidence.get("sma_50_slope"))
    return_5d = _as_float(evidence.get("return_5d"))
    return_252d = _as_float(evidence.get("return_252d"))
    rsi_14 = _as_float(evidence.get("rsi_14"))
    atr_14 = _as_float(evidence.get("atr_14"))
    drawdown_current = _as_float(evidence.get("drawdown_current"))
    high_63d = _as_float(evidence.get("high_63d"))
    as_of = evidence.get("bar_date")
    if as_of is not None and not isinstance(as_of, date):
        as_of = None

    # ─── Drawdowns ────────────────────────────────────────────────────
    # Negative numbers (close is at or below the peak). high_252d is
    # recovered from drawdown_current; high_63d is queried directly.
    #
    # Both values are passed through dq_guardrails because the upstream
    # mart bars carry split-adjustment artifacts on symbols that had
    # reverse splits inside the lookback window. Without these guards a
    # symbol like VUG could report an 80%+ "drawdown" that's really a
    # split-adjusted-close vs unadjusted-high mismatch.
    drawdown_252d_raw = drawdown_current
    drawdown_252d = safe_drawdown(drawdown_current)
    if drawdown_252d_raw is not None and drawdown_252d is None:
        cautions.append("suspect_drawdown_252d: dropped (likely split artifact)")

    peak_252d = _recover_peak_252d(close, drawdown_252d)

    if close is None:
        cautions.append("no_close_price")
        return _no_pullback_with(tier, as_of, close, None, drawdown_252d,
                                 None, None, None,
                                 TREND_UNKNOWN, STAB_UNKNOWN, None,
                                 reasons=["no close price"], cautions=cautions)

    if high_63d is not None and high_63d > 0:
        drawdown_63d_raw = (close / high_63d) - 1.0
        drawdown_63d = safe_short_horizon_drawdown(drawdown_63d_raw)
        if drawdown_63d is None:
            cautions.append(
                f"suspect_drawdown_63d {drawdown_63d_raw:.0%}: dropped (likely split artifact)"
            )
            # The high_63d itself is suspect — don't use it for buy levels either.
            high_63d = None
    else:
        drawdown_63d = None
        cautions.append("missing_high_63d: starter/better levels degraded")

    if peak_252d is None:
        cautions.append("missing_high_252d: deep level degraded")

    # Pullback magnitude used for threshold comparison.
    # Prefer the deeper of the two drawdowns when both are present —
    # buying off the 252d peak is what matters for "deep pullback opportunity".
    candidates = [d for d in (drawdown_252d, drawdown_63d) if d is not None]
    pullback_pct = -min(candidates) if candidates else 0.0  # positive magnitude

    # ─── Buy levels ───────────────────────────────────────────────────
    # Tier-aware percentages applied to recent highs. If the high is
    # missing we leave the level as None — the renderer will skip it.
    if high_63d is not None:
        starter = high_63d * (1.0 - tier.visibility_drawdown)
        better  = high_63d * (1.0 - tier.buy_zone_drawdown)
    else:
        starter = better = None
    if peak_252d is not None:
        deep    = peak_252d * (1.0 - tier.deep_drawdown)
    else:
        deep    = None

    # ─── Trend health ─────────────────────────────────────────────────
    trend_health, trend_reasons = _classify_trend(
        close=close, sma_200=sma_200,
        sma_50_slope=sma_50_slope, return_252d=return_252d,
    )
    reasons.extend(trend_reasons)

    # ─── Stabilization ────────────────────────────────────────────────
    stabilization, stab_reasons = _classify_stabilization(
        tier_code=tier.tier_code, return_5d=return_5d, rsi_14=rsi_14,
    )
    reasons.extend(stab_reasons)

    # If the tier explicitly requires stabilization and we have no signal,
    # treat unknown as not-ok (refuse to call buyable on missing data).
    if (
        tier.requires_stabilization and stabilization == STAB_UNKNOWN
        and pullback_pct >= tier.visibility_drawdown
    ):
        cautions.append("stabilization_unknown_but_required")

    # ─── Risk/reward (informational; not used in status decision v1) ──
    target_for_rr = peak_252d if peak_252d is not None else high_63d
    rr = _risk_reward(close=close, target=target_for_rr,
                      sma_200=sma_200, atr_14=atr_14)
    if (
        rr is not None and tier.min_risk_reward is not None
        and rr < tier.min_risk_reward
    ):
        cautions.append(f"risk_reward {rr:.2f} below tier floor {tier.min_risk_reward:.2f}")

    # ─── Status assignment ────────────────────────────────────────────
    visibility_th = tier.visibility_drawdown
    buy_zone_th   = tier.buy_zone_drawdown
    deep_th       = tier.deep_drawdown

    if trend_health == TREND_BROKEN:
        status = STATUS_THESIS_BROKEN_REVIEW
    elif pullback_pct >= deep_th and stabilization == STAB_OK:
        status = STATUS_DEEP_PULLBACK_OPPORTUNITY
    elif pullback_pct >= buy_zone_th and stabilization == STAB_OK:
        status = STATUS_BUY_ZONE_ACTIVE
    elif pullback_pct >= visibility_th and stabilization == STAB_NOT_OK:
        status = STATUS_FALLING_KNIFE_WAIT
    elif pullback_pct >= visibility_th:
        # Includes the case where stabilization is unknown — we surface
        # the pullback ("forming") but don't call it buyable.
        status = STATUS_PULLBACK_FORMING
    else:
        status = STATUS_NO_PULLBACK

    return PullbackSignal(
        symbol=tier.symbol,
        asset_kind=tier.asset_kind,
        tier_code=tier.tier_code,
        tier_display_name=tier.tier_display_name,
        status=status,
        display_label=DISPLAY_LABEL[status],
        close=close,
        as_of_date=as_of,
        drawdown_63d=drawdown_63d,
        drawdown_252d=drawdown_252d,
        starter_buy_level=starter,
        better_buy_level=better,
        deep_buy_level=deep,
        trend_health=trend_health,
        stabilization=stabilization,
        risk_reward=rr,
        reasons=reasons,
        cautions=cautions,
    )


def _no_pullback_with(
    tier: WatchlistRow,
    as_of: date | None, close: float | None,
    drawdown_63d: float | None, drawdown_252d: float | None,
    starter: float | None, better: float | None, deep: float | None,
    trend_health: str, stabilization: str, rr: float | None,
    *, reasons: list[str], cautions: list[str],
) -> PullbackSignal:
    """Internal: shorthand for the degraded NO_PULLBACK path."""
    return PullbackSignal(
        symbol=tier.symbol,
        asset_kind=tier.asset_kind,
        tier_code=tier.tier_code,
        tier_display_name=tier.tier_display_name,
        status=STATUS_NO_PULLBACK,
        display_label=DISPLAY_LABEL[STATUS_NO_PULLBACK],
        close=close,
        as_of_date=as_of,
        drawdown_63d=drawdown_63d,
        drawdown_252d=drawdown_252d,
        starter_buy_level=starter,
        better_buy_level=better,
        deep_buy_level=deep,
        trend_health=trend_health,
        stabilization=stabilization,
        risk_reward=rr,
        reasons=reasons,
        cautions=cautions,
    )


# ─────────────────────────────────────────────────────────────────────────
# Batch driver — convenience for the status renderer
# ─────────────────────────────────────────────────────────────────────────

def evaluate_watchlist(
    watchlist: list[WatchlistRow],
    evidence: dict[str, dict[str, Any]],
) -> list[PullbackSignal]:
    """Apply the engine to every watchlist row.

    Pure / deterministic. Preserves the watchlist's incoming order.
    """
    return [compute_pullback_signal(row, evidence.get(row.symbol)) for row in watchlist]
