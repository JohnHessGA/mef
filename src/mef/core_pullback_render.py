"""Render the Core Pullback Watchlist section for ``mef status``.

Pure-ish (just formatting). Takes a list of ``PullbackSignal``s and
returns the text lines for the section. Quiet symbols are summarized
as a single count; notable ones are grouped by status in the order
declared in ``mef.core_pullback.NOTABLE_STATUS_ORDER``.
"""

from __future__ import annotations

from mef.core_pullback import (
    DISPLAY_LABEL,
    NOTABLE_STATUS_ORDER,
    NOTABLE_STATUSES,
    PullbackSignal,
    STATUS_BUY_ZONE_ACTIVE,
    STATUS_DEEP_PULLBACK_OPPORTUNITY,
    STATUS_FALLING_KNIFE_WAIT,
    STATUS_PULLBACK_FORMING,
    STATUS_THESIS_BROKEN_REVIEW,
)
from mef.display_format import fmt_dollar_whole, fmt_pct_human


# Statuses for which it would be misleading to render buy levels — the
# headline of the row is "do not buy yet" or "review before buying", so
# numerical entry/scale-in levels would suggest false precision.
_SUPPRESS_LEVELS_STATUSES = {
    STATUS_FALLING_KNIFE_WAIT,
    STATUS_THESIS_BROKEN_REVIEW,
}

# Suffix appended to the reason line when the row would otherwise have
# rendered levels but is being suppressed by status.
_SUPPRESSED_LEVEL_SUFFIX = {
    STATUS_THESIS_BROKEN_REVIEW: " — no buy levels shown",
    STATUS_FALLING_KNIFE_WAIT:   " — wait before setting buy levels",
}


# Per-status safety caps. THESIS / RISK CHANGED rows are context, not
# actionable, so they get a tighter cap — a big selloff cluster
# otherwise dominates the daily report. The other notable buckets
# share the default cap.
_DEFAULT_NOTABLE_CAP = 12
_THESIS_BROKEN_CAP = 5

_NOTABLE_CAP_BY_STATUS = {
    STATUS_THESIS_BROKEN_REVIEW: _THESIS_BROKEN_CAP,
}


# Display headers per status. Slightly more emphatic than the
# lower-case DISPLAY_LABEL, suitable as section headings.
_STATUS_HEADER = {
    STATUS_DEEP_PULLBACK_OPPORTUNITY: "DEEP PULLBACK OPPORTUNITY",
    STATUS_BUY_ZONE_ACTIVE:           "BUY ZONE ACTIVE",
    STATUS_PULLBACK_FORMING:          "PULLBACK FORMING",
    STATUS_FALLING_KNIFE_WAIT:        "FALLING KNIFE — WAIT",
    STATUS_THESIS_BROKEN_REVIEW:      "THESIS / RISK CHANGED",
}


def render_section(signals: list[PullbackSignal]) -> list[str]:
    """Return the rendered section as a list of text lines (no trailing blank)."""
    if not signals:
        return [
            "CORE PULLBACK WATCHLIST",
            "=======================",
            "  (no watchlist symbols loaded)",
        ]

    by_status: dict[str, list[PullbackSignal]] = {s: [] for s in NOTABLE_STATUS_ORDER}
    quiet = 0
    for sig in signals:
        if sig.status in NOTABLE_STATUSES:
            by_status[sig.status].append(sig)
        else:
            quiet += 1

    lines: list[str] = [
        "CORE PULLBACK WATCHLIST",
        "=======================",
    ]
    notable_total = sum(len(v) for v in by_status.values())
    if notable_total == 0:
        lines.append(f"  All {len(signals)} watchlist symbols are quiet today (no meaningful pullback).")
        return lines

    for status in NOTABLE_STATUS_ORDER:
        bucket = by_status[status]
        if not bucket:
            continue
        lines.append("")
        lines.append(_STATUS_HEADER[status])
        # Sort within bucket: deepest pullback first (most negative drawdown_252d,
        # falling back to drawdown_63d, then symbol).
        bucket.sort(key=_sort_key_deepest_first)
        cap = _NOTABLE_CAP_BY_STATUS.get(status, _DEFAULT_NOTABLE_CAP)
        if len(bucket) > cap:
            shown = bucket[:cap]
            hidden = len(bucket) - cap
        else:
            shown = bucket
            hidden = 0
        for sig in shown:
            lines.extend(_format_signal_block(sig))
        if hidden:
            lines.append(f"  …and {hidden} more in this bucket.")

    lines.append("")
    lines.append("QUIET")
    if quiet:
        lines.append(f"  {quiet} watchlist symbols have no meaningful pullback today.")
    else:
        lines.append("  (none — everything is on the notable list above.)")
    return lines


def _sort_key_deepest_first(sig: PullbackSignal) -> tuple[float, float, str]:
    # None drawdowns sort last (treat as 0.0 so they don't claim "deepest").
    dd252 = sig.drawdown_252d if sig.drawdown_252d is not None else 0.0
    dd63  = sig.drawdown_63d  if sig.drawdown_63d  is not None else 0.0
    return (dd252, dd63, sig.symbol)


