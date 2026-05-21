"""Unit tests for the Core Pullback Watchlist renderer.

Pure formatting tests — feed crafted PullbackSignal objects through
``render_section`` and check the output structure. No DB, no SHDB.
"""

from __future__ import annotations

from datetime import date

from mef.core_pullback import (
    DISPLAY_LABEL,
    PullbackSignal,
    STATUS_BUY_ZONE_ACTIVE,
    STATUS_DEEP_PULLBACK_OPPORTUNITY,
    STATUS_FALLING_KNIFE_WAIT,
    STATUS_NO_PULLBACK,
    STATUS_PULLBACK_FORMING,
    STATUS_THESIS_BROKEN_REVIEW,
)
from mef.core_pullback_render import render_section


def _sig(symbol: str, status: str, **kw) -> PullbackSignal:
    base = dict(
        symbol=symbol, asset_kind="stock",
        tier_code="elite_compounder", tier_display_name="Tier 2 — Elite compounder",
        status=status, display_label=DISPLAY_LABEL[status],
        close=100.0, as_of_date=date(2026, 5, 20),
        drawdown_63d=-0.06, drawdown_252d=-0.10,
        starter_buy_level=95.0, better_buy_level=92.0, deep_buy_level=85.0,
        trend_health="healthy", stabilization="ok",
        risk_reward=2.5, reasons=[], cautions=[],
    )
    base.update(kw)
    return PullbackSignal(**base)


def test_empty_watchlist_renders_a_friendly_marker():
    out = render_section([])
    text = "\n".join(out)
    assert "CORE PULLBACK WATCHLIST" in text
    assert "no watchlist symbols loaded" in text


def test_all_quiet_collapses_to_one_count_line():
    sigs = [_sig(f"S{i}", STATUS_NO_PULLBACK) for i in range(60)]
    out = render_section(sigs)
    text = "\n".join(out)
    assert "All 60 watchlist symbols are quiet today" in text
    # No notable-section headers should appear.
    for header in ("BUY ZONE ACTIVE", "PULLBACK FORMING", "FALLING KNIFE",
                   "DEEP PULLBACK", "THESIS / RISK"):
        assert header not in text


def test_mixed_section_groups_notable_and_summarizes_quiet():
    sigs = [
        _sig("SPY",  STATUS_BUY_ZONE_ACTIVE),
        _sig("QQQ",  STATUS_PULLBACK_FORMING),
        _sig("INTC", STATUS_FALLING_KNIFE_WAIT, stabilization="not_ok",
             drawdown_63d=-0.12, drawdown_252d=-0.20),
        _sig("NVO",  STATUS_THESIS_BROKEN_REVIEW, trend_health="broken"),
        _sig("MSFT", STATUS_DEEP_PULLBACK_OPPORTUNITY,
             drawdown_63d=-0.16, drawdown_252d=-0.18),
    ]
    # Plus 55 quiet so the quiet count is meaningful.
    sigs.extend(_sig(f"Q{i}", STATUS_NO_PULLBACK) for i in range(55))

    out = render_section(sigs)
    text = "\n".join(out)

    # Headers appear in the canonical order.
    deep_pos = text.index("DEEP PULLBACK OPPORTUNITY")
    bza_pos  = text.index("BUY ZONE ACTIVE")
    pf_pos   = text.index("PULLBACK FORMING")
    fkw_pos  = text.index("FALLING KNIFE — WAIT")
    bra_pos  = text.index("THESIS / RISK CHANGED")
    assert deep_pos < bza_pos < pf_pos < fkw_pos < bra_pos

    # Symbols land under the right headers.
    assert "MSFT" in text[deep_pos:bza_pos]
    assert "SPY"  in text[bza_pos:pf_pos]
    assert "QQQ"  in text[pf_pos:fkw_pos]
    assert "INTC" in text[fkw_pos:bra_pos]
    assert "NVO"  in text[bra_pos:]

    # Quiet bucket renders as a single count line, not 55 rows.
    assert "55 watchlist symbols have no meaningful pullback today" in text


