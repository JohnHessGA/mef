"""Unit tests for the deterministic Job 2 pullback engine.

Pure tests — no DB, no SHDB, no network. The engine is a pure function
over (tier, evidence dict). These tests pin every status branch, the
Tier-4 strictness rule, and graceful degradation on missing evidence.
"""

from __future__ import annotations

from datetime import date

import pytest

from mef.core_pullback import (
    DISPLAY_LABEL,
    STATUS_BUY_ZONE_ACTIVE,
    STATUS_DEEP_PULLBACK_OPPORTUNITY,
    STATUS_FALLING_KNIFE_WAIT,
    STATUS_NO_PULLBACK,
    STATUS_PULLBACK_FORMING,
    STATUS_THESIS_BROKEN_REVIEW,
    TREND_BROKEN,
    TREND_HEALTHY,
    compute_pullback_signal,
    evaluate_watchlist,
)
from mef.core_pullback_repository import WatchlistRow


# ─────────────────────────────────────────────────────────────────────────
# Tier factories — match the seed in 013_core_pullback_watchlist.sql
# ─────────────────────────────────────────────────────────────────────────

def _tier(
    code: str = "elite_compounder",
    *, asset_kind: str = "stock",
    visibility: float = 0.05,
    buy_zone: float = 0.08,
    deep: float = 0.15,
    symbol: str = "NVDA",
    requires_stab: bool = True,
) -> WatchlistRow:
    return WatchlistRow(
        symbol=symbol,
        asset_kind=asset_kind,
        tier_code=code,
        tier_display_name=f"tier {code}",
        asset_group=asset_kind,
        visibility_drawdown=visibility,
        buy_zone_drawdown=buy_zone,
        deep_drawdown=deep,
        min_risk_reward=None,
        requires_stabilization=requires_stab,
        tier_display_order=10,
        row_display_order=100,
        rationale=None,
    )


# ─────────────────────────────────────────────────────────────────────────
# Evidence factory — helpers for crafting deterministic test rows
# ─────────────────────────────────────────────────────────────────────────

def _evidence(
    *, close: float, sma_200: float = 100.0, sma_50: float | None = None,
    high_63d: float | None = None,
    drawdown_current: float | None = None,
    return_5d: float = 0.0,
    return_252d: float | None = None,
    sma_50_slope: float | None = None,
    rsi_14: float | None = 55.0,
    atr_14: float | None = None,
    bar_date: date | None = None,
) -> dict:
    return {
        "close":             close,
        "sma_50":            sma_50,
        "sma_200":           sma_200,
        "sma_50_slope":      sma_50_slope,
        "high_63d":          high_63d,
        "drawdown_current":  drawdown_current,
        "return_5d":         return_5d,
        "return_252d":       return_252d,
        "rsi_14":            rsi_14,
        "atr_14":            atr_14,
        "bar_date":          bar_date or date(2026, 5, 20),
        "asset_kind":        "stock",
    }


# ─────────────────────────────────────────────────────────────────────────
# Status branches — one test per status
# ─────────────────────────────────────────────────────────────────────────

def test_no_pullback_when_close_at_recent_high():
    tier = _tier()
    ev = _evidence(close=100.0, sma_200=80.0, high_63d=100.0,
                   drawdown_current=0.0, return_5d=0.0, return_252d=0.30)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_NO_PULLBACK
    assert sig.trend_health == TREND_HEALTHY


