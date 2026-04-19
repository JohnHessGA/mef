"""Pure parser for Fidelity Portfolio Positions CSV files.

No DB, no network. MEF only needs a small subset of what Fidelity exports —
symbol, quantity, cost basis, price, market value, account — so this parser
is intentionally leaner than IRA Guard's full classifier.

Compatible with the Fidelity 16-column Portfolio Positions export.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
import re

FIDELITY_HEADER: tuple[str, ...] = (
    "Account Number",
    "Account Name",
    "Symbol",
    "Description",
    "Quantity",
    "Last Price",
    "Last Price Change",
    "Current Value",
    "Today's Gain/Loss Dollar",
    "Today's Gain/Loss Percent",
    "Total Gain/Loss Dollar",
    "Total Gain/Loss Percent",
    "Percent Of Account",
    "Cost Basis Total",
    "Average Cost Basis",
    "Type",
)

PLACEHOLDER_NULLS: frozenset[str] = frozenset({"", "--"})

_DOWNLOAD_TS_RE = re.compile(
    r"^Date\s+downloaded\s+"
    r"(?P<mon>[A-Z][a-z]{2})-(?P<day>\d{2})-(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*"
    r"(?P<ampm>[ap])\.?m\.?\s*ET\s*$",
    re.IGNORECASE,
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class ParsedPosition:
    account_number: str
    account_name: str | None
    symbol: str
    description: str | None
    quantity: Decimal | None
    last_price: Decimal | None
    current_value: Decimal | None
    cost_basis_total: Decimal | None
    average_cost_basis: Decimal | None
    source_type_raw: str | None
    row_number: int


@dataclass
class ParsedFile:
    source_path: Path
    header_valid: bool
    positions: list[ParsedPosition]
    download_timestamp: datetime | None
    as_of_date: date | None
    warnings: list[str] = field(default_factory=list)


# ───────────────────────── scalar parsers ─────────────────────────

def _strip_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    return None if s in PLACEHOLDER_NULLS else s


def parse_currency(value: str | None) -> Decimal | None:
    """Parse ``$1,234.56`` / ``+$12.00`` / ``-$570.00`` / blank."""
    s = _strip_or_none(value)
    if s is None:
        return None
    negative = s.startswith("-")
    s = s.lstrip("+-").lstrip("$").replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if negative else d


def parse_quantity(value: str | None) -> Decimal | None:
    s = _strip_or_none(value)
    if s is None:
        return None
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None


def _parse_download_ts(cell: str) -> datetime | None:
    m = _DOWNLOAD_TS_RE.match(cell.strip())
    if not m:
        return None
    mon = _MONTHS.get(m.group("mon").lower())
    if not mon:
        return None
    hour = int(m.group("hour"))
    if m.group("ampm").lower() == "p" and hour != 12:
        hour += 12
    elif m.group("ampm").lower() == "a" and hour == 12:
        hour = 0
    try:
        return datetime(
            year=int(m.group("year")),
            month=mon,
            day=int(m.group("day")),
            hour=hour,
            minute=int(m.group("minute")),
        )
    except ValueError:
        return None


# ───────────────────────── main entry point ─────────────────────────

def parse_fidelity_csv(path: str | Path) -> ParsedFile:
    """Parse a Fidelity Portfolio Positions CSV file on disk."""
    path = Path(path)
    positions: list[ParsedPosition] = []
    warnings: list[str] = []
    download_ts: datetime | None = None
    header_valid = False

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        for line_no, cells in enumerate(reader, start=1):
            if line_no == 1:
                header = [c.strip() for c in cells[: len(FIDELITY_HEADER)]]
                header_valid = tuple(header) == FIDELITY_HEADER
                if not header_valid:
                    warnings.append(f"unexpected header on line 1: {header!r}")
                continue

            if not cells or all((c is None or c.strip() == "") for c in cells):
                continue  # blank

            if len(cells) == 1:
                single = cells[0].strip()
                if single.lower().startswith("date downloaded"):
                    ts = _parse_download_ts(single)
                    if ts:
                        download_ts = ts
                continue

            business = list(cells[: len(FIDELITY_HEADER)])
            while len(business) < len(FIDELITY_HEADER):
                business.append("")
            fields = {FIDELITY_HEADER[i]: business[i] for i in range(len(FIDELITY_HEADER))}

            acct = fields["Account Number"].strip()
            symbol = fields["Symbol"].strip()
            if not acct or not symbol or symbol.lower() == "pending activity":
                continue

            positions.append(ParsedPosition(
                account_number=acct,
                account_name=(fields["Account Name"].strip() or None),
                symbol=symbol,
                description=(fields["Description"].strip() or None),
                quantity=parse_quantity(fields["Quantity"]),
                last_price=parse_currency(fields["Last Price"]),
                current_value=parse_currency(fields["Current Value"]),
                cost_basis_total=parse_currency(fields["Cost Basis Total"]),
                average_cost_basis=parse_currency(fields["Average Cost Basis"]),
                source_type_raw=_strip_or_none(fields["Type"]),
                row_number=line_no,
            ))

    as_of = download_ts.date() if download_ts else None
    return ParsedFile(
        source_path=path,
        header_valid=header_valid,
        positions=positions,
        download_timestamp=download_ts,
        as_of_date=as_of,
        warnings=warnings,
    )


# ───────────────────────── helpers for callers ─────────────────────────

def hash_file_sha256(path: str | Path) -> str:
    """Return the sha256 hex digest of the file contents (for dedupe)."""
    import hashlib
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def position_payload(p: ParsedPosition, as_of: date | None) -> dict[str, Any]:
    """Shape one parsed position for a DB insert."""
    return {
        "account":              p.account_number,
        "symbol":               p.symbol,
        "quantity":             p.quantity,
        "cost_basis_total":     p.cost_basis_total,
        "cost_basis_per_share": p.average_cost_basis,
        "last_price":           p.last_price,
        "market_value":         p.current_value,
        "as_of_date":           as_of,
    }
