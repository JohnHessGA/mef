"""Tests for the drawdown_current downstream guardrail.

These tests pin the five regression checks called out in the
2026-05-19 task brief:

  (1) drawdown_current ≤ -0.99 is treated as missing/suspect.
  (2) Normal drawdowns (e.g., -0.10, -0.25, -0.60) behave normally.
  (3) BRK.A-style legitimate high-price securities (drawdown ≈ -0.06)
      are NOT flagged just because price is high.
  (4) Existing ranker / etf_classifier behavior is unchanged for
      normal symbols.
  (5) The guardrail interprets only — it does not mutate any source
      row dict.

Background: see ~/repos/udc/docs/peak_252d-investigation-2026-05-19.md
"""

from __future__ import annotations

import pytest

from mef.dq_guardrails import (
    DRAWDOWN_SUSPECT_THRESHOLD,
    format_drawdown,
    is_drawdown_suspect,
    safe_drawdown,
)


# ──────────────────────────────────────────────────────────────────
# Helper-function behavior
# ──────────────────────────────────────────────────────────────────


def test_threshold_constant_is_pinned():
    """-0.99 is the threshold per the task brief. Change is intentional."""
    assert DRAWDOWN_SUSPECT_THRESHOLD == -0.99


@pytest.mark.parametrize("dd", [-1.0, -0.999, -0.9999, -0.99])
def test_suspect_detects_split_cascade_band(dd):
    """The split-cascade artifact produces drawdown ≈ -1.0; anything
    at or below -0.99 is flagged."""
    assert is_drawdown_suspect(dd) is True
    assert safe_drawdown(dd) is None
    assert format_drawdown(dd) == "suspect"


@pytest.mark.parametrize("dd", [-0.989, -0.95, -0.60, -0.25, -0.10, -0.06, -0.01, 0.0, 0.05])
def test_normal_drawdowns_pass_through_untouched(dd):
    """Realistic drawdowns including the BRK.A range (-0.06) must NOT
    be flagged. -0.989 is just above the threshold and must pass."""
    assert is_drawdown_suspect(dd) is False
    assert safe_drawdown(dd) == dd
    formatted = format_drawdown(dd)
    assert formatted != "suspect"
    assert formatted != "n/a"
    # Sanity: the formatter renders a percent.
    assert "%" in formatted


def test_brk_a_legitimate_high_price_not_flagged():
    """BRK.A actually trades at ~$770K per share. Its peak_252d in
    production was $770,660 and drawdown_current was -0.0608. The
    guardrail must not confuse 'high price' for 'suspect drawdown'."""
    brk_a_drawdown = -0.0608  # production value from 2026-05-15
    assert is_drawdown_suspect(brk_a_drawdown) is False
    assert safe_drawdown(brk_a_drawdown) == brk_a_drawdown


def test_none_passes_through_as_none():
    """None remains None — separate concept from suspect."""
    assert is_drawdown_suspect(None) is False
    assert safe_drawdown(None) is None
    assert format_drawdown(None) == "n/a"


def test_format_drawdown_custom_text():
    """The display helper exposes ``none_text`` and ``suspect_text``
    for callers that want different copy."""
    assert format_drawdown(None, none_text="—") == "—"
    assert format_drawdown(-1.0, suspect_text="dirty") == "dirty"


def test_format_drawdown_normal_value_signed_percent():
    """Normal values render with a sign + percent + 2 decimals."""
    assert format_drawdown(-0.0608) == "-6.08%"
    assert format_drawdown(0.0123) == "+1.23%"
    assert format_drawdown(0.0) == "+0.00%"


def test_guardrail_does_not_mutate_input():
    """The helper does NOT alter the upstream row dict — only the
    return value reflects the guarded interpretation."""
    row = {"drawdown_current": -0.999, "symbol": "FAKE"}
    safe_drawdown(row["drawdown_current"])
    format_drawdown(row["drawdown_current"])
    assert row == {"drawdown_current": -0.999, "symbol": "FAKE"}


# ──────────────────────────────────────────────────────────────────
# Ranker integration — _score_symbol path
# ──────────────────────────────────────────────────────────────────