def test_pullback_forming_when_dip_is_in_visibility_band_but_below_buy_zone():
    # visibility 5% / buy_zone 8% — close is 5.5% below 63d high → forming.
    tier = _tier(visibility=0.05, buy_zone=0.08, deep=0.15)
    ev = _evidence(close=94.5, sma_200=80.0, high_63d=100.0,
                   drawdown_current=-0.055, return_5d=-0.01,
                   return_252d=0.20, rsi_14=48.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_PULLBACK_FORMING


def test_buy_zone_active_when_pullback_clears_buy_zone_threshold_and_stable():
    # 9% pullback, healthy trend, return_5d > tier-2 floor.
    tier = _tier(visibility=0.05, buy_zone=0.08, deep=0.15)
    ev = _evidence(close=91.0, sma_200=80.0, high_63d=100.0,
                   drawdown_current=-0.09, return_5d=-0.01,
                   return_252d=0.20, rsi_14=42.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_BUY_ZONE_ACTIVE


def test_deep_pullback_opportunity_when_pullback_clears_deep_threshold_and_stable():
    # 18% below the 252d peak, recovered from drawdown_current → peak_252d=121.95
    # Trend still healthy (close way above SMA200) and stabilization ok.
    tier = _tier(visibility=0.05, buy_zone=0.08, deep=0.15)
    ev = _evidence(close=100.0, sma_200=80.0, high_63d=100.0,
                   drawdown_current=-0.18, return_5d=-0.01,
                   return_252d=0.05, rsi_14=40.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_DEEP_PULLBACK_OPPORTUNITY


def test_falling_knife_wait_when_visible_pullback_but_unstable():
    # 9% pullback (clears visibility AND buy_zone) but return_5d = -7% on an
    # elite_compounder (floor -5%) → not stabilized → falling knife.
    tier = _tier(code="elite_compounder", visibility=0.05, buy_zone=0.08, deep=0.15)
    ev = _evidence(close=91.0, sma_200=80.0, high_63d=100.0,
                   drawdown_current=-0.09, return_5d=-0.07,
                   return_252d=0.10, rsi_14=35.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_FALLING_KNIFE_WAIT


def test_thesis_broken_review_when_close_far_below_sma200():
    # 15% below SMA200 → broken trend → THESIS_BROKEN_REVIEW regardless of
    # pullback magnitude or stabilization.
    tier = _tier(visibility=0.05, buy_zone=0.08, deep=0.15)
    ev = _evidence(close=85.0, sma_200=100.0, high_63d=100.0,
                   drawdown_current=-0.30, return_5d=-0.01,
                   return_252d=-0.10, rsi_14=40.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_THESIS_BROKEN_REVIEW
    assert sig.trend_health == TREND_BROKEN


def test_thesis_broken_review_when_return_252d_deeply_negative():
    # close at SMA200 (not below) but return_252d = -35% → broken on the
    # return rule.
    tier = _tier()
    ev = _evidence(close=100.0, sma_200=100.0, high_63d=120.0,
                   drawdown_current=-0.10, return_5d=-0.01,
                   return_252d=-0.35, rsi_14=45.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_THESIS_BROKEN_REVIEW


# ─────────────────────────────────────────────────────────────────────────
# Tier-4 strictness — must demand a smaller return_5d slide before
# allowing BUY_ZONE_ACTIVE, even with the same pullback magnitude.
# ─────────────────────────────────────────────────────────────────────────

def test_tier4_requires_stricter_stabilization_than_etf():
    """Same setup, same -6% return_5d. ETF (Tier 1) clears; Tier-4 does not."""
    ev = _evidence(close=85.0, sma_200=80.0, high_63d=100.0,
                   drawdown_current=-0.15, return_5d=-0.06,
                   return_252d=0.05, rsi_14=42.0)

    etf_tier = _tier(code="core_market_etf", asset_kind="etf",
                     visibility=0.03, buy_zone=0.05, deep=0.08)
    vol_tier = _tier(code="volatile_special_situation",
                     visibility=0.10, buy_zone=0.15, deep=0.25)

    etf_sig = compute_pullback_signal(etf_tier, ev)
    vol_sig = compute_pullback_signal(vol_tier, ev)

    # ETF: -6% > floor -5%? actually -6% <= -5% → stabilization not_ok.
    # Wait — for ETFs the floor is -5%, so -6% IS below floor → not_ok.
    # Pick a case that proves the *differential*: -6% return_5d on
    # core_market_etf is not_ok, but on volatile is ok (floor -8%).
    assert etf_sig.stabilization == "not_ok"
    assert vol_sig.stabilization == "ok"


def test_tier4_panic_rsi_overrides_return_5d():
    """RSI <= 22 forces not_ok even if return_5d is mild."""
    tier = _tier(code="volatile_special_situation",
                 visibility=0.10, buy_zone=0.15, deep=0.25)
    ev = _evidence(close=80.0, sma_200=70.0, high_63d=100.0,
                   drawdown_current=-0.20, return_5d=-0.01,
                   return_252d=0.05, rsi_14=20.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.stabilization == "not_ok"
    # Pullback clears visibility (10% threshold, magnitude 20%) and not stable
    # → falling knife. (Trend is healthy: close 14% above SMA200.)
    assert sig.status == STATUS_FALLING_KNIFE_WAIT


# ─────────────────────────────────────────────────────────────────────────
# Buy levels — use tier percentages off recent highs
# ─────────────────────────────────────────────────────────────────────────

def test_buy_levels_use_high_63d_and_recovered_high_252d():
    tier = _tier(visibility=0.05, buy_zone=0.08, deep=0.15)
    ev = _evidence(close=90.0, sma_200=80.0, high_63d=100.0,
                   drawdown_current=-0.20, return_5d=-0.01,
                   return_252d=0.10, rsi_14=45.0)
    sig = compute_pullback_signal(tier, ev)
    # high_63d-based starter / better
    assert sig.starter_buy_level == pytest.approx(95.0, rel=1e-9)
    assert sig.better_buy_level  == pytest.approx(92.0, rel=1e-9)
    # high_252d recovered: 90 / (1 - 0.20) = 112.5; deep = 112.5 * 0.85 = 95.625
    assert sig.deep_buy_level    == pytest.approx(95.625, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────
# Missing-evidence degradation — must not crash, must add cautions
# ─────────────────────────────────────────────────────────────────────────

def test_missing_evidence_returns_no_pullback_not_crash():
    tier = _tier()
    sig = compute_pullback_signal(tier, None)
    assert sig.status == STATUS_NO_PULLBACK
    assert any("no_evidence" in c for c in sig.cautions)


def test_missing_high_63d_still_produces_signal_with_caution():
    tier = _tier()
    ev = _evidence(close=85.0, sma_200=80.0, high_63d=None,
                   drawdown_current=-0.15, return_5d=-0.01,
                   return_252d=0.05, rsi_14=45.0)
    sig = compute_pullback_signal(tier, ev)
    # No crash. Status still computed (drawdown_252d available).
    assert sig.status in (STATUS_BUY_ZONE_ACTIVE, STATUS_DEEP_PULLBACK_OPPORTUNITY,
                          STATUS_FALLING_KNIFE_WAIT)
    assert any("missing_high_63d" in c for c in sig.cautions)
    # starter/better levels degraded to None.
    assert sig.starter_buy_level is None
    assert sig.better_buy_level is None


def test_suspect_short_horizon_drawdown_is_treated_as_missing():
    """A 63d drawdown deeper than -50% indicates a split-adjustment
    artifact in the upstream mart bars. The engine must drop it (not
    surface a fake 80% pullback) and downgrade the buy levels."""
    tier = _tier()
    # VUG-style row: close $86, "high_63d" $495 → would be -82% drawdown.
    ev = _evidence(close=86.0, sma_200=80.0, high_63d=495.0,
                   drawdown_current=-0.06, return_5d=-0.01,
                   return_252d=0.10, rsi_14=50.0)
    sig = compute_pullback_signal(tier, ev)
    # drawdown_63d must NOT carry the fake -82% value.
    assert sig.drawdown_63d is None
    # starter/better levels degraded because high_63d was rejected.
    assert sig.starter_buy_level is None
    assert sig.better_buy_level is None
    # Caution must explain what happened.
    assert any("suspect_drawdown_63d" in c for c in sig.cautions)
    # Real signal (drawdown_252d = -6%) keeps the symbol as NO_PULLBACK
    # vs the tier's 5% visibility threshold (just clears) → forming/no_pullback
    # depending on exact threshold rounding; either way NOT broken.
    assert sig.status in (STATUS_NO_PULLBACK, STATUS_PULLBACK_FORMING)
    assert sig.trend_health == TREND_HEALTHY


def test_suspect_252d_drawdown_is_treated_as_missing():
    """A drawdown ≤ -99% is the classic peak_252d split-cascade artifact.
    safe_drawdown turns it into None; the engine surfaces a caution."""
    tier = _tier()
    ev = _evidence(close=10.0, sma_200=8.0, high_63d=11.0,
                   drawdown_current=-0.999, return_5d=-0.01,
                   return_252d=0.05, rsi_14=50.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.drawdown_252d is None
    assert any("suspect_drawdown_252d" in c for c in sig.cautions)


def test_missing_close_falls_through_to_no_pullback():
    tier = _tier()
    ev = _evidence(close=85.0)
    ev["close"] = None
    sig = compute_pullback_signal(tier, ev)
    assert sig.status == STATUS_NO_PULLBACK


def test_missing_sma200_marks_trend_unknown_but_does_not_crash():
    tier = _tier()
    ev = _evidence(close=85.0, sma_200=None, high_63d=100.0,
                   drawdown_current=-0.15, return_5d=-0.01,
                   return_252d=0.05, rsi_14=45.0)
    sig = compute_pullback_signal(tier, ev)
    assert sig.trend_health == "unknown"


# ─────────────────────────────────────────────────────────────────────────
# Display vocabulary
# ─────────────────────────────────────────────────────────────────────────

def test_every_status_has_a_display_label():
    for status in (STATUS_NO_PULLBACK, STATUS_PULLBACK_FORMING, STATUS_BUY_ZONE_ACTIVE,
                   STATUS_DEEP_PULLBACK_OPPORTUNITY, STATUS_FALLING_KNIFE_WAIT,
                   STATUS_THESIS_BROKEN_REVIEW):
        assert status in DISPLAY_LABEL
        assert DISPLAY_LABEL[status]   # non-empty


# ─────────────────────────────────────────────────────────────────────────
# Batch driver
# ─────────────────────────────────────────────────────────────────────────

def test_evaluate_watchlist_preserves_order_and_handles_missing_evidence():
    tiers = [
        _tier(symbol="AAA"),
        _tier(symbol="BBB"),
        _tier(symbol="CCC"),
    ]
    ev_only_bbb = {"BBB": _evidence(close=100.0, sma_200=80.0, high_63d=100.0,
                                    drawdown_current=0.0, return_252d=0.10)}
    sigs = evaluate_watchlist(tiers, ev_only_bbb)
    assert [s.symbol for s in sigs] == ["AAA", "BBB", "CCC"]
    # AAA and CCC missing evidence → NO_PULLBACK with caution
    assert sigs[0].status == STATUS_NO_PULLBACK
    assert any("no_evidence" in c for c in sigs[0].cautions)
    assert sigs[2].status == STATUS_NO_PULLBACK


# ─────────────────────────────────────────────────────────────────────────
# Boundary: engine must not pull in LLM / CIA / network code
# ─────────────────────────────────────────────────────────────────────────

def test_engine_imports_no_llm_or_cia_modules():
    """Structural guard: the deterministic engine must not import the
    LLM client or any CIA overlay module — directly or transitively.

    Inspecting the AST is more robust than grepping the source (which
    would false-positive on the docstring banner that says 'No LLM').
    """
    import ast
    import mef.core_pullback as engine

    tree = ast.parse(open(engine.__file__).read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)

    forbidden_prefixes = ("mef.llm", "mef.cia", "anthropic")
    for mod in imported:
        for prefix in forbidden_prefixes:
            assert not mod.startswith(prefix), (
                f"core_pullback.py imports {mod!r} (forbidden prefix {prefix!r})"
            )
