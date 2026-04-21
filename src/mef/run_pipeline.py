"""Daily-run pipeline.

End-to-end:

1. Open a ``mef.daily_run`` row (status='running').
2. Pull latest evidence for the universe via ``mef.evidence``.
3. Rank every symbol via ``mef.ranker`` — one ``mef.candidate`` row each,
   with posture + conviction_score.
4. Select top-N by conviction subject to the threshold + cap.
5. LLM gate: approve or reject each top-N idea.
6. Write ``mef.recommendation`` rows for approved (and — when LLM is
   unavailable — unavailable) candidates; stamp gate decision + reason on
   ``mef.candidate`` for every top-N row whether it shipped or not.
7. Close ``daily_run`` (status='ok', counts, ended_at).
8. Render the email body via ``mef.email_render``.
9. Return a summary dict for CLI printing.

Not yet wired:
- notify.py delivery
- active-position lifecycle transitions
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from mef.config import load_app_config
from mef.db.connection import connect_mefdb
from mef.email_render import render_daily_email
from mef.email_send import send_daily_email
from mef.evidence import EvidenceBundle, FreshnessReport, check_freshness, pull_latest_evidence
from mef.lifecycle import sweep as lifecycle_sweep
from mef.llm.gate import GateResult, apply_gate
from mef.ranker import RankedCandidate, rank, select_for_emission
from mef.paper_scoring import paper_score_emitted
from mef.pnl_tracking import snapshot_daily_pnl
from mef.scoring import score_all_pending
from mef.shadow_scoring import shadow_score_rejected
from mef.telemetry import (
    complete_run as ow_complete_run,
    event as ow_event,
    fail_run as ow_fail_run,
    start_run as ow_start_run,
)
from mef.uid import next_uid

_INTENT = {
    "premarket":  "today_after_10am",
    "postmarket": "next_trading_day",
}


# ─────────────────────────────────────────────────────────────────────────
# daily_run lifecycle helpers
# ─────────────────────────────────────────────────────────────────────────

def _universe_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM mef.universe_stock")
        stocks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM mef.universe_etf")
        etfs = cur.fetchone()[0]
    return {"stocks": stocks, "etfs": etfs}


def _open_daily_run(conn, when_kind: str) -> tuple[str, datetime]:
    uid = next_uid(conn, "daily_run")
    started_at = datetime.now(timezone.utc)
    intent = _INTENT[when_kind]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.daily_run (uid, when_kind, intent, started_at, status)
            VALUES (%s, %s, %s, %s, 'running')
            """,
            (uid, when_kind, intent, started_at),
        )
    conn.commit()
    return uid, started_at


def _close_daily_run(
    conn,
    *,
    run_uid: str,
    symbols_evaluated: int,
    candidates_passed: int,
    recommendations_emitted: int,
    notes: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.daily_run
               SET ended_at                = now(),
                   status                  = 'ok',
                   symbols_evaluated       = %s,
                   candidates_passed       = %s,
                   recommendations_emitted = %s,
                   notes                   = COALESCE(%s, notes)
             WHERE uid = %s
            """,
            (symbols_evaluated, candidates_passed, recommendations_emitted, notes, run_uid),
        )
    conn.commit()


def _mark_failed(conn, *, run_uid: str, error_text: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.daily_run
               SET ended_at   = now(),
                   status     = 'failed',
                   error_text = %s
             WHERE uid = %s
            """,
            (error_text, run_uid),
        )
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────
# Candidate + recommendation writers
# ─────────────────────────────────────────────────────────────────────────

