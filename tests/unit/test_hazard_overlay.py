"""Unit tests for Layer B hazard overlay."""

from __future__ import annotations

from datetime import date

from mef.hazard_overlay import (
    DEFAULT_CAP, DEFAULT_MACRO_BASE,
    _classify_event, _symbol_bucket, compute,
)


def _row(**over):
    base = {
        "symbol": "AAA", "asset_kind": "stock",
        "bar_date": date(2026, 4, 17),
        "sector": "Technology",
        "next_earnings_date": None,
    }
    base.update(over)
    return base


def _baseline(events=None):
    return {
        "spy_return_20d": 0.01, "spy_return_63d": 0.02,
        "sector_returns_63d": {},
        "upcoming_high_impact_events": events or [],
    }


# ─── event classification ───

def test_classify_recognizes_top_tier_events():
    assert _classify_event("CPI MoM") == "cpi"
    assert _classify_event("Core CPI") == "cpi"
    assert _classify_event("Core PCE") == "pce"
    assert _classify_event("Nonfarm Payrolls") == "nfp"
    assert _classify_event("FOMC Statement") == "fomc"
    assert _classify_event("Federal Funds Rate") == "fomc"


def test_classify_buckets_other_releases():
    assert _classify_event("GDP advance") == "other"
    assert _classify_event("ISM Manufacturing PMI") == "other"
    assert _classify_event("Retail Sales MoM") == "other"


def test_classify_unknown_falls_to_other():
    # Lower-tier releases default to the safe "other" bucket.
    assert _classify_event("Random Release") == "other"


# ─── symbol bucket ───

def test_symbol_bucket_broad_index_etfs():
    for sym in ("SPY", "QQQ", "IWM", "DIA"):
        assert _symbol_bucket({"symbol": sym, "asset_kind": "etf"}) == "broad_index"


def test_symbol_bucket_rate_sensitive_sector_etfs():
    for sym in ("XLF", "XLU", "XLRE"):
        assert _symbol_bucket({"symbol": sym, "asset_kind": "etf"}) == "rate_sensitive"


def test_symbol_bucket_defensive_etfs_and_stocks():
    assert _symbol_bucket({"symbol": "XLP", "asset_kind": "etf"}) == "defensive"
    assert _symbol_bucket({
        "symbol": "PG", "asset_kind": "stock",
        "sector": "Consumer Defensive",
    }) == "defensive"


def test_symbol_bucket_rate_sensitive_stock_sectors():
    assert _symbol_bucket({
        "symbol": "JPM", "asset_kind": "stock",
        "sector": "Financial Services",
    }) == "rate_sensitive"


def test_symbol_bucket_default():
    assert _symbol_bucket({
        "symbol": "AAPL", "asset_kind": "stock", "sector": "Technology",
    }) == "default"


# ─── macro penalty mechanics ───

def test_no_events_zero_penalty():
    r = compute(_row(), _baseline(), engine="trend", today=date(2026, 4, 17))
    assert r.total == 0.0
    assert r.macro == 0.0


def test_cpi_today_on_tech_stock_trend():
    events = [{"date": date(2026, 4, 17), "event": "CPI MoM"}]
    r = compute(_row(), _baseline(events), engine="trend", today=date(2026, 4, 17))
    # CPI base 0.06 × default symbol 1.00 × trend 1.00 = 0.06.
    assert r.macro == 0.06
    assert r.event_type == "cpi"
    assert "macro:cpi" in r.flags


def test_fomc_on_broad_index_trend_higher_penalty():
    events = [{"date": date(2026, 4, 17), "event": "FOMC Statement"}]
    row = {"symbol": "SPY", "asset_kind": "etf", "bar_date": date(2026, 4, 17)}
    r = compute(row, _baseline(events), engine="trend", today=date(2026, 4, 17))
    # FOMC base 0.07 × broad_index 1.25 × trend 1.00 = 0.0875.
    assert abs(r.macro - 0.0875) < 1e-4


