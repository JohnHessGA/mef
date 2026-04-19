"""Render the daily email body from a finished run's state.

Pure function — given the run metadata and (eventually) recommendation
records, produce a plain-text body and a subject line. No I/O, no DB calls,
no notify.py wiring. The renderer is testable in isolation; wiring comes
when the run pipeline decides how to deliver.

Skeleton behaviour (v0): the list of new ideas and active recommendations
is empty, so the body always reads "No new trades today." with universe
health + run metadata. Real content lands alongside the real ranker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    body: str


_SUBJECT_PREFIX = {
    "premarket":  "MEF pre-market report",
    "postmarket": "MEF post-market report",
}

_INTENT_LABEL = {
    "today_after_10am":   "trades for today (after 10:00 ET)",
    "next_trading_day":   "trades for the next trading day",
}


def render_daily_email(
    *,
    when_kind: str,
    intent: str,
    run_uid: str,
    started_at: datetime,
    stocks_in_universe: int,
    etfs_in_universe: int,
    new_ideas: list[dict[str, Any]] | None = None,
    active_updates: list[dict[str, Any]] | None = None,
    recent_score_summary: str | None = None,
) -> RenderedEmail:
    new_ideas = new_ideas or []
    active_updates = active_updates or []

    subject_prefix = _SUBJECT_PREFIX.get(when_kind, "MEF report")
    date_label = started_at.strftime("%Y-%m-%d")
    intent_label = _INTENT_LABEL.get(intent, intent)
    subject = f"{subject_prefix} — {date_label} ({intent_label})"

    lines: list[str] = [
        f"{subject_prefix}",
        "=" * len(subject_prefix),
        "",
        f"Run:      {run_uid} ({when_kind}, completed {started_at.strftime('%H:%M %Z').strip()})",
        f"Date:     {date_label}",
        f"Intent:   {intent_label}",
        f"Universe: {stocks_in_universe} stocks, {etfs_in_universe} ETFs",
        "",
    ]

    lines.append(f"New ideas ({len(new_ideas)}):")
    if not new_ideas:
        lines.append("  No new trades today.")
    else:
        for idx, idea in enumerate(new_ideas, start=1):
            lines.append(
                f"  {idx}. {idea.get('symbol','?')} — {idea.get('posture','?')} — "
                f"{idea.get('expression','?')}"
            )
            if reasoning := idea.get("reasoning_summary"):
                lines.append(f"     {reasoning}")
    lines.append("")

    lines.append(f"Active recommendations & tracked positions ({len(active_updates)}):")
    if not active_updates:
        lines.append("  None.")
    else:
        for update in active_updates:
            lines.append(
                f"  {update.get('symbol','?')}  {update.get('rec_uid','?')}  "
                f"state={update.get('state','?')}  guidance={update.get('guidance','-')}"
            )
    lines.append("")

    if recent_score_summary:
        lines.append("Scoring summary:")
        lines.append(f"  {recent_score_summary}")
        lines.append("")

    lines.append("CLI: mef show <rec-id> · mef dismiss <rec-id> · mef status")

    return RenderedEmail(subject=subject, body="\n".join(lines))
