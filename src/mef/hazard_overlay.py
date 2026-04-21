"""Layer B — hazard overlay.

Computes **penalty-only** conviction adjustments for cross-cutting risks
the engine thesis can't see on its own. The overlay never invalidates a
thesis; it reduces *act-today* confidence.

Families (Phase 1 + 2):

  macro
    High-impact US macro release today or tomorrow. The penalty is
    decomposed as:

        penalty = base_event[event_type] * symbol_multiplier * engine_multiplier

    where only the four ``base_event`` values are tunable and the two
    multipliers are *derived* from existing data (sector / ETF role,
    engine holding horizon). This preserves full expressiveness without
    pretending all 48 combinations are independently learnable.

  earnings_proximity
    The 6–21d trend-earnings zone, previously a mix of soft penalties
    and secondary veto inside the trend scorer. Layer A still vetoes
    0–5d for trend (and 0–10d for mean_reversion / value); earnings_
    proximity handles the band past the blackout — applied to trend only
    since mean_rev / value are already blocked up through day 10.

Combination rule (user decision 2026-04-21):

  - within a family: take the MAX applicable penalty
  - across families: SUM the per-family penalties
  - cap the total at ``cap`` (default 0.10)

So FOMC tomorrow AND earnings 8 days out on a trend candidate stacks
macro + earnings_proximity, clamped at the cap.

The overlay returns a ``HazardOverlayResult`` that the pipeline writes
verbatim onto ``mef.candidate`` so audit queries can decompose why a
final conviction differs from raw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# ─── Defaults (overridable via config/mef.yaml :: ranker.hazard_overlay) ───

# Tunable — revisit only when closed-rec evidence supports a move.
DEFAULT_MACRO_BASE = {
    "fomc":  0.07,
    "cpi":   0.06,
    "pce":   0.06,
    "nfp":   0.05,
    "other": 0.03,
}

# Derived from symbol metadata — do not treat as a free parameter.
DEFAULT_SYMBOL_MULTIPLIERS = {
    "broad_index":    1.25,   # SPY, QQQ, IWM, DIA
    "rate_sensitive": 1.15,   # financials, utilities, real estate, homebuilders
    "defensive":      0.85,   # staples, healthcare
    "default":        1.00,
}

# Derived from engine holding horizon (trend/mean_rev ≈ 30d, value = 60d).
DEFAULT_ENGINE_MULTIPLIERS = {
    "trend":          1.00,
    "mean_reversion": 1.00,
    "value":          0.60,
}

# Earnings-proximity (trend only). The pre-layering scorer used:
#   6-10d: -0.15 penalty  →  here 0.08 (hazard cap 0.10 bounds stacking)
#   11-21d: -0.03 caution →  here 0.03
DEFAULT_EARN_PROX_TREND = {
    "days_6_to_10":  0.08,
    "days_11_to_21": 0.03,
}

# Broad-index / defensive / rate-sensitive buckets reference existing
# symbol metadata. Broad-index ETFs are identified by symbol; sectors map
# through to rate-sensitive / defensive / default buckets.
BROAD_INDEX_SYMBOLS = frozenset({"SPY", "QQQ", "IWM", "DIA"})
RATE_SENSITIVE_SECTORS = frozenset({
    "Financial Services", "Utilities", "Real Estate",
})
# Industry-level match for homebuilders, since UDC's sector for them is
# Consumer Cyclical (too broad to bucket as rate-sensitive wholesale).
RATE_SENSITIVE_INDUSTRIES = frozenset({
    "Residential Construction",
    "Home Improvement Retail",
})
DEFENSIVE_SECTORS = frozenset({
    "Consumer Defensive", "Healthcare",
})

DEFAULT_CAP = 0.10


@dataclass(frozen=True)
class HazardOverlayResult:
    """Structured decomposition of the hazard adjustment applied to raw conviction.

    All penalties are non-negative magnitudes — the caller subtracts
    ``total`` from raw_conviction. Zero values mean "the overlay looked
    at this and found nothing."
    """
    total:             float                  # sum of components, capped
    macro:             float = 0.0
    earnings_prox:     float = 0.0
    event_type:        str | None = None       # drives macro penalty, e.g. "fomc"
    flags:             list[str] = field(default_factory=list)   # short tags
    notes:             list[str] = field(default_factory=list)   # human-readable


# ─── Event classification (name-matching against shdb.economic_calendar) ───

def _classify_event(event_name: str) -> str:
    """Map an economic_calendar.event string onto one of the base buckets.

    Deliberately narrow: anything that isn't a recognized top-tier
    release falls through as ``other``. This keeps the ``other`` bucket
    from becoming a catch-all for routine data drops.
    """
    name = (event_name or "").lower()
    if "fomc" in name or "federal funds" in name or "fed decision" in name:
        return "fomc"
    if "cpi" in name:
        return "cpi"
    if "pce" in name:
        return "pce"
    if "nonfarm" in name or name.strip() == "payrolls":
        return "nfp"
    # GDP / ISM / Retail Sales / similar → "other" tier.
    if any(k in name for k in (
        "gdp", "ism", "retail sales", "durable goods",
        "ppi", "consumer confidence",
    )):
        return "other"
    return "other"


def _symbol_bucket(row: dict[str, Any]) -> str:
    """Derive the sensitivity bucket for a symbol from evidence metadata."""
    if row.get("asset_kind") == "etf":
        symbol = row.get("symbol") or ""
        if symbol in BROAD_INDEX_SYMBOLS:
            return "broad_index"
        # Sector ETFs (XLF, XLU, XLRE) would be caught below via a
        # sector-matching table, but ETF rows don't carry sector — gate
        # on symbol instead.
        if symbol in ("XLF", "XLU", "XLRE"):
            return "rate_sensitive"
        if symbol in ("XLP", "XLV"):
            return "defensive"
        return "default"

    sector = row.get("sector")
    industry = row.get("industry")
    if sector in RATE_SENSITIVE_SECTORS or industry in RATE_SENSITIVE_INDUSTRIES:
        return "rate_sensitive"
    if sector in DEFENSIVE_SECTORS:
        return "defensive"
    return "default"


# ─── Family: macro ───

def _macro_penalty(
    row: dict[str, Any],
    baseline: dict[str, Any],
    engine: str,
    today: date,
    *,
    base: dict[str, float],
    symbol_multipliers: dict[str, float],
    engine_multipliers: dict[str, float],
) -> tuple[float, str | None, list[str], list[str]]:
    """Return (penalty, event_type, flags, notes) for the macro family.

    Rule: scan upcoming high-impact events in the 0–1 day window from
    the bar date, classify each, compute
    ``base[event_type] * symbol_mult * engine_mult`` per event, and take
    the MAX. Stacking multiple events in the same window would be jumpy;
    the max keeps the overlay calm.
    """
    events = baseline.get("upcoming_high_impact_events") or []
    if not events:
        return 0.0, None, [], []

    bar_date = row.get("bar_date") or today
    sym_mult = symbol_multipliers.get(_symbol_bucket(row), symbol_multipliers.get("default", 1.00))
    eng_mult = engine_multipliers.get(engine, 1.00)

    best_penalty = 0.0
    best_event: str | None = None
    best_event_name: str | None = None
    for ev in events:
        days_to_ev = (ev["date"] - bar_date).days
        if not (0 <= days_to_ev <= 1):
            continue
        event_type = _classify_event(ev["event"])
        base_pen = base.get(event_type, base.get("other", 0.0))
        penalty = round(base_pen * sym_mult * eng_mult, 4)
        if penalty > best_penalty:
            best_penalty = penalty
            best_event = event_type
            best_event_name = ev["event"]

    if best_penalty <= 0 or best_event is None:
        return 0.0, None, [], []

    flags = [f"macro:{best_event}"]
    notes = [
        f"macro hazard {best_event_name} ({best_event}) → "
        f"−{best_penalty:.3f} "
        f"(symbol_mult={sym_mult:.2f}, engine_mult={eng_mult:.2f})"
    ]
    return best_penalty, best_event, flags, notes


# ─── Family: earnings_proximity (trend only) ───

def _earnings_proximity_penalty(
    row: dict[str, Any],
    engine: str,
    today: date,
    *,
    trend_table: dict[str, float],
) -> tuple[float, list[str], list[str]]:
    """Return (penalty, flags, notes) for the earnings-proximity family.

    Applies only to the trend engine. Mean-rev and value block 0–10d at
    Layer A, so their 11–21d band would also qualify in principle, but
    the user's decision scoped this hazard to trend.
    """
    if engine != "trend" or row.get("asset_kind") != "stock":
        return 0.0, [], []
    next_earn = row.get("next_earnings_date")
    if next_earn is None:
        return 0.0, [], []

    bar_date = row.get("bar_date") or today
    days_to_earn = (next_earn - bar_date).days
    if 6 <= days_to_earn <= 10:
        pen = trend_table.get("days_6_to_10", 0.0)
        return pen, [f"earn_prox:6-10d"], [
            f"earnings-proximity hazard: {days_to_earn}d out (6-10d band) → −{pen:.3f}"
        ]
    if 11 <= days_to_earn <= 21:
        pen = trend_table.get("days_11_to_21", 0.0)
        return pen, [f"earn_prox:11-21d"], [
            f"earnings-proximity hazard: {days_to_earn}d out (11-21d band) → −{pen:.3f}"
        ]
    return 0.0, [], []


# ─── Public entry point ───

def compute(
    row: dict[str, Any],
    baseline: dict[str, Any],
    *,
    engine: str,
    today: date | None = None,
    config: dict[str, Any] | None = None,
) -> HazardOverlayResult:
    """Compute the hazard overlay for one (symbol, engine) pair.

    ``config`` is the ``ranker.hazard_overlay`` block from ``mef.yaml``
    (may be absent — defaults kick in). Expected shape:

        hazard_overlay:
          cap: 0.10
          macro:
            base: {fomc: 0.07, cpi: 0.06, pce: 0.06, nfp: 0.05, other: 0.03}
            symbol_multipliers: {broad_index: 1.25, rate_sensitive: 1.15,
                                 defensive: 0.85, default: 1.00}
            engine_multipliers: {trend: 1.00, mean_reversion: 1.00, value: 0.60}
          earnings_proximity:
            trend: {days_6_to_10: 0.08, days_11_to_21: 0.03}
    """
    cfg = config or {}
    today = today or date.today()

    macro_cfg = cfg.get("macro") or {}
    base = {**DEFAULT_MACRO_BASE, **(macro_cfg.get("base") or {})}
    sym_mult = {**DEFAULT_SYMBOL_MULTIPLIERS, **(macro_cfg.get("symbol_multipliers") or {})}
    eng_mult = {**DEFAULT_ENGINE_MULTIPLIERS, **(macro_cfg.get("engine_multipliers") or {})}

    ep_cfg = (cfg.get("earnings_proximity") or {}).get("trend") or {}
    ep_trend = {**DEFAULT_EARN_PROX_TREND, **ep_cfg}

    cap = float(cfg.get("cap", DEFAULT_CAP))

    macro_pen, event_type, macro_flags, macro_notes = _macro_penalty(
        row, baseline, engine, today,
        base=base, symbol_multipliers=sym_mult, engine_multipliers=eng_mult,
    )
    ep_pen, ep_flags, ep_notes = _earnings_proximity_penalty(
        row, engine, today, trend_table=ep_trend,
    )

    # Sum across families, cap the total. Components remain stored at
    # their uncapped value so audit can see what each family contributed
    # before the cap bit.
    total = round(min(macro_pen + ep_pen, cap), 4)

    flags = macro_flags + ep_flags
    notes = macro_notes + ep_notes
    if (macro_pen + ep_pen) > cap:
        notes.append(f"hazard total clamped at cap {cap:.2f}")

    return HazardOverlayResult(
        total=total,
        macro=round(macro_pen, 4),
        earnings_prox=round(ep_pen, 4),
        event_type=event_type,
        flags=flags,
        notes=notes,
    )
