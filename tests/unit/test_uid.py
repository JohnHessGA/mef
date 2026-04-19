"""Unit tests for mef.uid — prefix map + validation."""

from __future__ import annotations

import pytest

from mef.uid import NO_UID_TABLES, UID_PREFIX, next_uid


def test_prefix_map_covers_expected_tables():
    # Spot-check the core lifecycle tables.
    assert UID_PREFIX["daily_run"] == "DR"
    assert UID_PREFIX["candidate"] == "C"
    assert UID_PREFIX["recommendation"] == "R"
    assert UID_PREFIX["score"] == "S"
    assert UID_PREFIX["llm_trace"] == "L"


def test_no_overlap_between_prefix_map_and_no_uid_tables():
    assert UID_PREFIX.keys().isdisjoint(NO_UID_TABLES)


def test_next_uid_rejects_no_uid_table():
    with pytest.raises(ValueError):
        next_uid(conn=None, table="universe_stock")


def test_next_uid_rejects_unknown_table():
    with pytest.raises(ValueError):
        next_uid(conn=None, table="never_heard_of_this")