def _format_signal_block(sig: PullbackSignal) -> list[str]:
    """Two-line block per notable signal: header (symbol + levels) + reason."""
    head = f"  {sig.symbol:<6} {fmt_dollar_whole(sig.close)}"

    if sig.status not in _SUPPRESS_LEVELS_STATUSES:
        displayable = _displayable_levels(sig)
        if displayable:
            head = f"{head}  " + " · ".join(
                f"{label} {fmt_dollar_whole(v)}" for label, v in displayable
            )

    reason = _compose_reason_line(sig)
    return [head, f"        {reason}"]


def _displayable_levels(sig: PullbackSignal) -> list[tuple[str, float]]:
    """Return (label, value) pairs in display order, with safety filters
    and context-aware labels.

    Filters:
    1. Drop any level that is not strictly below ``close``. A "buy level"
       at or above the current price reads as "buy at a higher price",
       which is nonsense for a pullback report.
    2. Drop any level that breaks the natural monotone descent
       starter > better > deep. The three levels can use different
       anchors (high_63d vs recovered peak_252d) and occasionally land
       out of order — better to suppress the misleading one than to
       label it with anchor-context that doesn't help a quick scan.

    Labeling:
    - If the lone survivor is the original ``deep`` level (starter and
      better both above close, so price has already moved past the
      normal buy zone), relabel it as ``"deeper add"``. A bare ``deep``
      next to a current price reads ambiguously; ``deeper add`` signals
      "we're already past the normal zone — this is the add-lower level".
    """
    close = sig.close
    if close is None:
        return []

    raw = [
        ("starter", sig.starter_buy_level),
        ("better",  sig.better_buy_level),
        ("deep",    sig.deep_buy_level),
    ]
    candidates = [(label, float(v)) for label, v in raw
                  if v is not None and float(v) < close]

    # Enforce strictly descending values across the kept labels.
    out: list[tuple[str, float]] = []
    prev = float("inf")
    for label, value in candidates:
        if value < prev:
            out.append((label, value))
            prev = value
        # else: drop this level — keeps the rendered set monotone.

    # Relabel a lone-surviving "deep" → "deeper add". Three- and
    # two-element sets keep their original labels because the context
    # of starter/better next to deep is self-explanatory.
    if len(out) == 1 and out[0][0] == "deep":
        return [("deeper add", out[0][1])]
    return out


def _compose_reason_line(sig: PullbackSignal) -> str:
    """Short human-readable line summarizing the why for this status."""
    pieces: list[str] = []

    # Headline pullback magnitude — pick the deeper of the two horizons.
    # The engine's threshold check uses the deeper drawdown, so the
    # rendered "down X%" should match what triggered the status.
    dd63 = sig.drawdown_63d
    dd252 = sig.drawdown_252d
    if dd63 is not None and dd252 is not None:
        if dd252 < dd63:
            pieces.append(f"down {fmt_pct_human(dd252)} from 252d high")
        else:
            pieces.append(f"down {fmt_pct_human(dd63)} from 63d high")
    elif dd63 is not None:
        pieces.append(f"down {fmt_pct_human(dd63)} from 63d high")
    elif dd252 is not None:
        pieces.append(f"down {fmt_pct_human(dd252)} from 252d high")

    # Trend / stabilization headline.
    #
    # For BUY_ZONE_ACTIVE and DEEP_PULLBACK_OPPORTUNITY we explicitly
    # tell the reader that the current price has already crossed below
    # the relevant threshold. The status itself is the assertion (the
    # engine sets it on `pullback_pct >= threshold`), so the wording is
    # safe to add unconditionally — and it explains why some levels are
    # absent from the header line.
    if sig.status == STATUS_THESIS_BROKEN_REVIEW:
        pieces.append("long-term trend broken")
    elif sig.status == STATUS_FALLING_KNIFE_WAIT:
        pieces.append("stabilization not confirmed")
    elif sig.status == STATUS_DEEP_PULLBACK_OPPORTUNITY:
        pieces.append("current price is already beyond deep pullback threshold")
        pieces.append("trend intact")
    elif sig.status == STATUS_BUY_ZONE_ACTIVE:
        pieces.append("current price is already in the buy zone")
        pieces.append("trend intact")
    elif sig.status == STATUS_PULLBACK_FORMING:
        if sig.stabilization == "unknown":
            pieces.append("stabilization unclear — still developing")
        else:
            pieces.append("still above preferred buy zone")

    # Data-quality cautions are intentionally NOT rendered in the default
    # report — they would clutter a section that's read for action, not
    # for plumbing health. The cautions remain on the PullbackSignal
    # dataclass for a future details / debug view.

    line = "; ".join(pieces) if pieces else sig.display_label
    return line + _SUPPRESSED_LEVEL_SUFFIX.get(sig.status, "")
