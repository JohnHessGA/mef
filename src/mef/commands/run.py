"""`mef run --when {premarket|postmarket}` — skeleton daily run.

v0: executes the pipeline in ``mef.run_pipeline``, which writes a
``mef.daily_run`` row and renders an email body. Delivery via notify.py is
not yet wired — the rendered subject + body are printed to stdout so the
operator can preview what the scheduled run would send.
"""

from __future__ import annotations

from mef.run_pipeline import execute


def run(args) -> int:
    summary = execute(args.when)

    print(f"MEF run — {summary['when_kind']} ({summary['intent']})")
    print("=" * 46)
    print(f"  run uid:                 {summary['run_uid']}")
    print(f"  as-of date:              {summary.get('as_of_date', '?')}")
    print(f"  universe total:          {summary.get('universe_total', '?')}")
    print(f"  symbols evaluated:       {summary.get('symbols_evaluated', '?')}")
    print(f"  candidates passed:       {summary.get('candidates_passed', '?')}")
    print(f"  top-N sent to gate:      {summary.get('top_n', '?')}")
    print(f"  gate: available={summary.get('gate_available')} "
          f"approve={summary.get('gate_approved')} "
          f"reject={summary.get('gate_rejected')} "
          f"unavailable={summary.get('gate_unavailable')}")
    print(f"  recommendations emitted: {summary['recommendations_emitted']}")
    print()
    print("Rendered email (delivery not yet wired):")
    print("-" * 46)
    print(f"Subject: {summary['email_subject']}")
    print()
    print(summary["email_body"])
    print("-" * 46)
    return 0
