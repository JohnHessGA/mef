"""MEF Job 1 — Entry Quality Overlay v1 (deterministic).

Single production rule, derived from the RSE entry-quality interaction
research (commit eeeb537 onward) and the NDAQ/OXY diagnosis. Demotes
trend-engine, LLM-approved candidates that match the three-way weak-
entry shape from "Actionable Stock Ideas" to "Watch / Poor Entry
Quality" — never a hard reject.

The shape:
    risk_reward       < 1.5
AND return_63d        > 0.20      (i.e. >20% trailing-quarter run)
AND drawdown_current  > -0.05     (i.e. <5% pullback from recent peak)

The research found this combination of three weak signals is the most
reliable predictor of a weak forward outcome at the cohort level. None
of the three is treated as a standalone veto — only their conjunction.

Boundaries (per the implementation spec):
- No LLM. No CIA. No network calls. Pure function over (plan, features).
- Not a veto. The candidate remains in the lifecycle, paper/shadow scoring
  still happens; only the Actionable/Watch routing changes.
- High extension from SMA200 and negative FCF are display-only flags;
  they do NOT route. See the RSE research notes for why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────
# Status vocabulary — must match the CHECK constraint added in
# sql/mefdb/015_entry_quality.sql.
# ─────────────────────────────────────────────────────────────────────────

STATUS_PASS  = "pass"
STATUS_WATCH = "watch"

# Only the routing flag. Additional flags are display-only and listed
# below for callers that want to surface them; they do NOT cause routing
# changes in v1.
FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK = "STRONG_RUN_WEAK_RR_NO_PULLBACK"

# Display-only (informational). Set when the relevant condition holds,
# even if the routing flag is not triggered.
FLAG_WEAK_RISK_REWARD       = "WEAK_RISK_REWARD"
FLAG_NEGATIVE_FCF           = "NEGATIVE_FCF"
FLAG_EXTENDED_FROM_SMA200   = "EXTENDED_FROM_SMA200"

# Thresholds — the routing rule.
_RR_THRESHOLD              = 1.5
_RETURN_63D_THRESHOLD      = 0.20
_DRAWDOWN_PULLBACK_FLOOR   = -0.05      # > -0.05 means "less than 5% pullback"

# Display-flag thresholds (informational).
_EXTENSION_SMA200_DISPLAY  = 0.20


_ENTRY_ZONE_RE = re.compile(r"\$([0-9.]+)\s*-\s*\$([0-9.]+)")


# ─────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EntryQualityResult:
    """Verdict for one candidate. Persisted to mef.candidate by the pipeline."""
    status: str                     # 'pass' | 'watch'
    flags: list[str] = field(default_factory=list)
    summary: str | None = None
    risk_reward: float | None = None
    return_63d: float | None = None
    drawdown_current: float | None = None

    @property
    def is_watch(self) -> bool:
        return self.status == STATUS_WATCH


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _entry_mid(entry_zone: str | None) -> float | None:
    """Extract the midpoint of a "$lo-$hi" entry zone string."""
    if not entry_zone:
        return None
    m = _ENTRY_ZONE_RE.search(entry_zone)
    if not m:
        return None
    try:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    except ValueError:
        return None


def _risk_reward(
    *, entry_zone: str | None, stop: float | None, target: float | None,
) -> float | None:
    """(target - entry_mid) / (entry_mid - stop). Same geometry as the research."""
    mid = _entry_mid(entry_zone)
    if mid is None or stop is None or target is None:
        return None
    try:
        risk = mid - float(stop)
        if risk <= 0:
            return None
        return (float(target) - mid) / risk
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────
# Evaluator
# ─────────────────────────────────────────────────────────────────────────

def evaluate_entry_quality(
    *,
    entry_zone: str | None,
    stop: float | None,
    target: float | None,
    features: dict[str, Any],
) -> EntryQualityResult:
    """Apply the v1 three-way routing rule + collect display flags.

    Missing data is safe: when risk_reward can't be computed (no plan,
    unparseable entry zone, missing stop/target, or non-positive risk),
    the status is ``pass`` — Entry Quality Overlay is a demoter, not a
    sanity gate. The Layer-A eligibility check upstream is the right
    place to refuse candidates without plans.
    """
    rr               = _risk_reward(entry_zone=entry_zone, stop=stop, target=target)
    return_63d       = _as_float(features.get("return_63d"))
    drawdown_current = _as_float(features.get("drawdown_current"))
    free_cash_flow   = _as_float(features.get("free_cash_flow"))
    close            = _as_float(features.get("close"))
    sma_200          = _as_float(features.get("sma_200"))

    flags: list[str] = []

    # Display-only flags (do NOT cause routing changes).
    if rr is not None and rr < _RR_THRESHOLD:
        flags.append(FLAG_WEAK_RISK_REWARD)
    if free_cash_flow is not None and free_cash_flow < 0:
        flags.append(FLAG_NEGATIVE_FCF)
    if close is not None and sma_200 is not None and sma_200 > 0:
        if (close - sma_200) / sma_200 > _EXTENSION_SMA200_DISPLAY:
            flags.append(FLAG_EXTENDED_FROM_SMA200)

    # The single routing rule. All three must be true. Missing data on any
    # of the three → cannot be a watch (must be pass).
    routes_to_watch = (
        rr is not None and rr < _RR_THRESHOLD
        and return_63d is not None and return_63d > _RETURN_63D_THRESHOLD
        and drawdown_current is not None and drawdown_current > _DRAWDOWN_PULLBACK_FLOOR
    )

    if routes_to_watch:
        flags.insert(0, FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK)
        summary = (
            "Strong trend, but poor entry quality: weak risk/reward after a "
            "large 63d run with little pullback."
        )
        status = STATUS_WATCH
    else:
        summary = None
        status = STATUS_PASS

    return EntryQualityResult(
        status=status,
        flags=flags,
        summary=summary,
        risk_reward=rr,
        return_63d=return_63d,
        drawdown_current=drawdown_current,
    )
