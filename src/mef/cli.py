"""MEF command-line entry point.

Target shape (AFT style — bare verbs, no required flags):

    mef             show this help
    mef status      current user-facing recommendation/report view
    mef run         run the pipeline (no email by default)
    mef health      environment / DB / freshness checks
    mef universe    show the 305-stock + 20-ETF universe

The following subcommands are *deprecated* and pending removal in a
future cleanup. They still work for the moment so existing scripts and
the operator's muscle memory don't break, but their `--help` output
is prefixed with "[DEPRECATED]" and stderr emits a one-line notice
when they run:

    init-db, report, recommendations, show, dismiss, import-positions,
    score, rejections, gate-audit, tag, link-trade, universe load

DB initialization is one-time setup and should be documented; it is
no longer part of the normal CLI surface.
"""

from __future__ import annotations

import argparse
import sys


DEPRECATED_NOTE = (
    "[DEPRECATED] {name} — pending removal; do not rely on this command."
)


# ───────────────────────────── subcommand defs ─────────────────────────────

def _add_run(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run",
        help="Run the MEF pipeline (no email by default).",
        description=(
            "Run the MEF pipeline. Writes a daily_run + candidates + "
            "recommendations to MEFDB and renders an email body, but "
            "does NOT send email unless --send-email is passed."
        ),
    )
    # --when is now optional and informational. The pipeline produces the
    # best slate it can from current data regardless of which window we're
    # nominally in. Kept for backward compatibility with cron entries.
    p.add_argument(
        "--when",
        choices=["premarket", "postmarket"],
        default="postmarket",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--send-email",
        action="store_true",
        help="Send the rendered email (default: do not send).",
    )
    p.set_defaults(func=_run_mef_run)


def _add_status(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "status",
        help="Current MEF recommendations and ETF posture (read-only).",
    )
    p.set_defaults(func=_run_status)


def _add_health(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "health",
        help="Environment, DB, SHDB/MEFDB, freshness, latest run, warnings.",
    )
    p.set_defaults(func=_run_health)


def _add_universe(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "universe",
        help="Show the 305-stock + 20-ETF universe.",
    )
    p.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "load"],
        help="'show' (default) prints the universe; 'load' is [DEPRECATED] (pending removal).",
    )
    p.set_defaults(func=_run_universe)


# ── Deprecated commands (kept but marked) ──

def _add_init_db(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "init-db",
        help="[DEPRECATED] Apply MEFDB migrations. Use psql + sql/mefdb/*.sql instead.",
    )
    p.set_defaults(func=_deprecated("init-db", _run_init_db))


def _add_recommendations(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "recommendations",
        help="[DEPRECATED] Historical-rec list. Use `mef status` for current recommendations.",
    )
    p.add_argument("--state")
    p.add_argument("--all", action="store_true")
    p.add_argument("--symbol")
    p.add_argument("--since")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=_deprecated("recommendations", _run_recommendations))


def _add_show(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "show",
        help="[DEPRECATED] Show full detail on a recommendation.",
    )
    p.add_argument("uid")
    p.set_defaults(func=_deprecated("show", _run_show))


def _add_dismiss(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "dismiss",
        help="[DEPRECATED] Mark a proposed recommendation as not-implemented.",
    )
    p.add_argument("rec_uid")
    p.add_argument("--note")
    p.set_defaults(func=_deprecated("dismiss", _run_dismiss))


def _add_import_positions(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "import-positions",
        help="[DEPRECATED] Ingest a Fidelity Positions CSV. MEF will read PHDB instead.",
    )
    p.add_argument("csv_path")
    p.set_defaults(func=_deprecated("import-positions", _run_import_positions))


def _add_score(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "score",
        help="[DEPRECATED] Refresh scoring on closed recommendations.",
    )
    p.set_defaults(func=_deprecated("score", _run_score))


def _add_rejections(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "rejections",
        help="[DEPRECATED] LLM-gate debugging.",
    )
    p.add_argument("--symbol")
    p.add_argument("--since")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=_deprecated("rejections", _run_rejections))


