"""Render the daily email body from a finished run's state.

Pure function — given the run metadata, emitted ideas, and LLM-gate status,
produce a plain-text body and a subject line. No I/O, no DB calls, no
notify.py wiring.

Each emitted idea carries an estimated P&L block (potential gain / loss
per 100 shares and risk/reward ratio), computed upstream in
``mef.run_pipeline``.
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


def _fmt_money(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "n/a"


def _fmt_ratio(v: float | None) -> str:
    return f"{v:.2f}:1" if v is not None else "n/a"


def _idea_lines(idx: int, idea: dict[str, Any]) -> list[str]:
    symbol = idea.get("symbol", "?")
    posture = idea.get("posture", "?")
    expression = idea.get("expression", "?")
    lines = [f"  {idx}. {symbol} — {posture} — {expression}"]

    entry_zone = idea.get("entry_zone")
    if entry_zone:
        lines.append(f"     Entry zone: {entry_zone}")
    stop = idea.get("stop")
    target = idea.get("target")
    time_exit = idea.get("time_exit")
    if stop is not None:
        lines.append(f"     Stop:       ${stop:,.2f}")
    if target is not None:
        lines.append(f"     Target:     ${target:,.2f}")
    if time_exit is not None:
        lines.append(f"     Time exit:  {time_exit}")

    gain = idea.get("potential_gain_100sh")
    loss = idea.get("potential_loss_100sh")
    rr = idea.get("risk_reward")
    if gain is not None or loss is not None:
        lines.append(
            f"     Per 100 shares: potential +{_fmt_money(gain)} · "
            f"risk {_fmt_money(loss)} · R:R {_fmt_ratio(rr)}"
        )

    reasoning = idea.get("reasoning_summary")
    if reasoning:
        lines.append(f"     Reasoning:  {reasoning}")

    gate = idea.get("llm_gate")
    if gate == "unavailable":
        lines.append("     ⚠ Not reviewed by LLM (gate unavailable).")
    return lines


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
    llm_gate_available: bool = True,
    llm_gate_rejected: int = 0,
    llm_gate_review: int = 0,
    staleness_warning: str | None = None,
    staleness_aborted: bool = False,
) -> RenderedEmail:
    new_ideas = new_ideas or []
    active_updates = active_updates or []

    subject_prefix = _SUBJECT_PREFIX.get(when_kind, "MEF report")
    date_label = started_at.strftime("%Y-%m-%d")
    intent_label = _INTENT_LABEL.get(intent, intent)
    subject = f"{subject_prefix} — {date_label} ({intent_label})"
    if staleness_aborted:
        subject = f"[STALE DATA] {subject}"

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

    if staleness_aborted:
        lines.append("⛔ RUN ABORTED — input data is too stale to trust.")
        lines.append(f"   {staleness_warning}")
        lines.append("   No ideas were generated this run. Check whether the UDC daily")
        lines.append("   harvest succeeded; once the mart tables are fresh again, the")
        lines.append("   next scheduled run will resume normal operation.")
        lines.append("")
    elif staleness_warning:
        lines.append("⚠ Input data is older than expected — proceeding with caution.")
        lines.append(f"   {staleness_warning}")
        lines.append("")

    if not llm_gate_available and not staleness_aborted:
        lines.append("⚠ LLM gate was unavailable for this run — ideas below were not reviewed.")
        lines.append("")

    lines.append(f"New ideas ({len(new_ideas)}):")
    if not new_ideas:
        lines.append("  No new trades today.")
    else:
        for idx, idea in enumerate(new_ideas, start=1):
            lines.extend(_idea_lines(idx, idea))

    # Quiet footer noting what was withheld from the email — concise.
    # Both review and reject items live in the DB; the user can pull them
    # via `mef recommendations --state proposed` and `mef rejections`.
    held_parts: list[str] = []
    if llm_gate_review:
        held_parts.append(f"{llm_gate_review} held for review")
    if llm_gate_rejected:
        held_parts.append(f"{llm_gate_rejected} rejected")
    if held_parts:
        lines.append("")
        lines.append(f"  Also from this run: {', '.join(held_parts)} (logged for audit).")
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
