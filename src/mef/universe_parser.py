"""Parse the curated-universe markdown files in ``notes/``.

Two pure-function entry points:

- ``parse_stocks(text)`` → list of dicts, one per row of the stock table in
  ``notes/focus-universe-us-stocks-final.md``.
- ``parse_etfs(text)`` → list of dicts, one per bullet in
  ``notes/core-us-etfs-daily-final.md``.

Neither function touches the database or the filesystem. That's left to
``mef.universe_loader``.
"""

from __future__ import annotations

import re
from typing import Any

# ──────────────────────────────────────────────────────────────────────────
# Number parsing helpers
# ──────────────────────────────────────────────────────────────────────────

_MULTIPLIER = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}


def _clean(text: str) -> str:
    return text.strip()


def _parse_currency_float(cell: str) -> float | None:
    """Parse a plain currency like ``$123.28`` → 123.28."""
    cell = _clean(cell).lstrip("$").replace(",", "")
    if not cell:
        return None
    return float(cell)


def _parse_int_with_commas(cell: str) -> int | None:
    """Parse an integer with thousands separators like ``2,204,554`` → 2204554."""
    cell = _clean(cell).replace(",", "")
    if not cell:
        return None
    return int(cell)


def _parse_abbreviated_dollars(cell: str) -> int | None:
    """Parse ``$272M`` / ``$4.57B`` / ``$4.05T`` → absolute-dollar integer.

    Returns a whole-dollar count. Examples:
        $272M  → 272_000_000
        $4.57B → 4_570_000_000
        $4.05T → 4_050_000_000_000
    """
    cell = _clean(cell).lstrip("$").replace(",", "")
    if not cell:
        return None
    suffix = cell[-1].upper()
    if suffix in _MULTIPLIER:
        value = float(cell[:-1]) * _MULTIPLIER[suffix]
        return int(round(value))
    return int(round(float(cell)))


# ──────────────────────────────────────────────────────────────────────────
# Stocks
# ──────────────────────────────────────────────────────────────────────────

_STOCK_HEADER_KEYS = (
    "symbol", "name", "sector", "industry", "avg_close", "avg_vol",
    "avg_dollar_vol", "market_cap", "expirations", "total_oi",
)


def _is_markdown_separator(row_cells: list[str]) -> bool:
    """A markdown-table separator row contains only dashes and colons."""
    return all(re.fullmatch(r":?-+:?", c) for c in row_cells if c)


def _is_stock_header(cells: list[str]) -> bool:
    """Return True iff this row is the header for the 305-stock table.

    Anchors on the first cell being 'Symbol' and the cell count matching our
    expected schema. That's specific enough to distinguish the stock table
    from the Sector Distribution table or any other pipe-delimited block in
    the same file.
    """
    return (
        len(cells) == len(_STOCK_HEADER_KEYS)
        and cells[0].strip().lower() == "symbol"
    )


def parse_stocks(text: str) -> list[dict[str, Any]]:
    """Extract stock rows from the 305-stock notes file.

    The file contains multiple pipe-delimited tables (Sector Distribution,
    Stock List). We scan for the 'Symbol' header row with the full 10-column
    shape, skip its ``|----|`` separator, and yield one dict per data row
    until the table ends (a non-pipe or blank line).

    Raises ``ValueError`` if no stock rows are found.
    """
    stocks: list[dict[str, Any]] = []
    in_target_table = False
    separator_seen = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_target_table:
                # End-of-table: a blank line or prose closes the block.
                break
            continue

        cells = [_clean(c) for c in stripped.strip("|").split("|")]

        if not in_target_table:
            if _is_stock_header(cells):
                in_target_table = True
                separator_seen = False
            continue

        if not separator_seen:
            if _is_markdown_separator(cells):
                separator_seen = True
            continue

        if len(cells) != len(_STOCK_HEADER_KEYS):
            continue

        row = dict(zip(_STOCK_HEADER_KEYS, cells))
        stocks.append({
            "symbol":                row["symbol"],
            "company_name":          row["name"],
            "sector":                row["sector"],
            "industry":              row["industry"],
            "avg_close_90d":         _parse_currency_float(row["avg_close"]),
            "avg_volume_90d":        _parse_int_with_commas(row["avg_vol"]),
            "avg_dollar_volume_90d": _parse_abbreviated_dollars(row["avg_dollar_vol"]),
            "market_cap_usd":        _parse_abbreviated_dollars(row["market_cap"]),
            "options_expirations":   _parse_int_with_commas(row["expirations"]),
            "total_open_interest":   _parse_int_with_commas(row["total_oi"]),
        })

    if not stocks:
        raise ValueError("No stock rows found — is the notes file malformed?")
    return stocks


# ──────────────────────────────────────────────────────────────────────────
# ETFs
# ──────────────────────────────────────────────────────────────────────────

_SECTION_ROLE_MAP = {
    "Broad Market":     "broad_market",
    "Size":             "size",
    "Style / Factor":   "style",
    "Core Sector ETFs": "sector",
    "Industry ETF":     "industry",
}

_SECTION_RE = re.compile(r"^\s*###\s+(.+?)\s*(?:\(\d+\))?\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+\*\*([A-Z.]+)\*\*\s+[—–-]\s+(.+?)\s*$")


def parse_etfs(text: str) -> list[dict[str, Any]]:
    """Extract ETF rows from the 15-ETF notes file.

    The file is organised as ``### Section`` headings followed by bullet
    lines ``- **SYM** — description``. The current section determines the
    role tag written to ``mef.universe_etf``.

    Raises ``ValueError`` if no ETF bullets are found.
    """
    etfs: list[dict[str, Any]] = []
    current_role: str | None = None

    for line in text.splitlines():
        if match := _SECTION_RE.match(line):
            section = match.group(1).strip()
            current_role = _SECTION_ROLE_MAP.get(section)
            continue

        if current_role is None:
            continue

        if match := _BULLET_RE.match(line):
            symbol, description = match.group(1), match.group(2).strip()
            etfs.append({
                "symbol":      symbol,
                "role":        current_role,
                "description": description,
            })

    if not etfs:
        raise ValueError("No ETF bullets found — is the notes file malformed?")
    return etfs
