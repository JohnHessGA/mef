"""Layer A — universal eligibility gate.

Answers only one question: *should MEF even consider this symbol today?*

Layer A is intentionally narrow. It rejects symbols that are untrustworthy
or outside MEF policy — not symbols whose thesis looks weak, not symbols
whose tape conditions look nervous. Those belong to Layer C (per-engine
thesis) and Layer B (hazard overlay) respectively.

Current Layer A rules:
  1. Universe membership — already enforced by ``evidence._fetch_universe_symbols``
  2. Data presence — the symbol produced an evidence row with a close
  3. Earnings blackout — no announcement inside the engine-specific window

Per-engine earnings windows (kept at their current values to preserve
the pre-layering behavior):

  - trend:          5 calendar days
  - mean_reversion: 10 calendar days
  - value:          10 calendar days

The wider 10-day "pullback veto" that lived inside the trend scorer is
NOT preserved here — it is handled as an earnings-proximity hazard in
Layer B, which is the correct shape for an "act-today confidence"
adjustment (the user's decision in the 2026-04-21 layered-gating spec).

Liquidity and distress rules are reserved for Layer A but not yet
implemented — MEF's universe is already curated, and adding those checks
without concrete failure cases would be speculative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# Per-engine earnings-blackout windows in calendar days. See module
# docstring for rationale. Values match the pre-layering scorer windows
# so Phase 1 intentionally does not change behavior here.
EARNINGS_WINDOW_DAYS = {
    "trend":          5,
    "mean_reversion": 10,
    "value":          10,
}


@dataclass(frozen=True)
class EligibilityResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _earnings_blackout(
    row: dict[str, Any], engine: str, today: date,
) -> str | None:
    """Return a short reason string if the earnings blackout applies; else None.

    ETFs and stocks without an upcoming earnings date are always eligible
    on this rule. Stocks with ``next_earnings_date`` inside the engine's
    window get blocked.
    """
    if row.get("asset_kind") != "stock":
        return None
    next_earn = row.get("next_earnings_date")
    if next_earn is None:
        return None
    window = EARNINGS_WINDOW_DAYS.get(engine)
    if window is None:
        return None
    bar_date = row.get("bar_date") or today
    days_to_earn = (next_earn - bar_date).days
    if 0 <= days_to_earn <= window:
        return f"earnings in {days_to_earn}d (≤{window}d blackout for {engine})"
    return None


def check(
    symbol: str,
    row: dict[str, Any] | None,
    *,
    engine: str,
    today: date | None = None,
) -> EligibilityResult:
    """Evaluate Layer A for one (symbol, engine) pair.

    ``row`` is the evidence dict for the symbol (``None`` when the symbol
    has no mart coverage at all). Callers upstream have already enforced
    universe membership, so this function focuses on data presence and
    earnings.
    """
    reasons: list[str] = []
    today = today or date.today()

    # Data presence. A missing row or a row without a close means we have
    # nothing to score against. Record the fail so the daily_run still
    # counts the symbol as evaluated.
    if row is None:
        reasons.append("no mart evidence row")
    elif row.get("close") is None:
        reasons.append("evidence row present but close is null")

    # Earnings blackout — engine-aware window.
    if row is not None:
        earn_reason = _earnings_blackout(row, engine, today)
        if earn_reason:
            reasons.append(earn_reason)

    return EligibilityResult(passed=not reasons, reasons=reasons)
