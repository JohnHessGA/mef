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


def _unavailable_reason_suffix(kind: str | None) -> str:
    """Human-friendly suffix for the 'LLM gate was unavailable' banner.

    Maps the GateResult.unavailable_kind classification to a short
    'due to <reason>' fragment. Kept in one place so the mapping is
    easy to adjust when new failure classes are added.
    """
    if kind == "timeout":
        return " due to LLM timeouts"
    if kind == "parse":
        return " due to an unparseable LLM response"
    if kind == "error":
        return " due to an LLM subprocess error"
    return ""


_ENGINE_LABELS = {
    "trend":          "trend",
    "mean_reversion": "mean-rev",
    "value":          "value",
}


def _engine_badge(source_engines: list[str] | None) -> str:
    """Format an engine-lineage badge. Multi-engine picks get
    trend+value-style joined labels; single-engine gets the bare name.
    """
    if not source_engines:
        return ""
    labels = [_ENGINE_LABELS.get(e, e) for e in source_engines]
    if len(labels) == 1:
        return f"  [engine: {labels[0]}]"
    return f"  [engines: {'+'.join(labels)}]"


def _idea_lines(idx: int, idea: dict[str, Any]) -> list[str]:
    symbol = idea.get("symbol", "?")
    posture = idea.get("posture", "?")
    expression = idea.get("expression", "?")
    badge = _engine_badge(idea.get("source_engines"))
    header = f"  {idx}. {symbol} — {posture} — {expression}{badge}"
    # Earnings annotation on the symbol line when an announcement is
    # within the caution horizon (≤21 days). Informational only — the
    # ranker already vetoed or penalized per its own thresholds, so by
    # the time an idea hits the email this is context, not a warning.
    next_earn = idea.get("next_earnings_date")
    if next_earn is not None:
        from datetime import date as _date
        if hasattr(next_earn, "days"):  # guard against bad types
            pass
        try:
            today = _date.today()
            days_to_earn = (next_earn - today).days if hasattr(next_earn, "year") else None
            if days_to_earn is not None and 0 <= days_to_earn <= 21:
                header += f"  📅 earnings in {days_to_earn}d"
        except Exception:
            pass
    lines = [header]

    # Surface the recommendation UID so the closing CLI hint
    # (`mef show <rec-id>`) is actionable. Previously the email told
    # the user to run `mef show <rec-id>` without ever printing an id.
    rec_uid = idea.get("rec_uid")
    if rec_uid:
        lines.append(f"     Rec ID:     {rec_uid}")

    entry_zone = idea.get("entry_zone")
    if entry_zone:
        if idea.get("needs_pullback"):
            current = idea.get("current_price")
            price_hint = f" (currently ~${current:,.2f})" if current is not None else ""
            lines.append(f"     Entry zone: {entry_zone}  ⏳ wait for pullback{price_hint}")
        else:
            lines.append(f"     Entry zone: {entry_zone}")

    # Price-freshness annotation from mef.price_check. Emitted on its
    # own line so it's visible without cramming the entry-zone line.
    # Only renders when the tier is info or warn (< 1% moves are silent).
    price_note = idea.get("price_check_note")
    if price_note:
        lines.append(f"     Price check: {price_note}")
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
    review_ideas: list[dict[str, Any]] | None = None,
    active_updates: list[dict[str, Any]] | None = None,
    recent_score_summary: str | None = None,
    llm_gate_available: bool = True,
    llm_gate_rejected: int = 0,
    llm_gate_review: int = 0,
    llm_gate_unavailable_kind: str | None = None,
    staleness_warning: str | None = None,
    staleness_aborted: bool = False,
    upcoming_macro_events: list[dict[str, Any]] | None = None,
    per_engine_top: dict[str, list[dict[str, Any]]] | None = None,
    synthesis_order: list[str] | None = None,
) -> RenderedEmail:
    new_ideas = new_ideas or []
    review_ideas = review_ideas or []
    active_updates = active_updates or []
    upcoming_macro_events = upcoming_macro_events or []
    per_engine_top = per_engine_top or {}
    synthesis_order = synthesis_order or []

    # Reorder new_ideas by the LLM's synthesis if available. The
    # synthesis is the LLM's ordered top picks across all engines —
    # treat it as the actionable ordering for the email. Items the LLM
    # approved but didn't include in synthesis fall to the bottom,
    # preserving conviction order among themselves.
    if synthesis_order and new_ideas:
        order_index = {sym: i for i, sym in enumerate(synthesis_order)}
        big = len(synthesis_order) + 1
        new_ideas = sorted(
            new_ideas,
            key=lambda idea: order_index.get(idea.get("symbol", ""), big),
        )

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
        reason_suffix = _unavailable_reason_suffix(llm_gate_unavailable_kind)
        lines.append(
            f"⚠ LLM gate was unavailable for this run{reason_suffix} — "
            "ideas below were not reviewed."
        )
        lines.append("")

    if upcoming_macro_events and not staleness_aborted:
        lines.append("📅 Upcoming high-impact US macro events:")
        for ev in upcoming_macro_events[:6]:
            d = ev.get("date")
            e = ev.get("event", "?")
            dstr = d.isoformat() if hasattr(d, "isoformat") else str(d)
            lines.append(f"   - {dstr}  {e}")
        lines.append("")

    lines.append(f"New ideas ({len(new_ideas)}):")
    if not new_ideas:
        lines.append("  No new trades today.")
    else:
        for idx, idea in enumerate(new_ideas, start=1):
            lines.extend(_idea_lines(idx, idea))

    # Held-for-review ideas: fully rendered so the user can see the LLM's
    # concern + the setup, and decide whether to act manually. Not part
    # of the "approved for auto-ship" list — visually separated.
    if review_ideas:
        lines.append("")
        lines.append(
            f"Held for review ({len(review_ideas)}) — LLM flagged these "
            f"for human attention, not auto-ship:"
        )
        for idx, idea in enumerate(review_ideas, start=1):
            lines.extend(_idea_lines(idx, idea))

    # Quiet footer: only rejected count now. Review items are rendered
    # explicitly above, so summarizing them as a count here would be
    # redundant. ``llm_gate_review`` stays as a fallback count for paths
    # that don't pass the full ``review_ideas`` list (e.g. stale-data abort).
    held_parts: list[str] = []
    if not review_ideas and llm_gate_review:
        held_parts.append(f"{llm_gate_review} held for review")
    if llm_gate_rejected:
        held_parts.append(f"{llm_gate_rejected} rejected")
    if held_parts:
        lines.append("")
        lines.append(f"  Also from this run: {', '.join(held_parts)} (logged for audit).")
    lines.append("")

    # Per-engine top-N sections — the raw output of each ranker engine,
    # rendered concisely (one line per pick) so the user can see what
    # each engine surfaced before the LLM's synthesis narrowed it. Order
    # is fixed: trend → mean-reversion → value.
    if per_engine_top:
        lines.append("Engine views (raw per-engine top picks):")
        _engine_order = ("trend", "mean_reversion", "value")
        for eng in _engine_order:
            items = per_engine_top.get(eng) or []
            if not items:
                continue
            label = _ENGINE_LABELS.get(eng, eng).capitalize()
            lines.append(f"  {label} top {len(items)}:")
            for i, it in enumerate(items, start=1):
                sym = it.get("symbol", "?")
                conv = it.get("conviction_score", 0.0) or 0.0
                posture = it.get("posture", "?")
                lines.append(f"    {i}. {sym:<6} conv={conv:.2f}  {posture}")
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