def _json_safe(features: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in features.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _insert_candidates(conn, run_uid: str, candidates: list[RankedCandidate]) -> dict[str, str]:
    """Insert one candidate row per scored symbol. Returns {symbol: candidate_uid}."""
    uid_map: dict[str, str] = {}
    with conn.cursor() as cur:
        for cand in candidates:
            uid = next_uid(conn, "candidate")
            cur.execute(
                """
                INSERT INTO mef.candidate (
                    uid, run_uid, symbol, asset_kind, posture, conviction_score,
                    feature_json, proposed_expression, proposed_entry_zone,
                    proposed_stop, proposed_target, proposed_time_exit, emitted
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uid, run_uid, cand.symbol, cand.asset_kind,
                    cand.posture, cand.conviction_score,
                    json.dumps(_json_safe(cand.features)),
                    cand.proposed_expression,
                    cand.proposed_entry_zone,
                    cand.proposed_stop,
                    cand.proposed_target,
                    cand.proposed_time_exit,
                    False,
                ),
            )
            uid_map[cand.symbol] = uid
    conn.commit()
    return uid_map


def _stamp_gate_decisions(
    conn,
    *,
    candidate_uid_map: dict[str, str],
    gate: GateResult,
) -> None:
    """Write gate decisions + reasons + issue_type onto mef.candidate for every top-N symbol."""
    if not gate.decisions:
        return
    with conn.cursor() as cur:
        for sym, dec in gate.decisions.items():
            uid = candidate_uid_map.get(sym)
            if not uid:
                continue
            cur.execute(
                """
                UPDATE mef.candidate
                   SET llm_gate_decision   = %s,
                       llm_gate_reason     = %s,
                       llm_gate_issue_type = %s
                 WHERE uid = %s
                """,
                (dec.decision, dec.reason, dec.issue_type, uid),
            )
    conn.commit()


def _mark_emitted(conn, candidate_uids: list[str]) -> None:
    if not candidate_uids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE mef.candidate SET emitted = TRUE WHERE uid = ANY(%s)",
            (candidate_uids,),
        )
    conn.commit()


def _compose_reasoning(cand: RankedCandidate, gate_reason: str | None) -> str:
    """Prefer the LLM's one-sentence reason; fall back to ranker notes."""
    if gate_reason:
        return gate_reason
    if cand.reasoning_notes:
        return "; ".join(cand.reasoning_notes)
    return f"{cand.posture} · conviction {cand.conviction_score:.2f}"


def _estimated_pnl(cand: RankedCandidate) -> dict[str, float | None]:
    """Potential gain / loss / R:R per 100 shares, from entry-mid / stop / target."""
    close = cand.features.get("close")
    stop = cand.proposed_stop
    target = cand.proposed_target
    if close is None or stop is None or target is None:
        return {"potential_gain_100sh": None, "potential_loss_100sh": None, "risk_reward": None}
    # Entry mid: middle of the draft entry zone (±1%) — close is already the anchor.
    entry_mid = close
    gain = round((target - entry_mid) * 100, 2)
    loss = round((entry_mid - stop) * 100, 2)
    rr = round(gain / loss, 2) if loss and loss > 0 else None
    return {"potential_gain_100sh": gain, "potential_loss_100sh": loss, "risk_reward": rr}


def _insert_recommendations(
    conn,
    run_uid: str,
    survivors: list[RankedCandidate],
    candidate_uid_map: dict[str, str],
    gate: GateResult,
) -> list[dict[str, Any]]:
    """Insert one recommendation row per approve / review / unavailable survivor.

    Rejected ideas are NOT recorded as recommendations — their gate decision
    lives on mef.candidate only. Approved + review + unavailable ALL become
    recommendations so they can flow through the lifecycle (auto-activate
    on matching holding, get paper-scored, etc.). Email filtering happens
    downstream via the ``should_email`` flag.
    """
    emitted_rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for cand in survivors:
            decision = gate.decisions.get(cand.symbol)
            if decision is None or decision.decision == "reject":
                continue

            uid = next_uid(conn, "recommendation")
            gate_reason = decision.reason if decision.decision != "unavailable" else None
            reasoning = _compose_reasoning(cand, gate_reason)
            cur.execute(
                """
                INSERT INTO mef.recommendation (
                    uid, run_uid, candidate_uid, symbol, asset_kind, posture,
                    expression, entry_method, entry_window_end,
                    stop_level, invalidation_rule,
                    target_level, target_rule,
                    time_exit_date, confidence, reasoning_summary,
                    llm_review_color,
                    state, state_changed_by
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s,
                    'proposed', 'run'
                )
                """,
                (
                    uid, run_uid, candidate_uid_map[cand.symbol],
                    cand.symbol, cand.asset_kind, cand.posture,
                    cand.proposed_expression,
                    f"limit order {cand.proposed_entry_zone}" if cand.proposed_entry_zone else None,
                    cand.proposed_time_exit,
                    cand.proposed_stop,
                    "close below stop on daily bar",
                    cand.proposed_target,
                    "profit-take at target or on momentum break",
                    cand.proposed_time_exit,
                    cand.conviction_score,
                    reasoning,
                    gate_reason,
                ),
            )
            pnl = _estimated_pnl(cand)
            # Email rule: only LLM-approved (and unavailable, as a fallback so
            # an LLM outage doesn't silence MEF). Review-tagged recs are saved
            # but not emailed — visible via `mef recommendations --state proposed`.
            should_email = decision.decision in ("approve", "unavailable")
            emitted_rows.append({
                "rec_uid":           uid,
                "symbol":            cand.symbol,
                "asset_kind":        cand.asset_kind,
                "posture":           cand.posture,
                "expression":        cand.proposed_expression,
                "entry_zone":        cand.proposed_entry_zone,
                "stop":              cand.proposed_stop,
                "target":            cand.proposed_target,
                "time_exit":         cand.proposed_time_exit,
                "llm_gate":          decision.decision,
                "issue_type":        decision.issue_type,
                "should_email":      should_email,
                "reasoning_summary": reasoning,
                "needs_pullback":    cand.needs_pullback,
                "current_price":     cand.features.get("close"),
                **pnl,
            })
    conn.commit()
    return emitted_rows


# ─────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────

def _stamp_email_sent(conn, run_uid: str, sent_at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE mef.daily_run SET email_sent_at = %s WHERE uid = %s",
            (sent_at, run_uid),
        )
    conn.commit()


def _abort_for_stale_data(
    conn,
    *,
    run_uid: str,
    when_kind: str,
    started_at: datetime,
    counts: dict[str, int],
    universe_total: int,
    freshness: FreshnessReport,
    dry_run: bool,
    conviction_threshold: float,
    max_new_ideas: int,
) -> dict[str, Any]:
    """Short-circuit the run when mart data is too stale to trust.

    Writes the daily_run row with status='partial', sends a warning-only
    email (no ideas), emits telemetry, and returns a summary dict shaped
    like the normal-path return so the CLI can print it uniformly.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.daily_run
               SET ended_at                = now(),
                   status                  = 'partial',
                   symbols_evaluated       = 0,
                   candidates_passed       = 0,
                   recommendations_emitted = 0,
                   notes                   = %s
             WHERE uid = %s
            """,
            (f"ABORTED for stale data: {freshness.message}", run_uid),
        )
    conn.commit()

    email = render_daily_email(
        when_kind=when_kind,
        intent=_INTENT[when_kind],
        run_uid=run_uid,
        started_at=started_at,
        stocks_in_universe=counts["stocks"],
        etfs_in_universe=counts["etfs"],
        new_ideas=[],
        active_updates=[],
        llm_gate_available=False,
        llm_gate_rejected=0,
        staleness_warning=freshness.message,
        staleness_aborted=True,
    )

    if dry_run:
        send_status = {"sent": False, "skipped_reason": "dry-run"}
        ow_event(severity="info", code="email_dry_run", run_uid=run_uid)
    else:
        send_result = send_daily_email(subject=email.subject, body=email.body)
        if send_result.ok and send_result.sent_at:
            _stamp_email_sent(conn, run_uid, send_result.sent_at)
            ow_event(
                severity="info", code="email_sent",
                message=", ".join(send_result.recipients),
                run_uid=run_uid,
            )
        else:
            ow_event(
                severity="warning", code="email_not_sent",
                message=send_result.error or send_result.skipped_reason or "unknown",
                run_uid=run_uid,
            )
        send_status = {
            "sent":           send_result.ok,
            "recipients":     send_result.recipients,
            "sent_at":        send_result.sent_at.isoformat() if send_result.sent_at else None,
            "error":          send_result.error,
            "skipped_reason": send_result.skipped_reason,
        }

    ow_complete_run(
        run_uid=run_uid, started_at=started_at,
        counts={
            "symbols_evaluated":       0,
            "candidates_passed":       0,
            "recommendations_emitted": 0,
            "gate_approved":           0,
            "gate_rejected":           0,
            "gate_unavailable":        0,
            "lifecycle_expired":       0,
            "lifecycle_closed":        0,
            "scored":                  0,
        },
        email_sent=send_status.get("sent", False),
    )

    return {
        "run_uid":                 run_uid,
        "when_kind":               when_kind,
        "intent":                  _INTENT[when_kind],
        "as_of_date":              (freshness.as_of_date.isoformat() if freshness.as_of_date else None),
        "data_freshness":          {
            "status":   freshness.status,
            "age_days": freshness.age_days,
            "message":  freshness.message,
            "aborted":  True,
        },
        "universe_total":          universe_total,
        "symbols_evaluated":       0,
        "candidates_passed":       0,
        "top_n":                   0,
        "gate_available":          False,
        "gate_approved":           0,
        "gate_rejected":           0,
        "gate_unavailable":        0,
        "lifecycle_expired":       0,
        "lifecycle_closed":        0,
        "scored":                  0,
        "stocks_in_universe":      counts["stocks"],
        "etfs_in_universe":        counts["etfs"],
        "recommendations_emitted": 0,
        "survivors":               [],
        "email_subject":           email.subject,
        "email_body":              email.body,
        "email_send":              send_status,
        "aborted":                 "stale_data",
    }


def execute(when_kind: str, *, dry_run: bool = False) -> dict[str, Any]:
    if when_kind not in _INTENT:
        raise ValueError(f"when_kind must be premarket|postmarket, got {when_kind!r}")

    app_cfg = load_app_config()
    ranker_cfg = app_cfg.get("ranker") or {}
    conviction_threshold = float(ranker_cfg.get("conviction_threshold", 0.5))
    max_new_ideas = int(ranker_cfg.get("max_new_ideas_per_run", 5))

    fresh_cfg = app_cfg.get("data_freshness") or {}
    fresh_warn = int(fresh_cfg.get("warn_after_calendar_days", 4))
    fresh_abort = int(fresh_cfg.get("abort_after_calendar_days", 7))

    conn = connect_mefdb()
    try:
        run_uid, started_at = _open_daily_run(conn, when_kind)
        ow_start_run(
            run_uid=run_uid, when_kind=when_kind,
            intent=_INTENT[when_kind], started_at=started_at,
        )
        ow_event(severity="info", code="run_started", message=f"{when_kind}", run_uid=run_uid)
        try:
            # Lifecycle sweep before generating new ideas — catches any
            # proposed rec whose entry window has closed, and any active
            # rec whose symbol disappeared from the latest import.
            life = lifecycle_sweep()
            if life.expired or life.closed:
                ow_event(
                    severity="info", code="lifecycle_sweep",
                    message=f"expired={len(life.expired)} closed={len(life.closed)}",
                    run_uid=run_uid,
                )

            counts = _universe_counts(conn)
            universe_total = counts["stocks"] + counts["etfs"]

            evidence: EvidenceBundle = pull_latest_evidence()
            freshness: FreshnessReport = check_freshness(
                evidence,
                today=date.today(),
                warn_after_calendar_days=fresh_warn,
                abort_after_calendar_days=fresh_abort,
            )
            if freshness.should_warn:
                ow_event(
                    severity=("error" if freshness.should_abort else "warning"),
                    code=("data_stale_abort" if freshness.should_abort else "data_stale_warn"),
                    message=freshness.message,
                    run_uid=run_uid,
                )
            if freshness.should_abort:
                return _abort_for_stale_data(
                    conn,
                    run_uid=run_uid,
                    when_kind=when_kind,
                    started_at=started_at,
                    counts=counts,
                    universe_total=universe_total,
                    freshness=freshness,
                    dry_run=dry_run,
                    conviction_threshold=conviction_threshold,
                    max_new_ideas=max_new_ideas,
                )

            all_candidates = rank(evidence)
            candidate_uid_map = _insert_candidates(conn, run_uid, all_candidates)

            top_n = select_for_emission(
                all_candidates,
                conviction_threshold=conviction_threshold,
                max_new_ideas=max_new_ideas,
            )

            gate = apply_gate(
                conn,
                run_uid=run_uid,
                survivors=top_n,
                as_of_date=evidence.as_of_date.isoformat(),
                spy_return_20d=evidence.baseline.get("spy_return_20d"),
                spy_return_63d=evidence.baseline.get("spy_return_63d"),
                candidate_uids=candidate_uid_map,
            )
            _stamp_gate_decisions(conn, candidate_uid_map=candidate_uid_map, gate=gate)
            if not gate.available:
                ow_event(
                    severity="warning", code="gate_unavailable",
                    message="LLM gate unavailable — ideas shipped without review",
                    run_uid=run_uid,
                )

            emitted_rows = _insert_recommendations(
                conn, run_uid, top_n, candidate_uid_map, gate,
            )
            emitted_uids = [candidate_uid_map[row["symbol"]] for row in emitted_rows]
            _mark_emitted(conn, emitted_uids)

            candidates_passed = sum(
                1 for c in all_candidates
                if c.posture in ("bullish", "range_bound")
            )
            symbols_evaluated = len(all_candidates)

            # Daily MTM P&L for every active rec + close-day rows for newly closed.
            # Runs after the lifecycle sweep so just-closed recs get their final
            # row stamped with is_close_day=TRUE this run.
            pnl_snap = snapshot_daily_pnl()
            if pnl_snap.active_written or pnl_snap.close_day_written:
                ow_event(
                    severity="info", code="pnl_snapshot",
                    message=(f"active={len(pnl_snap.active_written)} "
                             f"close_day={len(pnl_snap.close_day_written)} "
                             f"skipped={len(pnl_snap.skipped)}"),
                    run_uid=run_uid,
                )

            # Score any newly-closed recs from the lifecycle sweep.
            scoring = score_all_pending()
            # Shadow-score any rejected candidates whose time_exit has elapsed
            # (or that hit stop/target along the way). Lets us audit the LLM
            # gate by comparing approved-vs-rejected outcome distributions.
            shadow = shadow_score_rejected()
            if shadow.new_rows:
                ow_event(
                    severity="info", code="shadow_scored",
                    message=f"shadow_scored={len(shadow.new_rows)} deferred={len(shadow.deferred)}",
                    run_uid=run_uid,
                )
            # Paper-trade every emitted rec under the same forward-walk rules.
            # Speeds validation from "wait for activations" to "wait for time_exit".
            paper = paper_score_emitted()
            if paper.new_rows:
                ow_event(
                    severity="info", code="paper_scored",
                    message=f"paper_scored={len(paper.new_rows)} deferred={len(paper.deferred)}",
                    run_uid=run_uid,
                )

            _close_daily_run(
                conn,
                run_uid=run_uid,
                symbols_evaluated=symbols_evaluated,
                candidates_passed=candidates_passed,
                recommendations_emitted=len(emitted_rows),
                notes=(
                    f"as_of={evidence.as_of_date.isoformat()} "
                    f"threshold={conviction_threshold} cap={max_new_ideas} "
                    f"gate_available={gate.available} "
                    f"approved={len(gate.approved)} review={len(gate.review)} "
                    f"rejected={len(gate.rejected)} "
                    f"unavailable={len(gate.unavailable)} "
                    f"expired={len(life.expired)} closed={len(life.closed)} "
                    f"scored={len(scoring.new_rows)} "
                    f"shadow_scored={len(shadow.new_rows)} "
                    f"shadow_deferred={len(shadow.deferred)} "
                    f"paper_scored={len(paper.new_rows)} "
                    f"paper_deferred={len(paper.deferred)}"
                ),
            )

            # Email shows approved (+ unavailable, so an LLM outage doesn't
            # silence MEF) as "New ideas", and review-tagged recs in a
            # separate "Held for review" section with the LLM reasoning
            # visible so the user can decide whether to act manually.
            email_ideas = [r for r in emitted_rows if r.get("should_email")]
            review_ideas = [r for r in emitted_rows if r.get("llm_gate") == "review"]
            email = render_daily_email(
                when_kind=when_kind,
                intent=_INTENT[when_kind],
                run_uid=run_uid,
                started_at=started_at,
                stocks_in_universe=counts["stocks"],
                etfs_in_universe=counts["etfs"],
                new_ideas=email_ideas,
                review_ideas=review_ideas,
                active_updates=[],
                llm_gate_available=gate.available,
                llm_gate_rejected=len(gate.rejected),
                staleness_warning=(freshness.message if freshness.should_warn else None),
            )

            if dry_run:
                send_status = {"sent": False, "skipped_reason": "dry-run"}
                ow_event(severity="info", code="email_dry_run", run_uid=run_uid)
            else:
                send_result = send_daily_email(subject=email.subject, body=email.body)
                if send_result.ok and send_result.sent_at:
                    _stamp_email_sent(conn, run_uid, send_result.sent_at)
                    ow_event(
                        severity="info", code="email_sent",
                        message=", ".join(send_result.recipients),
                        run_uid=run_uid,
                    )
                else:
                    ow_event(
                        severity="warning", code="email_not_sent",
                        message=send_result.error or send_result.skipped_reason or "unknown",
                        run_uid=run_uid,
                    )
                send_status = {
                    "sent":           send_result.ok,
                    "recipients":     send_result.recipients,
                    "sent_at":        send_result.sent_at.isoformat() if send_result.sent_at else None,
                    "error":          send_result.error,
                    "skipped_reason": send_result.skipped_reason,
                }

            ow_complete_run(
                run_uid=run_uid, started_at=started_at,
                counts={
                    "symbols_evaluated":       symbols_evaluated,
                    "candidates_passed":       candidates_passed,
                    "recommendations_emitted": len(emitted_rows),
                    "gate_approved":           len(gate.approved),
                    "gate_review":             len(gate.review),
                    "gate_rejected":           len(gate.rejected),
                    "gate_unavailable":        len(gate.unavailable),
                    "lifecycle_expired":       len(life.expired),
                    "lifecycle_closed":        len(life.closed),
                    "scored":                  len(scoring.new_rows),
                    "shadow_scored":           len(shadow.new_rows),
                    "shadow_deferred":         len(shadow.deferred),
                    "paper_scored":            len(paper.new_rows),
                    "paper_deferred":          len(paper.deferred),
                },
                email_sent=send_status.get("sent", False),
            )

            return {
                "run_uid":                 run_uid,
                "when_kind":               when_kind,
                "intent":                  _INTENT[when_kind],
                "as_of_date":              evidence.as_of_date.isoformat(),
                "data_freshness":          {
                    "status":   freshness.status,
                    "age_days": freshness.age_days,
                    "message":  freshness.message,
                },
                "universe_total":          universe_total,
                "symbols_evaluated":       symbols_evaluated,
                "candidates_passed":       candidates_passed,
                "top_n":                   len(top_n),
                "gate_available":          gate.available,
                "gate_approved":           len(gate.approved),
                "gate_review":             len(gate.review),
                "gate_rejected":           len(gate.rejected),
                "gate_unavailable":        len(gate.unavailable),
                "lifecycle_expired":       len(life.expired),
                "lifecycle_closed":        len(life.closed),
                "scored":                  len(scoring.new_rows),
                "shadow_scored":           len(shadow.new_rows),
                "shadow_deferred":         len(shadow.deferred),
                "paper_scored":            len(paper.new_rows),
                "paper_deferred":          len(paper.deferred),
                "pnl_active_written":      len(pnl_snap.active_written),
                "pnl_close_day_written":   len(pnl_snap.close_day_written),
                "stocks_in_universe":      counts["stocks"],
                "etfs_in_universe":        counts["etfs"],
                "recommendations_emitted": len(emitted_rows),
                "survivors":               emitted_rows,
                "email_subject":           email.subject,
                "email_body":              email.body,
                "email_send":              send_status,
            }
        except Exception as exc:
            _mark_failed(conn, run_uid=run_uid, error_text=repr(exc))
            ow_fail_run(run_uid=run_uid, started_at=started_at, error_text=repr(exc))
            ow_event(severity="error", code="run_failed", message=repr(exc), run_uid=run_uid)
            raise
    finally:
        conn.close()
