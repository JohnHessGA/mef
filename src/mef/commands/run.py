"""`mef run` — execute the MEF pipeline.

Writes a ``mef.daily_run`` row plus candidates/recommendations and renders
an email body. Email is *not* sent unless ``--send-email`` is passed; the
rendered subject + body are printed to stdout for review.

MEF has a single run behavior. The ``--when`` argument and the legacy
``premarket-run`` / ``postmarket-run`` aliases still exist as compatibility
wrappers, but they all execute the same code path. Scheduling decides
when the run fires; the tool does not branch on the nominal window.
"""

from __future__ import annotations

from mef.run_pipeline import execute


def run(args) -> int:
    # Default is now the neutral 'run' (migration 014 widened the CHECK
    # constraint to allow it). The runtime does not branch on this value;
    # it is stamped on mef.daily_run.when_kind so the Grafana dashboard
    # still has a populated column. The deprecated `premarket-run` /
    # `postmarket-run` aliases override the default with their legacy
    # value for historical dashboard continuity.
    when = getattr(args, "when", "run") or "run"
    send_email = bool(getattr(args, "send_email", False))
    summary = execute(when, dry_run=not send_email)

    print(f"MEF run — {summary['run_uid']}")
    print("=" * 46)
    if not send_email:
        print("  email send:              SKIPPED (use --send-email to send)")
    print(f"  run uid:                 {summary['run_uid']}")
    print(f"  as-of date:              {summary.get('as_of_date', '?')}")
    print(f"  universe total:          {summary.get('universe_total', '?')}")
    print(f"  symbols evaluated:       {summary.get('symbols_evaluated', '?')}")
    print(f"  candidates passed:       {summary.get('candidates_passed', '?')}")
    print(f"  top-N sent to gate:      {summary.get('top_n', '?')}")
    print(f"  gate: available={summary.get('gate_available')} "
          f"approve={summary.get('gate_approved')} "
          f"review={summary.get('gate_review', 0)} "
          f"reject={summary.get('gate_rejected')} "
          f"unavailable={summary.get('gate_unavailable')}")
    print(f"  lifecycle sweep: expired={summary.get('lifecycle_expired', 0)} "
          f"closed={summary.get('lifecycle_closed', 0)}  "
          f"scored={summary.get('scored', 0)}")
    print(f"  recommendations emitted: {summary['recommendations_emitted']}")

    send = summary.get("email_send") or {}
    if send.get("sent"):
        print(f"  email: sent to {', '.join(send.get('recipients') or [])} at {send.get('sent_at')}")
    elif send.get("skipped_reason"):
        print(f"  email: skipped ({send['skipped_reason']})")
    elif send.get("error"):
        print(f"  email: NOT SENT — {send['error']}")
    print()
    print("Rendered email body:")
    print("-" * 46)
    print(f"Subject: {summary['email_subject']}")
    print()
    print(summary["email_body"])
    print("-" * 46)
    return 0
