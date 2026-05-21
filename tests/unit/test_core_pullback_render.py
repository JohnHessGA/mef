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
    # Section title was renamed 2026-05-21 ("WATCHLIST" → "RADAR")
    # to match the Growth Opportunity Finder / Core Pullback Radar
    # naming alignment. Underlying module / table names unchanged.
    assert "CORE PULLBACK RADAR" in text
    assert "CORE PULLBACK WATCHLIST" not in text
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


# ─────────────────────────────────────────────────────────────────────────
# Pass 2: "already in/beyond" reason wording for actionable buckets
# ─────────────────────────────────────────────────────────────────────────

def test_buy_zone_active_reason_says_already_in_buy_zone():
    """BUY_ZONE_ACTIVE means the engine has already declared that price
    crossed below the buy_zone threshold. The reason line must say so
    explicitly so a reader doesn't wonder why starter/better are absent."""
    sigs = [_sig("ANET", STATUS_BUY_ZONE_ACTIVE,
                 close=142.0,
                 starter_buy_level=160.0,          # above close → dropped
                 better_buy_level=152.0,           # above close → dropped
                 deep_buy_level=133.0,             # below close → kept
                 drawdown_63d=-0.21, drawdown_252d=-0.18)]
    text = "\n".join(render_section(sigs))
    assert "current price is already in the buy zone" in text
    # Bracketing pieces still present.
    assert "down 21%" in text
    assert "trend intact" in text


def test_deep_pullback_reason_says_already_beyond_deep_threshold():
    sigs = [_sig("MSFT", STATUS_DEEP_PULLBACK_OPPORTUNITY,
                 close=417.0,
                 starter_buy_level=412.0, better_buy_level=399.0,
                 deep_buy_level=460.0,             # > close → dropped
                 drawdown_63d=-0.04, drawdown_252d=-0.23)]
    text = "\n".join(render_section(sigs))
    assert "current price is already beyond deep pullback threshold" in text
    assert "down 23%" in text
    assert "trend intact" in text


def test_buy_zone_lone_surviving_deep_renamed_deeper_add():
    """ANET-style row: starter/better above close, only deep survives.
    The lone deep level must render as 'deeper add' so the reader
    doesn't read a bare 'deep $133' as 'this is the first buy level'."""
    sigs = [_sig("ANET", STATUS_BUY_ZONE_ACTIVE,
                 close=142.0,
                 starter_buy_level=160.0,
                 better_buy_level=152.0,
                 deep_buy_level=133.0,
                 drawdown_63d=-0.21, drawdown_252d=-0.18)]
    text = "\n".join(render_section(sigs))
    assert "deeper add $133" in text
    # Original "deep $133" wording must not leak through.
    assert "deep $133" not in text.replace("deeper add $133", "")


def test_lone_better_keeps_its_label():
    """Only `deep` gets the 'deeper add' rename. A lone surviving
    starter or better still uses its natural label so we don't pretend
    a starter is an add level."""
    sigs = [_sig("BBB", STATUS_PULLBACK_FORMING,
                 close=200.0,
                 starter_buy_level=210.0,          # > close → dropped
                 better_buy_level=195.0,           # < close → kept
                 deep_buy_level=205.0,             # non-monotone after better → dropped
                 drawdown_63d=-0.06, drawdown_252d=-0.07)]
    text = "\n".join(render_section(sigs))
    assert "better $195" in text
    assert "deeper add" not in text


def test_three_surviving_levels_keep_deep_label():
    """When starter/better/deep all survive, 'deep' stays — context is
    self-explanatory next to its siblings."""
    sigs = [_sig("JPM", STATUS_BUY_ZONE_ACTIVE,
                 close=296.0,
                 starter_buy_level=295.0,
                 better_buy_level=285.0,
                 deep_buy_level=274.0,
                 drawdown_63d=-0.05, drawdown_252d=-0.12)]
    text = "\n".join(render_section(sigs))
    assert "starter $295" in text
    assert "better $285" in text
    assert "deep $274" in text
    assert "deeper add" not in text


def test_deep_pullback_with_all_levels_dropped_still_has_reason_clarifier():
    """Edge case where every level lands above close (close has moved
    past all three anchors). No levels in the header, but the reason
    line still explains why."""
    sigs = [_sig("ZZZ", STATUS_DEEP_PULLBACK_OPPORTUNITY,
                 close=50.0,
                 starter_buy_level=60.0, better_buy_level=58.0,
                 deep_buy_level=55.0,
                 drawdown_63d=-0.30, drawdown_252d=-0.40)]
    text = "\n".join(render_section(sigs))
    # No level wording in the header line ("$" next to a label).
    assert "starter $" not in text
    assert "better $" not in text
    assert "deep $" not in text
    assert "deeper add $" not in text
    # But the reason clarifier still fires.
    assert "current price is already beyond deep pullback threshold" in text


# ─────────────────────────────────────────────────────────────────────────
# Pass 2: data-quality cautions are silenced in the default render
# ─────────────────────────────────────────────────────────────────────────

def test_dq_cautions_do_not_leak_into_default_render():
    """Pre-2026-05-21 the reason line included a `⚠ suspect_drawdown…`
    fragment that cluttered an already terse section. Cautions stay on
    the dataclass for a future debug view but must not surface here."""
    sigs = [_sig("CELH", STATUS_THESIS_BROKEN_REVIEW,
                 close=29.0,
                 starter_buy_level=53.0, better_buy_level=50.0,
                 deep_buy_level=48.0,
                 drawdown_63d=None,
                 drawdown_252d=-0.55,
                 trend_health="broken",
                 cautions=["suspect_drawdown_63d -51%: dropped (likely split artifact)",
                           "missing_high_63d: starter/better levels degraded"])]
    text = "\n".join(render_section(sigs))
    assert "suspect_drawdown_63d" not in text
    assert "split artifact" not in text
    assert "missing_high_63d" not in text
    # Headline + suffix still present so the row is intelligible.
    assert "long-term trend broken" in text
    assert "no buy levels shown" in text


# ─────────────────────────────────────────────────────────────────────────
# Pass 2: THESIS / RISK CHANGED cap is lower than the other buckets
# ─────────────────────────────────────────────────────────────────────────

def test_thesis_broken_bucket_capped_at_five_and_summarized():
    """A 20-name selloff cluster must not dominate the daily report."""
    sigs = [_sig(f"T{i:02d}", STATUS_THESIS_BROKEN_REVIEW,
                 close=10.0 + i,
                 drawdown_252d=-0.40 - i * 0.005,
                 trend_health="broken") for i in range(20)]
    out = render_section(sigs)
    text = "\n".join(out)
    # Five rows rendered; the rest summarized.
    rendered = sum(1 for line in out if line.strip().startswith("T") and "$" in line)
    assert rendered == 5, f"expected 5 rendered rows, got {rendered}"
    assert "…and 15 more in this bucket." in text   # 20 - 5 cap = 15


def test_other_buckets_keep_the_default_cap_of_twelve():
    """Only THESIS_BROKEN gets the tighter cap. The other notable
    buckets retain the standard 12-row cap so they aren't truncated
    prematurely."""
    sigs = [_sig(f"P{i:02d}", STATUS_PULLBACK_FORMING,
                 drawdown_63d=-0.07 - i * 0.001) for i in range(15)]
    out = render_section(sigs)
    text = "\n".join(out)
    assert "…and 3 more in this bucket." in text   # 15 - 12 = 3
