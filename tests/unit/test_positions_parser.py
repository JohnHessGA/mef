"""Pure-function tests for the Fidelity CSV parser."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from mef.positions.parser import (
    FIDELITY_HEADER,
    hash_file_sha256,
    parse_currency,
    parse_fidelity_csv,
    parse_quantity,
)


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("$1,234.56", Decimal("1234.56")),
        ("+$12.00",  Decimal("12.00")),
        ("-$570.00", Decimal("-570.00")),
        ("--",       None),
        ("",         None),
    ],
)
def test_parse_currency(cell, expected):
    assert parse_currency(cell) == expected


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("100",       Decimal("100")),
        ("1,500.25",  Decimal("1500.25")),
        ("--",        None),
        ("",          None),
    ],
)
def test_parse_quantity(cell, expected):
    assert parse_quantity(cell) == expected


def _minimal_csv(positions: list[list[str]]) -> str:
    header_line = ",".join(f'"{h}"' for h in FIDELITY_HEADER)
    rows = [header_line]
    for cells in positions:
        padded = cells + [""] * (len(FIDELITY_HEADER) - len(cells))
        rows.append(",".join(f'"{c}"' for c in padded))
    rows.append("")
    rows.append('"Date downloaded Apr-17-2026 04:15 p.m ET"')
    return "\n".join(rows) + "\n"


def test_parse_fidelity_csv_happy(tmp_path: Path):
    csv_text = _minimal_csv([
        ["Z12345678", "BROKERAGE", "KLAC", "KLA CORP", "60", "$1,533.00", "+$3.00", "$91,980.00",
         "$180.00", "+0.20%", "$5,000.00", "+5.75%", "45.00%", "$86,980.00", "$1,449.67", "Cash"],
        ["Z12345678", "BROKERAGE", "AAPL", "APPLE INC COM", "100", "$270.23", "-$1.00", "$27,023.00",
         "-$100.00", "-0.37%", "$3,000.00", "+12.50%", "15.00%", "$24,023.00", "$240.23", "Cash"],
    ])
    p = tmp_path / "positions.csv"
    p.write_text(csv_text, encoding="utf-8")

    parsed = parse_fidelity_csv(p)
    assert parsed.header_valid
    assert parsed.as_of_date is not None
    assert parsed.as_of_date.isoformat() == "2026-04-17"

    symbols = {pos.symbol for pos in parsed.positions}
    assert symbols == {"KLAC", "AAPL"}

    klac = next(pos for pos in parsed.positions if pos.symbol == "KLAC")
    assert klac.quantity == Decimal("60")
    assert klac.last_price == Decimal("1533.00")
    assert klac.cost_basis_total == Decimal("86980.00")
    assert klac.average_cost_basis == Decimal("1449.67")
    assert klac.account_number == "Z12345678"


def test_parse_fidelity_csv_skips_pending_and_blank(tmp_path: Path):
    csv_text = _minimal_csv([
        ["Z12345678", "BROKERAGE", "KLAC", "KLA CORP", "60", "$1,533.00", "$0", "$91,980.00",
         "$0", "0%", "$0", "0%", "0%", "$0", "$1,449.67", "Cash"],
        ["Z12345678", "BROKERAGE", "Pending activity", "", "", "", "", "",
         "", "", "", "", "", "", "", ""],
    ])
    p = tmp_path / "positions.csv"
    p.write_text(csv_text, encoding="utf-8")

    parsed = parse_fidelity_csv(p)
    assert len(parsed.positions) == 1
    assert parsed.positions[0].symbol == "KLAC"


def test_hash_is_stable(tmp_path: Path):
    p = tmp_path / "x.csv"
    p.write_text("hello\n")
    h1 = hash_file_sha256(p)
    h2 = hash_file_sha256(p)
    assert h1 == h2 and len(h1) == 64


def test_header_mismatch_flagged(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("wrong,header\nrow,here\n")
    parsed = parse_fidelity_csv(p)
    assert not parsed.header_valid
    assert parsed.warnings
