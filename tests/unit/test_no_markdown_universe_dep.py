"""Pin the rule: runtime/loader code must not read operational universe
data from markdown files (docs/, notes/, or anywhere).

Regression guard for the 2026-05-20 cleanup. If a future change re-introduces
markdown parsing for universe data, these tests should fail loudly.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


_SRC = Path(__file__).resolve().parents[2] / "src" / "mef"


def _python_files() -> list[Path]:
    return [p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_universe_parser_module_is_gone() -> None:
    """The old markdown universe parser must not exist as a module."""
    assert not (_SRC / "universe_parser.py").exists(), (
        "src/mef/universe_parser.py was removed — re-adding markdown parsing "
        "for universe data is not allowed (operational lists live in MEFDB)."
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mef.universe_parser")


def test_no_source_reads_universe_markdown_paths() -> None:
    """No src/mef/*.py may reference the legacy notes/ universe markdown paths."""
    forbidden = (
        "notes/focus-universe-us-stocks-final.md",
        "notes/core-us-etfs-daily-final.md",
    )
    hits: list[tuple[str, str]] = []
    for path in _python_files():
        text = path.read_text()
        for needle in forbidden:
            if needle in text:
                hits.append((str(path.relative_to(_SRC)), needle))
    assert hits == [], (
        f"runtime code references legacy markdown universe paths: {hits}"
    )


def test_no_source_parses_docs_markdown_for_universe() -> None:
    """No src/mef/*.py may read universe-defining .md files at runtime.

    Catches a regression where someone adds a `read_text()` on a docs/ or
    notes/ markdown file (regardless of exact filename).
    """
    smell_patterns = (
        "docs/focus-universe",
        "docs/core-us-etfs",
        "notes/focus-universe",
        "notes/core-us-etfs",
    )
    hits: list[tuple[str, str]] = []
    for path in _python_files():
        text = path.read_text()
        for smell in smell_patterns:
            if smell in text:
                hits.append((str(path.relative_to(_SRC)), smell))
    assert hits == [], (
        f"runtime code references universe markdown by path fragment: {hits}"
    )
