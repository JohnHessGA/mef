"""Provenance inference for auto-activations.

Pure function: given the symbol's earliest known position date, the rec's
creation date, and the rec's entry_window_end, classify how the position
came to match the recommendation.
"""

from __future__ import annotations

from datetime import date

from mef.positions.activator import infer_provenance


def test_pre_existing_when_position_predates_rec():
    # Symbol was already in our positions before the rec was even created.
    out = infer_provenance(
        earliest_position_date=date(2026, 3, 15),
        rec_created_date=date(2026, 4, 1),
        entry_window_end=date(2026, 4, 8),
    )
    assert out == "pre_existing"


def test_mef_attributed_when_position_appears_during_entry_window():
    # First saw the symbol in positions on day 3 of a 7-day window after the rec.
    out = infer_provenance(
        earliest_position_date=date(2026, 4, 4),
        rec_created_date=date(2026, 4, 1),
        entry_window_end=date(2026, 4, 8),
    )
    assert out == "mef_attributed"


def test_mef_attributed_when_position_appears_same_day_as_rec():
    # Boundary: position date == rec created date is still inside the window.
    out = infer_provenance(
        earliest_position_date=date(2026, 4, 1),
        rec_created_date=date(2026, 4, 1),
        entry_window_end=date(2026, 4, 8),
    )
    assert out == "mef_attributed"


def test_mef_attributed_when_position_appears_on_window_end():
    # Boundary: position date == entry_window_end is still inside the window.
    out = infer_provenance(
        earliest_position_date=date(2026, 4, 8),
        rec_created_date=date(2026, 4, 1),
        entry_window_end=date(2026, 4, 8),
    )
    assert out == "mef_attributed"


def test_independent_when_position_appears_after_window():
    out = infer_provenance(
        earliest_position_date=date(2026, 4, 12),
        rec_created_date=date(2026, 4, 1),
        entry_window_end=date(2026, 4, 8),
    )
    assert out == "independent"


def test_independent_when_no_entry_window_end():
    # No window to attribute against — the safe default is independent.
    out = infer_provenance(
        earliest_position_date=date(2026, 4, 4),
        rec_created_date=date(2026, 4, 1),
        entry_window_end=None,
    )
    assert out == "independent"


def test_independent_when_no_position_history():
    # earliest_position_date=None → no signal at all → independent.
    out = infer_provenance(
        earliest_position_date=None,
        rec_created_date=date(2026, 4, 1),
        entry_window_end=date(2026, 4, 8),
    )
    assert out == "independent"
