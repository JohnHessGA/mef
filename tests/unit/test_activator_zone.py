"""Unit tests for the entry-zone midpoint parser used by the activator."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mef.positions.activator import _parse_zone_midpoint


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$270.00-$275.00",          Decimal("272.5")),
        ("$270-$275",                Decimal("272.5")),
        ("limit order $444.20-$453.06", Decimal("448.63")),
        ("$1517.87-$1548.85",        Decimal("1533.36")),
        ("no zone here",             None),
        (None,                        None),
        ("",                          None),
    ],
)
def test_parse_zone_midpoint(text, expected):
    got = _parse_zone_midpoint(text)
    if expected is None:
        assert got is None
    else:
        assert got is not None
        assert abs(got - expected) < Decimal("0.01")