def test_notable_per_status_safety_cap_kicks_in_for_huge_buckets():
    sigs = [_sig(f"X{i:03d}", STATUS_PULLBACK_FORMING,
                 drawdown_63d=-0.07 - i * 0.001) for i in range(20)]
    out = render_section(sigs)
    text = "\n".join(out)
    assert "PULLBACK FORMING" in text
    assert "…and 8 more in this bucket." in text   # 20 - 12 cap = 8


def test_notable_block_includes_buy_levels_when_present():
    sigs = [_sig("SPY", STATUS_BUY_ZONE_ACTIVE,
                 close=440.0, starter_buy_level=435.0,
                 better_buy_level=420.0, deep_buy_level=400.0,
                 drawdown_63d=-0.04, drawdown_252d=-0.06)]
    text = "\n".join(render_section(sigs))
    assert "SPY" in text
    assert "starter $435" in text
    assert "better $420" in text
    assert "deep $400" in text


def test_notable_block_skips_missing_buy_levels_without_crash():
    sigs = [_sig("AAA", STATUS_BUY_ZONE_ACTIVE,
                 starter_buy_level=None, better_buy_level=None, deep_buy_level=None)]
    text = "\n".join(render_section(sigs))
    assert "AAA" in text
    # No "starter $None" / "$None" garbage in output.
    assert "$None" not in text


def test_thesis_broken_reason_line_is_explicit():
    sigs = [_sig("INTC", STATUS_THESIS_BROKEN_REVIEW,
                 trend_health="broken",
                 drawdown_63d=-0.18, drawdown_252d=-0.40)]
    text = "\n".join(render_section(sigs))
    assert "long-term trend broken" in text


# ─────────────────────────────────────────────────────────────────────────
# Buy-level suppression: FALLING_KNIFE_WAIT + THESIS_BROKEN_REVIEW must
# not show entry/scale-in levels — those statuses mean "do not buy yet"
# or "review before buying", so a buy ladder reads as false precision.
# ─────────────────────────────────────────────────────────────────────────

def test_thesis_broken_review_suppresses_all_buy_levels():
    sigs = [_sig("TTD", STATUS_THESIS_BROKEN_REVIEW,
                 close=21.16, starter_buy_level=29.61,
                 better_buy_level=27.96, deep_buy_level=67.32,
                 drawdown_63d=-0.357, drawdown_252d=-0.50,
                 trend_health="broken")]
    text = "\n".join(render_section(sigs))
    assert "TTD" in text
    # No buy-level wording in the header line for this status.
    assert "starter" not in text
    assert "better" not in text
    assert "deep" not in text
    # Reason line carries the explanatory suffix.
    assert "no buy levels shown" in text


def test_falling_knife_wait_suppresses_all_buy_levels():
    sigs = [_sig("INTC", STATUS_FALLING_KNIFE_WAIT,
                 close=110.80, starter_buy_level=119.48,
                 better_buy_level=112.84, deep_buy_level=97.08,
                 drawdown_63d=-0.165, drawdown_252d=-0.20,
                 stabilization="not_ok")]
    text = "\n".join(render_section(sigs))
    assert "INTC" in text
    assert "starter" not in text
    assert "better" not in text
    assert "deep" not in text
    assert "wait before setting buy levels" in text


def test_buy_zone_active_still_renders_levels():
    sigs = [_sig("ANET", STATUS_BUY_ZONE_ACTIVE,
                 close=200.0, starter_buy_level=190.0,
                 better_buy_level=180.0, deep_buy_level=160.0,
                 drawdown_63d=-0.05, drawdown_252d=-0.08)]
    text = "\n".join(render_section(sigs))
    assert "starter $190" in text
    assert "better $180" in text
    assert "deep $160" in text


def test_pullback_forming_still_renders_levels():
    sigs = [_sig("QQQ", STATUS_PULLBACK_FORMING,
                 close=440.0, starter_buy_level=435.0,
                 better_buy_level=420.0, deep_buy_level=400.0,
                 drawdown_63d=-0.03)]
    text = "\n".join(render_section(sigs))
    assert "starter $435" in text
    assert "better $420" in text
    assert "deep $400" in text


