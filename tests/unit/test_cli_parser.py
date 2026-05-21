"""Unit tests for the mef CLI parser.

These tests exercise argparse wiring without hitting the DB.
"""

from __future__ import annotations

import pytest

from mef.cli import _build_parser


def test_bare_args_parse_with_no_command():
    """Bare `mef` parses with no subcommand set; main() reroutes to status."""
    parser = _build_parser()
    args = parser.parse_args([])
    assert getattr(args, "command", None) is None


def test_bare_mef_dispatches_to_status(monkeypatch):
    """Bare `mef` must invoke the status dispatcher, not the run pipeline.

    Pins the contract from the 2026-05-20 clarification: `mef` defaults
    to the read-only status view; only the explicit `mef run` command
    executes the pipeline.
    """
    from mef import cli as cli_mod

    called: list[str] = []

    def fake_status(args):
        called.append("status")
        return 0

    def fake_run(args):
        called.append("run")
        return 0

    monkeypatch.setattr(cli_mod, "_run_status", fake_status)
    monkeypatch.setattr(cli_mod, "_run_mef_run", fake_run)
    rc = cli_mod.main([])
    assert rc == 0
    assert called == ["status"], (
        "bare `mef` must dispatch to status (not run); "
        f"actually dispatched to: {called}"
    )


def test_mef_status_dispatches_to_status(monkeypatch):
    """Explicit `mef status` keeps dispatching to status."""
    from mef import cli as cli_mod
    called: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_status", lambda a: (called.append("status"), 0)[1])
    monkeypatch.setattr(cli_mod, "_run_mef_run", lambda a: (called.append("run"), 0)[1])
    cli_mod.main(["status"])
    assert called == ["status"]


def test_mef_run_dispatches_to_run(monkeypatch):
    """Explicit `mef run` is the only thing that triggers the pipeline."""
    from mef import cli as cli_mod
    called: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_status", lambda a: (called.append("status"), 0)[1])
    monkeypatch.setattr(cli_mod, "_run_mef_run", lambda a: (called.append("run"), 0)[1])
    cli_mod.main(["run"])
    assert called == ["run"]


def test_mef_help_flag_does_not_dispatch(capsys):
    """`mef -h` must still print help without running anything (argparse
    raises SystemExit(0) before reaching main's dispatcher)."""
    from mef import cli as cli_mod
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main(["-h"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "usage: mef" in out


@pytest.mark.parametrize("name", ["status", "health", "run", "universe"])
def test_active_subcommands_parse(name):
    parser = _build_parser()
    args = parser.parse_args([name])
    assert args.command == name


def test_run_defaults_to_neutral_when_kind_run():
    """Step 2 contract: bare `mef run` now stamps when_kind='run' (the
    neutral value allowed by migration 014). The runtime does not branch
    on it; this is purely for dashboard column population."""
    parser = _build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.when == "run"


def test_run_send_email_defaults_off():
    parser = _build_parser()
    args = parser.parse_args(["run"])
    assert args.send_email is False


def test_run_send_email_opt_in():
    parser = _build_parser()
    args = parser.parse_args(["run", "--send-email"])
    assert args.send_email is True


@pytest.mark.parametrize("when", ["premarket", "postmarket", "run"])
def test_run_when_still_accepted_for_backcompat(when):
    """Hidden --when accepts the legacy two values plus the neutral 'run'.
    The legacy values are kept so the deprecated alias dispatchers — and
    any external cron lines still passing --when explicitly — keep
    working unchanged."""
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


# ─────────────────────────────────────────────────────────────────────────
# Single-run-model contract: all three entry points dispatch to the same
# underlying function so behavior is identical regardless of which alias
# cron / a user types.
# ─────────────────────────────────────────────────────────────────────────


def _resolves_to(func, target_name: str) -> bool:
    """True if `func` is `target_name` or a closure wrapping `target_name`."""
    if getattr(func, "__name__", None) == target_name:
        return True
    # _deprecated() wraps via a plain closure (no functools.wraps); check
    # cellvars for the captured inner function.
    closure = getattr(func, "__closure__", None) or ()
    for cell in closure:
        contents = getattr(cell, "cell_contents", None)
        if callable(contents) and getattr(contents, "__name__", None) == target_name:
            return True
    return False


@pytest.mark.parametrize("argv", [
    ["run"],
    ["run", "--send-email"],
    ["premarket-run"],
    ["postmarket-run"],
])
def test_run_aliases_dispatch_to_same_function(argv):
    """Every run-style alias routes to _run_mef_run, either directly or
    through the _deprecated() wrapper. This is the structural guarantee
    that 'MEF has a single run behavior' regardless of which entry point
    fires it."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    assert _resolves_to(args.func, "_run_mef_run"), (
        f"argv {argv!r} dispatched to {args.func} which does not "
        f"resolve to _run_mef_run"
    )


def test_premarket_alias_preserves_when_kind_for_grafana_compat():
    parser = _build_parser()
    args = parser.parse_args(["premarket-run"])
    # The when_kind value still has to satisfy mef.daily_run's CHECK
    # constraint AND keep the Grafana dashboard's existing column happy.
    assert args.when == "premarket"
    assert args.send_email is True


def test_postmarket_alias_preserves_when_kind_for_grafana_compat():
    parser = _build_parser()
    args = parser.parse_args(["postmarket-run"])
    assert args.when == "postmarket"
    assert args.send_email is True
