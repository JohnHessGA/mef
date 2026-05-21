"""Unit tests for mef.display_format — the small shared display helpers."""

from __future__ import annotations

from mef.display_format import fmt_dollar_whole, fmt_pct_human


# ─────────────────────────────────────────────────────────────────────────
# fmt_dollar_whole
# ─────────────────────────────────────────────────────────────────────────

def test_dollar_whole_rounds_to_nearest():
    assert fmt_dollar_whole(161.19) == "$161"
    assert fmt_dollar_whole(152.23) == "$152"
    assert fmt_dollar_whole(133.30) == "$133"
    assert fmt_dollar_whole(133.50) == "$134"   # bank-round: 134 (round-half-to-even)
    assert fmt_dollar_whole(0.49)   == "$0"
    assert fmt_dollar_whole(0.51)   == "$1"


def test_dollar_whole_thousands_separator():
    assert fmt_dollar_whole(1234.56) == "$1,235"
    assert fmt_dollar_whole(1_000_000.0) == "$1,000,000"


def test_dollar_whole_handles_missing():
    assert fmt_dollar_whole(None) == "$?"
    assert fmt_dollar_whole("not a number") == "$?"   # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────
# fmt_pct_human
# ─────────────────────────────────────────────────────────────────────────

def test_pct_human_rounds_to_whole_percent_at_or_above_one():
    assert fmt_pct_human(-0.209) == "21%"
    assert fmt_pct_human(0.132)  == "13%"
    assert fmt_pct_human(0.064)  == "6%"
    assert fmt_pct_human(-0.359) == "36%"   # the TTD example
    # Python's round() is banker's rounding (round-half-to-even). That's
    # acceptable here — the helper just needs to be deterministic, not
    # arithmetically-canonical.
    assert fmt_pct_human(0.045) == "4%"


def test_pct_human_below_one_percent_uses_less_than_phrase():
    assert fmt_pct_human(-0.007) == "less than 1%"
    assert fmt_pct_human(0.0099) == "less than 1%"
    assert fmt_pct_human(0.0)    == "less than 1%"


def test_pct_human_handles_missing():
    assert fmt_pct_human(None) == "?"
    assert fmt_pct_human("nope") == "?"        # type: ignore[arg-type]


def test_pct_human_strips_sign():
    """Direction ("down X%") is the caller's job; the helper returns magnitude."""
    assert fmt_pct_human(-0.21).lstrip().startswith("21")
    assert fmt_pct_human(0.21).lstrip().startswith("21")
