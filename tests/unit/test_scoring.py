"""Unit tests for the pure-function pieces of mef.scoring."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mef.scoring import _SECTOR_TO_ETF, _outcome


@pytest.mark.parametrize(
    "exit_price,stop,target,expected",
    [
        (Decimal("1700"), Decimal("1440"), Decimal("1672"), "win"),
        (Decimal("1672"), Decimal("1440"), Decimal("1672"), "win"),         # at-target
        (Decimal("1440"), Decimal("1440"), Decimal("1672"), "loss"),         # at-stop
        (Decimal("1430"), Decimal("1440"), Decimal("1672"), "loss"),
        (Decimal("1500"), Decimal("1440"), Decimal("1672"), "timeout"),
        (None,            Decimal("1440"), Decimal("1672"), "timeout"),
        (Decimal("1700"), None,            None,            "timeout"),
    ],
)
def test_outcome(exit_price, stop, target, expected):
    assert _outcome(exit_price=exit_price, stop=stop, target=target) == expected


def test_sector_map_covers_universe_xls():
    """All seven sector ETFs in our universe must be reachable from a sector name."""
    expected_etfs = {"XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP"}
    assert set(_SECTOR_TO_ETF.values()) == expected_etfs


def test_sector_map_skips_sectors_without_xl_etf():
    """Communication Services / Utilities / Real Estate / Basic Materials
    have no XL* ETF in the v1 universe — they should be absent from the map."""
    for missing in ("Communication Services", "Utilities", "Real Estate", "Basic Materials"):
        assert _SECTOR_TO_ETF.get(missing) is None
