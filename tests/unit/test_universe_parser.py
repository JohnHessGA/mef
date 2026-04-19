"""Unit tests for mef.universe_parser.

Pure-function tests; no DB, no filesystem.
"""

from __future__ import annotations

import pytest

from mef.universe_parser import (
    _parse_abbreviated_dollars,
    _parse_currency_float,
    _parse_int_with_commas,
    parse_etfs,
    parse_stocks,
)


# ──────────────────────────────────────────────────────────────────────────
# Number helpers
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cell,expected",
    [
        ("$123.28", 123.28),
        ("$4132.34", 4132.34),
        ("$27.09", 27.09),
        ("", None),
    ],
)
def test_parse_currency_float(cell, expected):
    assert _parse_currency_float(cell) == expected


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("2,204,554", 2_204_554),
        ("178,557,077", 178_557_077),
        ("10", 10),
        ("", None),
    ],
)
def test_parse_int_with_commas(cell, expected):
    assert _parse_int_with_commas(cell) == expected


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("$272M", 272_000_000),
        ("$4.57B", 4_570_000_000),
        ("$4.05T", 4_050_000_000_000),
        ("$38.0B", 38_000_000_000),
        ("", None),
    ],
)
def test_parse_abbreviated_dollars(cell, expected):
    assert _parse_abbreviated_dollars(cell) == expected


# ──────────────────────────────────────────────────────────────────────────
# Stock table
# ──────────────────────────────────────────────────────────────────────────

_STOCK_FIXTURE = """\
# Focus US Stocks

Some preamble.

| Symbol | Name | Sector | Industry | Avg Close | Avg Vol | Avg $ Vol | Market Cap | Expirations | Total OI |
|--------|------|--------|----------|----------:|--------:|----------:|-----------:|------------:|---------:|
| A | Agilent Technologies Inc. | Healthcare | Diagnostics & Research | $123.28 | 2,204,554 | $272M | $38.0B | 10 | 21,211 |
| AAPL | Apple Inc. | Technology | Consumer Electronics | $259.66 | 46,913,776 | $12.18B | $4.05T | 25 | 4,508,974 |
"""


def test_parse_stocks_basic():
    rows = parse_stocks(_STOCK_FIXTURE)
    assert len(rows) == 2

    first = rows[0]
    assert first["symbol"] == "A"
    assert first["company_name"] == "Agilent Technologies Inc."
    assert first["sector"] == "Healthcare"
    assert first["industry"] == "Diagnostics & Research"
    assert first["avg_close_90d"] == 123.28
    assert first["avg_volume_90d"] == 2_204_554
    assert first["avg_dollar_volume_90d"] == 272_000_000
    assert first["market_cap_usd"] == 38_000_000_000
    assert first["options_expirations"] == 10
    assert first["total_open_interest"] == 21_211

    aapl = rows[1]
    assert aapl["symbol"] == "AAPL"
    assert aapl["market_cap_usd"] == 4_050_000_000_000
    assert aapl["avg_volume_90d"] == 46_913_776


def test_parse_stocks_empty_raises():
    with pytest.raises(ValueError):
        parse_stocks("# Heading only, no table\n\nNot a table row.")


def test_parse_stocks_real_file_counts():
    """Sanity-check: the real 305-stock file should parse to 305 rows."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    notes = (repo_root / "notes" / "focus-universe-us-stocks-final.md").read_text()
    rows = parse_stocks(notes)
    assert len(rows) == 305
    # Every row must have a symbol and a numeric market cap.
    assert all(r["symbol"] for r in rows)
    assert all(r["market_cap_usd"] and r["market_cap_usd"] > 0 for r in rows)


# ──────────────────────────────────────────────────────────────────────────
# ETF bullets
# ──────────────────────────────────────────────────────────────────────────

_ETF_FIXTURE = """\
# Core US ETFs

## Daily Shortlist (15)

### Broad Market (3)

- **SPY** — S&P 500 benchmark; primary broad-market reference
- **QQQ** — large-cap growth / Nasdaq leadership

### Size (1)

- **IWM** — small-cap risk appetite / cyclicality read

### Core Sector ETFs (7)

- **XLK** — technology
- **XLF** — financials
"""


def test_parse_etfs_basic():
    rows = parse_etfs(_ETF_FIXTURE)
    assert len(rows) == 5

    symbols = [r["symbol"] for r in rows]
    assert symbols == ["SPY", "QQQ", "IWM", "XLK", "XLF"]

    roles = [r["role"] for r in rows]
    assert roles == ["broad_market", "broad_market", "size", "sector", "sector"]

    assert rows[0]["description"].startswith("S&P 500 benchmark")


def test_parse_etfs_real_file_counts():
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    notes = (repo_root / "notes" / "core-us-etfs-daily-final.md").read_text()
    rows = parse_etfs(notes)
    assert len(rows) == 15
    symbols = {r["symbol"] for r in rows}
    # Spot-check: these are all in the 15-ETF shortlist.
    assert {"SPY", "QQQ", "VTI", "IWM", "XLK", "XLF", "XLV",
            "XLE", "XLI", "XLY", "XLP", "SMH"}.issubset(symbols)


def test_parse_etfs_empty_raises():
    with pytest.raises(ValueError):
        parse_etfs("# Core US ETFs — nothing here.")
