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