def test_value_engine_multiplier_lowers_penalty():
    events = [{"date": date(2026, 4, 17), "event": "CPI MoM"}]
    trend = compute(_row(), _baseline(events), engine="trend", today=date(2026, 4, 17))
    value = compute(_row(), _baseline(events), engine="value", today=date(2026, 4, 17))
    # Value's 0.60 multiplier should reduce the penalty meaningfully.
    assert value.macro < trend.macro
    assert abs(value.macro - trend.macro * 0.60) < 1e-4


def test_event_2_days_out_does_not_trigger():
    events = [{"date": date(2026, 4, 19), "event": "CPI MoM"}]
    r = compute(_row(), _baseline(events), engine="trend", today=date(2026, 4, 17))
    assert r.macro == 0.0


def test_multiple_events_same_window_take_max():
    # CPI + NFP both today. Max of (0.06, 0.05) wins; no stacking.
    events = [
        {"date": date(2026, 4, 17), "event": "CPI MoM"},
        {"date": date(2026, 4, 17), "event": "Nonfarm Payrolls"},
    ]
    r = compute(_row(), _baseline(events), engine="trend", today=date(2026, 4, 17))
    assert r.event_type == "cpi"
    assert abs(r.macro - 0.06) < 1e-4


# ─── earnings-proximity mechanics ───

def test_earnings_prox_trend_6_to_10_days():
    # 8 days out: 6-10d band.
    row = _row(next_earnings_date=date(2026, 4, 25))
    r = compute(row, _baseline(), engine="trend", today=date(2026, 4, 17))
    assert r.earnings_prox == 0.08
    assert "earn_prox:6-10d" in r.flags


def test_earnings_prox_trend_11_to_21_days():
    # 14 days out: 11-21d band.
    row = _row(next_earnings_date=date(2026, 5, 1))
    r = compute(row, _baseline(), engine="trend", today=date(2026, 4, 17))
    assert r.earnings_prox == 0.03
    assert "earn_prox:11-21d" in r.flags


def test_earnings_prox_does_not_apply_to_mean_rev():
    # Mean-rev blocks 0-10d at Layer A; Layer B earnings_prox is trend-only.
    row = _row(next_earnings_date=date(2026, 5, 1))  # 14d out
    r = compute(row, _baseline(), engine="mean_reversion", today=date(2026, 4, 17))
    assert r.earnings_prox == 0.0


def test_earnings_prox_does_not_apply_to_value():
    row = _row(next_earnings_date=date(2026, 5, 1))
    r = compute(row, _baseline(), engine="value", today=date(2026, 4, 17))
    assert r.earnings_prox == 0.0


# ─── cross-family stacking + cap ───

def test_sum_across_families_under_cap():
    # CPI today (0.06) + earnings in 8d (0.08) = 0.14 → cap 0.10.
    events = [{"date": date(2026, 4, 17), "event": "CPI MoM"}]
    row = _row(next_earnings_date=date(2026, 4, 25))
    r = compute(row, _baseline(events), engine="trend", today=date(2026, 4, 17))
    assert r.macro == 0.06
    assert r.earnings_prox == 0.08
    assert r.total == DEFAULT_CAP
    # Note explicitly mentions the clamp so audit can spot capped runs.
    assert any("clamped at cap" in n for n in r.notes)


def test_config_override_on_base_penalties():
    # Supplying a custom ranker.hazard_overlay config should override defaults.
    events = [{"date": date(2026, 4, 17), "event": "CPI MoM"}]
    cfg = {"macro": {"base": {"cpi": 0.02}}}
    r = compute(_row(), _baseline(events),
                engine="trend", today=date(2026, 4, 17), config=cfg)
    assert r.macro == 0.02


def test_default_base_penalties_match_spec():
    # Guards against accidental changes to the tunable table.
    assert DEFAULT_MACRO_BASE["fomc"] == 0.07
    assert DEFAULT_MACRO_BASE["cpi"] == 0.06
    assert DEFAULT_MACRO_BASE["pce"] == 0.06
    assert DEFAULT_MACRO_BASE["nfp"] == 0.05
    assert DEFAULT_MACRO_BASE["other"] == 0.03
