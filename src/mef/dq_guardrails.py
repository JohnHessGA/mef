"""Defensive downstream guardrails for known UDC data-quality issues.

This module owns temporary protection against the reverse-split-cascade
artifact in ``drawdown_current`` / ``drawdown_max_252d``. See the upstream
investigation report at
``~/repos/udc/docs/peak_252d-investigation-2026-05-19.md``.

Background
----------
Symbols that underwent repeated extreme reverse splits (SMX, WOK, WHLR,
HCTI, NIVF, LRHC at the time of the investigation) carry inflated
``peak_252d`` values in ``shdb.{stock,etf}_volatility_1d``. The mart-layer
``drawdown_current = (adj_close - peak_252d) / peak_252d`` collapses to
≈ -1.0 for those rows even when the symbol is currently trading at a
reasonable price. The legacy formula is mechanically correct given the
vendor-supplied cumulative-split-factor; the resulting drawdown is just
operationally meaningless because the "peak" reflects multiple accumulated
reverse splits.

BRK.A and other legitimately high-priced securities are NOT affected:
their ``drawdown_current`` lands in the normal range (e.g., -0.06).

Temporary nature
----------------
This guardrail is the defensive front-line until UDC adds a
``peak_quality_flag`` column on the volatility tables (analogous to
``beta_quality``). When that lands, consumers should filter on the
upstream flag and these helpers can shrink or retire.

Usage
-----
For ranking / screening / gating / scoring, wrap reads with
:func:`safe_drawdown`. For human-readable display, use
:func:`format_drawdown`. Both leave the raw value alone in the underlying
mart row — the guardrail interprets, it does NOT mutate source data.
"""

from __future__ import annotations

DRAWDOWN_SUSPECT_THRESHOLD = -0.99
"""Drawdowns at or below this threshold are treated as suspect — the
peak_252d that produced them is almost certainly inflated by the
reverse-split-cascade artifact, not a real 99-100% drawdown."""


def is_drawdown_suspect(dd: float | None) -> bool:
    """True when ``dd`` is in the suspect band (≤ ``-0.99``).

    NULL / ``None`` values are NOT suspect — they're separately missing.
    """
    if dd is None:
        return False
    return dd <= DRAWDOWN_SUSPECT_THRESHOLD


def safe_drawdown(dd: float | None) -> float | None:
    """Return ``dd`` if it's a trustworthy signal, else ``None``.

    Use at ranking / screening / gating / scoring sites so a corrupt
    drawdown lands as "missing" rather than as a fake 100%-drawdown
    extreme. Callers that already branch on ``None`` (most do) get
    correct behavior with no other changes.
    """
    if dd is None or is_drawdown_suspect(dd):
        return None
    return dd


def format_drawdown(
    dd: float | None,
    none_text: str = "n/a",
    suspect_text: str = "suspect",
) -> str:
    """Format a drawdown for human-readable display.

    Suspect values render as ``"suspect"`` instead of ``"-100.00%"``;
    ``None`` renders as ``"n/a"``; normal values render as a signed
    percent with 2 decimals.
    """
    if dd is None:
        return none_text
    if is_drawdown_suspect(dd):
        return suspect_text
    return f"{dd * 100:+.2f}%"
