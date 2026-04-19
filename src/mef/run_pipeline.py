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
from datetime import datetime, timezone
from typing import Any

from mef.config import load_app_config
from mef.db.connection import connect_mefdb
from mef.email_render import render_daily_email
from mef.evidence import EvidenceBundle, pull_latest_evidence
from mef.lifecycle import sweep as lifecycle_sweep
from mef.llm.gate import GateResult, apply_gate
from mef.ranker import RankedCandidate, rank, select_for_emission
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
    """Write gate decisions + reasons onto mef.candidate for every top-N symbol."""
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
                   SET llm_gate_decision = %s,
                       llm_gate_reason   = %s
                 WHERE uid = %s
                """,
                (dec.decision, dec.reason, uid),
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
    """Insert one recommendation row per approved or unavailable survivor.

    Rejected ideas are skipped — their gate decision is on mef.candidate only.
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
                "reasoning_summary": reasoning,
                **pnl,
            })
    conn.commit()
    return emitted_rows


# ─────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────

def execute(when_kind: str) -> dict[str, Any]:
    if when_kind not in _INTENT:
        raise ValueError(f"when_kind must be premarket|postmarket, got {when_kind!r}")

    app_cfg = load_app_config()
    ranker_cfg = app_cfg.get("ranker") or {}
    conviction_threshold = float(ranker_cfg.get("conviction_threshold", 0.5))
    max_new_ideas = int(ranker_cfg.get("max_new_ideas_per_run", 5))

    conn = connect_mefdb()
    try:
        run_uid, started_at = _open_daily_run(conn, when_kind)
        try:
            # Lifecycle sweep before generating new ideas — catches any
            # proposed rec whose entry window has closed, and any active
            # rec whose symbol disappeared from the latest import.
            life = lifecycle_sweep()

            counts = _universe_counts(conn)
            universe_total = counts["stocks"] + counts["etfs"]

            evidence: EvidenceBundle = pull_latest_evidence()
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
            )
            _stamp_gate_decisions(conn, candidate_uid_map=candidate_uid_map, gate=gate)

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
                    f"approved={len(gate.approved)} rejected={len(gate.rejected)} "
                    f"unavailable={len(gate.unavailable)} "
                    f"expired={len(life.expired)} closed={len(life.closed)}"
                ),
            )

            email = render_daily_email(
                when_kind=when_kind,
                intent=_INTENT[when_kind],
                run_uid=run_uid,
                started_at=started_at,
                stocks_in_universe=counts["stocks"],
                etfs_in_universe=counts["etfs"],
                new_ideas=emitted_rows,
                active_updates=[],
                llm_gate_available=gate.available,
                llm_gate_rejected=len(gate.rejected),
            )
            return {
                "run_uid":                 run_uid,
                "when_kind":               when_kind,
                "intent":                  _INTENT[when_kind],
                "as_of_date":              evidence.as_of_date.isoformat(),
                "universe_total":          universe_total,
                "symbols_evaluated":       symbols_evaluated,
                "candidates_passed":       candidates_passed,
                "top_n":                   len(top_n),
                "gate_available":          gate.available,
                "gate_approved":           len(gate.approved),
                "gate_rejected":           len(gate.rejected),
                "gate_unavailable":        len(gate.unavailable),
                "lifecycle_expired":       len(life.expired),
                "lifecycle_closed":        len(life.closed),
                "stocks_in_universe":      counts["stocks"],
                "etfs_in_universe":        counts["etfs"],
                "recommendations_emitted": len(emitted_rows),
                "survivors":               emitted_rows,
                "email_subject":           email.subject,
                "email_body":              email.body,
            }
        except Exception as exc:
            _mark_failed(conn, run_uid=run_uid, error_text=repr(exc))
            raise
    finally:
        conn.close()