def _add_gate_audit(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "gate-audit",
        help="[DEPRECATED] LLM-gate outcome comparison.",
    )
    p.set_defaults(func=_deprecated("gate-audit", _run_gate_audit))


def _add_tag(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "tag",
        help="[DEPRECATED] Override the inferred activation provenance on a recommendation.",
    )
    p.add_argument("rec_uid")
    p.add_argument(
        "--provenance",
        required=True,
        choices=["mef_attributed", "pre_existing", "independent"],
    )
    p.set_defaults(func=_deprecated("tag", _run_tag))


def _add_link_trade(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "link-trade",
        help="[DEPRECATED] Record actual buy/sell on a scored recommendation.",
    )
    p.add_argument("rec_uid")
    p.add_argument("--qty",        required=True, type=float)
    p.add_argument("--buy-price",  required=True, type=float)
    p.add_argument("--buy-date",   required=True)
    p.add_argument("--sell-price", type=float)
    p.add_argument("--sell-date")
    p.set_defaults(func=_deprecated("link-trade", _run_link_trade))


def _add_report(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "report",
        help="[DEPRECATED] Render the email body. Use `mef status` for current recs.",
    )
    p.add_argument(
        "--when",
        required=True,
        choices=["premarket", "postmarket"],
    )
    p.add_argument("--run")
    p.set_defaults(func=_deprecated("report", _run_report))


# ───────────────────────────── dispatchers ─────────────────────────────

def _deprecated(name: str, inner):
    """Wrap a dispatcher with a stderr deprecation notice."""
    def _wrapped(args) -> int:
        print(DEPRECATED_NOTE.format(name=name), file=sys.stderr)
        return inner(args)
    return _wrapped


def _run_status(args) -> int:
    from mef.commands import status
    return status.run(args)


def _run_health(args) -> int:
    from mef.commands import health
    return health.run(args)


def _run_init_db(args) -> int:
    from mef.commands import init_db
    return init_db.run(args)


def _run_universe(args) -> int:
    if getattr(args, "action", "show") == "load":
        print(DEPRECATED_NOTE.format(name="universe load"), file=sys.stderr)
    from mef.commands import universe
    return universe.run(args)


def _run_mef_run(args) -> int:
    from mef.commands import run as run_cmd
    return run_cmd.run(args)


def _run_import_positions(args) -> int:
    from mef.commands import import_positions
    return import_positions.run(args)


def _run_dismiss(args) -> int:
    from mef.commands import dismiss
    return dismiss.run(args)


def _run_recommendations(args) -> int:
    from mef.commands import recommendations
    return recommendations.run(args)


def _run_show(args) -> int:
    from mef.commands import show
    return show.run(args)


def _run_score(args) -> int:
    from mef.commands import score
    return score.run(args)


def _run_rejections(args) -> int:
    from mef.commands import rejections
    return rejections.run(args)


def _run_gate_audit(args) -> int:
    from mef.commands import gate_audit
    return gate_audit.run(args)


def _run_tag(args) -> int:
    from mef.commands import tag
    return tag.run(args)


def _run_link_trade(args) -> int:
    from mef.commands import link_trade
    return link_trade.run(args)


def _run_report(args) -> int:
    from mef.commands import report
    return report.run(args)


# ───────────────────────────── parser wiring ─────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mef",
        description="Muse Engine Forecaster — daily forecasting and recommendation tool.",
    )
    sub = parser.add_subparsers(dest="command")

    # Active commands
    _add_status(sub)
    _add_run(sub)
    _add_health(sub)
    _add_universe(sub)

    # Deprecated commands (still parseable, marked in --help)
    _add_init_db(sub)
    _add_recommendations(sub)
    _add_show(sub)
    _add_dismiss(sub)
    _add_import_positions(sub)
    _add_score(sub)
    _add_rejections(sub)
    _add_gate_audit(sub)
    _add_tag(sub)
    _add_link_trade(sub)
    _add_report(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