def test_deep_pullback_opportunity_still_renders_levels():
    sigs = [_sig("MSFT", STATUS_DEEP_PULLBACK_OPPORTUNITY,
                 close=300.0, starter_buy_level=290.0,
                 better_buy_level=275.0, deep_buy_level=250.0,
                 drawdown_63d=-0.06, drawdown_252d=-0.18)]
    text = "\n".join(render_section(sigs))
    assert "starter $290" in text
    assert "better $275" in text
    assert "deep $250" in text


# ─────────────────────────────────────────────────────────────────────────
# Whole-dollar / whole-percent formatting
# ─────────────────────────────────────────────────────────────────────────

def test_displayed_dollar_values_are_whole_dollars_no_cents():
    sigs = [_sig("SPY", STATUS_BUY_ZONE_ACTIVE,
                 close=440.45, starter_buy_level=435.12,
                 better_buy_level=420.87, deep_buy_level=400.49,
                 drawdown_63d=-0.04, drawdown_252d=-0.06)]
    text = "\n".join(render_section(sigs))
    # Rounded to nearest dollar, no decimals anywhere in the levels.
    assert "$440" in text   # close 440.45 → 440
    assert "$435" in text   # 435.12 → 435
    assert "$421" in text   # 420.87 → 421
    assert "$400" in text   # 400.49 → 400
    # Cents must not leak.
    for cents in (".45", ".12", ".87", ".49", ".00"):
        assert cents not in text


def test_displayed_percentages_geq_1_are_whole_percent():
    sigs = [_sig("SPY", STATUS_BUY_ZONE_ACTIVE,
                 close=100.0, starter_buy_level=95.0,
                 better_buy_level=92.0, deep_buy_level=85.0,
                 drawdown_63d=-0.209, drawdown_252d=-0.132)]
    text = "\n".join(render_section(sigs))
    # The renderer picks the deeper drawdown (252d here is shallower than 63d,
    # so 63d at 21% wins). Whatever it picks must round to a whole percent.
    assert "down 21% from 63d high" in text
    # No decimals should appear on the headline percent.
    assert "20.9%" not in text
    assert "13.2%" not in text


def test_displayed_percentage_below_1_renders_cleanly():
    sigs = [_sig("AAA", STATUS_PULLBACK_FORMING,
                 close=100.0, starter_buy_level=99.0,
                 better_buy_level=98.0, deep_buy_level=95.0,
                 drawdown_63d=-0.007, drawdown_252d=-0.005)]
    text = "\n".join(render_section(sigs))
    # Sub-1% renders as "less than 1%", not "0.7%" and not "1%".
    assert "less than 1%" in text


# ─────────────────────────────────────────────────────────────────────────
# Non-monotonic / confusing levels — drop the misleading entry instead of
# rendering it.
# ─────────────────────────────────────────────────────────────────────────

def test_level_above_close_is_dropped_from_display():
    # MSFT-shape row: deep level (anchored to 252d peak) lands ABOVE close.
    # That reads as "buy at a higher price", which is nonsense for a
    # pullback report — drop it.
    sigs = [_sig("MSFT", STATUS_DEEP_PULLBACK_OPPORTUNITY,
                 close=417.0,
                 starter_buy_level=412.0,
                 better_buy_level=399.0,
                 deep_buy_level=460.0,                # > close → must drop
                 drawdown_63d=-0.038, drawdown_252d=-0.230)]
    text = "\n".join(render_section(sigs))
    assert "starter $412" in text
    assert "better $399" in text
    # "deep $460" must not appear (it's above the current price).
    assert "deep $460" not in text


def test_non_monotone_inner_level_is_dropped():
    # If deep is between starter and better (out of natural descent),
    # drop deep so the rendered set stays starter > better.
    sigs = [_sig("AAA", STATUS_BUY_ZONE_ACTIVE,
                 close=500.0,
                 starter_buy_level=490.0,
                 better_buy_level=470.0,
                 deep_buy_level=480.0,                # > better → non-monotone
                 drawdown_63d=-0.10, drawdown_252d=-0.12)]
    text = "\n".join(render_section(sigs))
    assert "starter $490" in text
    assert "better $470" in text
    assert "deep $480" not in text
