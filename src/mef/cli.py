"""MEF command-line entry point.

Subcommands (target set per docs/README_mef.md §"User Experience / CLI"):

- mef run --when {premarket|postmarket} — scheduled daily run
- mef status                            — environment & data-source overview
- mef init-db                           — apply MEFDB migrations
- mef universe [load]                   — show or reload the 305+15 universe
- mef recommendations [...]             — list recommendations by state
- mef show <rec-id>                     — detail on a recommendation
- mef dismiss <rec-id>                  — mark a proposed rec as not-implemented
- mef import-positions <csv>            — ingest a Fidelity Positions CSV
- mef score                             — refresh scoring on closed recs
- mef report --when {premarket|postmarket} — render email body without sending

Currently implemented: `status`, `init-db`. Other commands stub out.
"""

from __future__ import annotations

import argparse
import sys


# ───────────────────────────── subcommand defs ─────────────────────────────

def _add_run(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("run", help="Execute one scheduled MEF run.")
    p.add_argument(
        "--when",
        required=True,
        choices=["premarket", "postmarket"],
        help="Which scheduled run this is.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but skip sending the email.",
    )
    p.set_defaults(func=_run_mef_run)


def _add_status(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("status", help="Show environment and data-source status.")
    p.set_defaults(func=_run_status)


def _add_init_db(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init-db", help="Apply MEFDB schema migrations (idempotent).")
    p.set_defaults(func=_run_init_db)


def _add_universe(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("universe", help="Show or reload the 305+15 universe.")
    p.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "load"],
        help="'show' (default) prints the current universe; 'load' syncs MEFDB from the notes files.",
    )
    p.set_defaults(func=_run_universe)


def _add_recommendations(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("recommendations", help="List recommendations by lifecycle state.")
    p.add_argument("--state", help="Filter by lifecycle state (proposed, active, closed_win, ...).")
    p.add_argument("--all", action="store_true", help="Include closed/expired/dismissed.")
    p.add_argument("--symbol", help="Filter by symbol.")
    p.add_argument("--since", help="Only recs emitted on/after this date (YYYY-MM-DD).")
    p.add_argument("--limit", type=int, help="Max rows to show (default 30).")
    p.set_defaults(func=_run_recommendations)


def _add_show(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("show", help="Show full detail on a recommendation.")
    p.add_argument("uid", help="Recommendation UID (e.g., R-000042).")
    p.set_defaults(func=_run_show)


def _add_dismiss(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("dismiss", help="Mark a proposed recommendation as not-implemented.")
    p.add_argument("rec_uid", help="Recommendation UID (e.g., R-000042).")
    p.add_argument("--note", help="Optional reason.")
    p.set_defaults(func=_run_dismiss)


def _add_import_positions(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("import-positions", help="Ingest a Fidelity Portfolio Positions CSV.")
    p.add_argument("csv_path", help="Path to the Fidelity Portfolio Positions CSV.")
    p.set_defaults(func=_run_import_positions)


def _add_score(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("score", help="Refresh scoring on closed recommendations.")
    p.set_defaults(func=_run_score)


def _add_rejections(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("rejections", help="List LLM-rejected candidates for audit.")
    p.add_argument("--symbol", help="Filter by symbol.")
    p.add_argument("--since", help="Only rejections on/after this date (YYYY-MM-DD).")
    p.add_argument("--limit", type=int, help="Max rows to show (default 20).")
    p.set_defaults(func=_run_rejections)


def _add_gate_audit(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "gate-audit",
        help="Compare approved vs rejected outcome distributions to test if the LLM gate helps.",
    )
    p.set_defaults(func=_run_gate_audit)


def _add_tag(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "tag",
        help="Override the inferred activation provenance on a recommendation.",
    )
    p.add_argument("rec_uid", help="Recommendation UID (e.g., R-000042).")
    p.add_argument(
        "--provenance",
        required=True,
        choices=["mef_attributed", "pre_existing", "independent"],
        help="What actually drove the position match.",
    )
    p.set_defaults(func=_run_tag)


def _add_link_trade(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "link-trade",
        help="Record the actual buy/sell on a scored recommendation.",
    )
    p.add_argument("rec_uid", help="Recommendation UID (e.g., R-000042).")
    p.add_argument("--qty",         required=True, type=float, help="Shares traded.")
    p.add_argument("--buy-price",   required=True, type=float, help="Actual buy fill price.")
    p.add_argument("--buy-date",    required=True, help="Buy date (YYYY-MM-DD).")
    p.add_argument("--sell-price",  type=float, help="Actual sell fill price (optional while holding).")
    p.add_argument("--sell-date",   help="Sell date (YYYY-MM-DD; optional while holding).")
    p.set_defaults(func=_run_link_trade)


def _add_report(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("report", help="Render the email report for a given run without sending.")
    p.add_argument(
        "--when",
        required=True,
        choices=["premarket", "postmarket"],
        help="Which report to render.",
    )
    p.add_argument("--run", help="Specific run UID (defaults to latest matching --when).")
    p.set_defaults(func=_run_report)


# ───────────────────────────── dispatchers ─────────────────────────────

def _stub(name: str):
    def _unimplemented(args) -> int:
        print(f"mef {name}: not yet implemented.", file=sys.stderr)
        return 2
    return _unimplemented


def _run_status(args) -> int:
    from mef.commands import status
    return status.run(args)


def _run_init_db(args) -> int:
    from mef.commands import init_db
    return init_db.run(args)


def _run_universe(args) -> int:
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
    sub = parser.add_subparsers(dest="command", required=True)
    _add_run(sub)
    _add_status(sub)
    _add_init_db(sub)
    _add_universe(sub)
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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