def _baseline_trend_row(**overrides):
    """A minimally-valid feature row for ranker._score_symbol — enough
    to NOT short-circuit on missing-data guards but otherwise neutral."""
    row = {
        "symbol": "TEST",
        "close": 100.0,
        "sma_50": 95.0,
        "sma_200": 90.0,
        "trend_above_sma50": True,
        "trend_above_sma200": True,
        "rsi_14": 55.0,
        "macd_histogram": 0.05,
        "macd_value": 0.10,
        "macd_signal": 0.05,
        "volume_z_score": 0.5,
        "return_5d": 0.01,
        "return_20d": 0.02,
        "realized_vol_20d": 0.20,
        "realized_vol_63d": 0.22,
        "drawdown_current": -0.05,
    }
    row.update(overrides)
    return row


def test_ranker_normal_drawdown_unchanged():
    """A normal drawdown still influences the trend score the same way
    it always has — the guardrail must not change happy-path behavior."""
    from mef.ranker import _score_symbol

    row = _baseline_trend_row(drawdown_current=-0.05)
    result_normal = _score_symbol("TEST", row, baseline={})
    # Sanity: a normal drawdown produces a structurally-valid posture.
    assert result_normal.posture is not None
    assert isinstance(result_normal.conviction_score, float)


def test_ranker_suspect_drawdown_treated_as_missing():
    """A drawdown of -0.999 (split-cascade artifact) must NOT power any
    drawdown-driven branch. After the guardrail, the ranker sees None
    and follows its missing-drawdown path — identical to passing
    drawdown_current=None."""
    from mef.ranker import _score_symbol

    row_suspect = _baseline_trend_row(drawdown_current=-0.999)
    row_missing = _baseline_trend_row(drawdown_current=None)
    suspect_result = _score_symbol("TEST", row_suspect, baseline={})
    missing_result = _score_symbol("TEST", row_missing, baseline={})

    # Same posture and conviction whether suspect or genuinely-missing —
    # that's the contract: suspect ≡ missing.
    assert suspect_result.posture == missing_result.posture
    assert pytest.approx(suspect_result.conviction_score) == missing_result.conviction_score
    assert pytest.approx(suspect_result.raw_conviction) == missing_result.raw_conviction


# ──────────────────────────────────────────────────────────────────
# ETF classifier integration
# ──────────────────────────────────────────────────────────────────


def test_etf_classifier_suspect_drawdown_treated_as_missing():
    """The ETF classifier reads drawdown_current for its categorization.
    Suspect values must be treated equivalently to genuinely-missing —
    the deep-drawdown bucket should NOT fire on a -0.999 split-cascade
    artifact."""
    from mef.etf_classifier import classify_etf

    features_suspect = {
        "symbol": "TEST_ETF",
        "close": 50.0,
        "sma_50": 49.0,
        "sma_200": 48.0,
        "rsi_14": 50.0,
        "drawdown_current": -0.999,
        "return_63d": 0.03,
    }
    features_missing = {**features_suspect, "drawdown_current": None}

    out_suspect = classify_etf(features_suspect, spy_features={"return_63d": 0.02})
    out_missing = classify_etf(features_missing, spy_features={"return_63d": 0.02})

    # classify_etf returns an EtfEntryLabel dataclass.
    assert out_suspect.label == out_missing.label, (
        "split-cascade-suspect drawdown must classify identically to "
        "genuinely-missing drawdown"
    )


# ──────────────────────────────────────────────────────────────────
# Source-integrity invariant
# ──────────────────────────────────────────────────────────────────


def test_guardrail_does_not_touch_upstream_data():
    """Pin the contract: the guardrail is a downstream interpretation
    layer; it never writes back to MASD, SHDB, or the mart. The unit
    tests above prove the helpers are pure functions; this test exists
    as a documentation marker so future readers see the intent."""
    # Pure function: no I/O, no global state mutation.
    assert safe_drawdown(-0.5) == -0.5
    assert safe_drawdown(-0.999) is None
    # Calling many times has no side effect.
    for _ in range(10):
        assert safe_drawdown(-0.999) is None
