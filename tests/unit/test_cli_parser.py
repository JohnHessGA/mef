"""Unit tests for the mef CLI parser.

These tests exercise argparse wiring without hitting the DB.
"""

from __future__ import annotations

import pytest

from mef.cli import _build_parser


def test_bare_args_parse_with_no_command():
    """Bare `mef` should parse cleanly so main() can render --help."""
    parser = _build_parser()
    args = parser.parse_args([])
    assert getattr(args, "command", None) is None


@pytest.mark.parametrize("name", ["status", "health", "run", "universe"])
def test_active_subcommands_parse(name):
    parser = _build_parser()
    args = parser.parse_args([name])
    assert args.command == name


def test_run_does_not_require_when():
    parser = _build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    # --when is no longer required and defaults to a single canonical value.
    assert getattr(args, "when", None) in ("postmarket", "premarket")


def test_run_send_email_defaults_off():
    parser = _build_parser()
    args = parser.parse_args(["run"])
    assert args.send_email is False


def test_run_send_email_opt_in():
    parser = _build_parser()
    args = parser.parse_args(["run", "--send-email"])
    assert args.send_email is True


@pytest.mark.parametrize("when", ["premarket", "postmarket"])
def test_run_when_still_accepted_for_backcompat(when):
    parser = _build_parser()
    args = parser.parse_args(["run", "--when", when])
    assert args.when == when


def test_universe_defaults_to_show():
    parser = _build_parser()
    args = parser.parse_args(["universe"])
    assert args.command == "universe"
    assert args.action == "show"


def test_deprecated_init_db_still_parses():
    parser = _build_parser()
    args = parser.parse_args(["init-db"])
    assert args.command == "init-db"


def test_deprecated_dismiss_still_parses():
    parser = _build_parser()
    args = parser.parse_args(["dismiss", "R-000001"])
    assert args.rec_uid == "R-000001"
