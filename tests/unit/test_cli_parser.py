"""Unit tests for the mef CLI parser.

These tests exercise argparse wiring without hitting the DB.
"""

from __future__ import annotations

import pytest

from mef.cli import _build_parser


def test_parser_requires_subcommand():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_status_subcommand_parses():
    parser = _build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_init_db_subcommand_parses():
    parser = _build_parser()
    args = parser.parse_args(["init-db"])
    assert args.command == "init-db"


def test_run_requires_when():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])


@pytest.mark.parametrize("when", ["premarket", "postmarket"])
def test_run_when_values(when):
    parser = _build_parser()
    args = parser.parse_args(["run", "--when", when])
    assert args.when == when


def test_dismiss_requires_rec_uid():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dismiss"])
    args = parser.parse_args(["dismiss", "R-000001"])
    assert args.rec_uid == "R-000001"
