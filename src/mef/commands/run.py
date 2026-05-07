"""`mef run` — execute the MEF pipeline.

Writes a ``mef.daily_run`` row plus candidates/recommendations and renders
an email body. Email is *not* sent unless ``--send-email`` is passed; the
rendered subject + body are printed to stdout for review.
"""

from __future__ import annotations

from mef.run_pipeline import execute


def run(args) -> int:
    when = getattr(args, "when", "postmarket") or "postmarket"
    send_email = bool(getattr(args, "send_email", False))
    summary = execute(when, dry_run=not send_email)

    print(f"MEF run — {summary['when_kind']} ({summary['intent']})")
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
