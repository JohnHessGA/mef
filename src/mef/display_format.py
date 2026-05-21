"""Small shared display formatters for the human-readable MEF reports.

Internal calculations stay precise (the dataclasses carry floats). These
helpers exist so report output looks clean and scan-friendly:

- ``fmt_dollar_whole``  — whole dollars, no cents
- ``fmt_pct_human``     — whole percent at ≥1%, "less than 1%" below

Use in the rendering layer only. Never use these to round values you
intend to persist or compare against thresholds.
"""

from __future__ import annotations


def fmt_dollar_whole(v: float | None, *, missing: str = "$?") -> str:
    """Round to the nearest whole dollar, no cents, with thousands separator.

    >>> fmt_dollar_whole(161.19)
    '$161'
    >>> fmt_dollar_whole(1234.56)
    '$1,235'
    >>> fmt_dollar_whole(None)
    '$?'
    """
    if v is None:
        return missing
    try:
        return f"${round(float(v)):,d}"
    except (TypeError, ValueError):
        return missing


def fmt_pct_human(v: float | None, *, missing: str = "?") -> str:
    """Format a fractional value as a human-readable percent.

    Magnitude ≥1% → whole percent ("21%"). Magnitude <1% → "less than 1%".
    Sign is dropped — callers compose the direction ("down X%", "up X%").

    >>> fmt_pct_human(-0.209)
    '21%'
    >>> fmt_pct_human(0.132)
    '13%'
    >>> fmt_pct_human(-0.007)
    'less than 1%'
    >>> fmt_pct_human(None)
    '?'
    """
    if v is None:
        return missing
    try:
        pct = abs(float(v)) * 100.0
    except (TypeError, ValueError):
        return missing
    if pct < 1.0:
        return "less than 1%"
    return f"{round(pct)}%"
