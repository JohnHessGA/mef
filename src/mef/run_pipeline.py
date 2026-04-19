"""Daily-run pipeline.

v0 behaviour (now with real evidence):

1. Open a ``mef.daily_run`` row (status='running').
2. Pull latest evidence for the universe via ``mef.evidence``.
3. Rank every symbol via ``mef.ranker`` — writes one ``mef.candidate`` row
   per symbol with a posture and a conviction score.
4. Select survivors (conviction >= threshold, non-no_edge posture, capped
   at ``max_new_ideas_per_run``) and write ``mef.recommendation`` rows
   with state ``proposed``.
5. Close ``daily_run`` (status='ok', counts, ended_at).
6. Render the email body via ``mef.email_render``.
7. Return a summary dict (CLI prints; delivery via notify.py lands later).

Not yet wired:
- LLM review over survivors
- Active-position lifecycle transitions
- notify.py email delivery
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mef.config import load_app_config
from mef.db.connection import connect_mefdb
from mef.email_render import render_daily_email
from mef.evidence import EvidenceBundle, pull_latest_evidence
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
    """Strip non-JSON-serializable values (dates, etc.) to ISO strings."""
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


def _mark_emitted(conn, candidate_uids: list[str]) -> None:
    if not candidate_uids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE mef.candidate SET emitted = TRUE WHERE uid = ANY(%s)",
            (candidate_uids,),
        )
    conn.commit()


def _reasoning_text(cand: RankedCandidate) -> str:
    if not cand.reasoning_notes:
        return f"{cand.posture} · conviction {cand.conviction_score:.2f}"
    return "; ".join(cand.reasoning_notes)


def _insert_recommendations(
    conn,
    run_uid: str,
    survivors: list[RankedCandidate],
    candidate_uid_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Insert one recommendation row per survivor and return email-ready dicts."""
    emitted_rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for cand in survivors:
            uid = next_uid(conn, "recommendation")
            cur.execute(
                """
                INSERT INTO mef.recommendation (
                    uid, run_uid, candidate_uid, symbol, asset_kind, posture,
                    expression, entry_method, entry_window_end,
                    stop_level, invalidation_rule,
                    target_level, target_rule,
                    time_exit_date, confidence, reasoning_summary,
                    state, state_changed_by
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
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
                    _reasoning_text(cand),
                ),
            )
            emitted_rows.append({
                "rec_uid":           uid,
                "symbol":            cand.symbol,
                "posture":           cand.posture,
                "expression":        cand.proposed_expression,
                "reasoning_summary": _reasoning_text(cand),
            })
    conn.commit()
    return emitted_rows


# ─────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────

def execute(when_kind: str) -> dict[str, Any]:
    """Execute one scheduled run. Returns a summary dict suitable for CLI output."""
    if when_kind not in _INTENT:
        raise ValueError(f"when_kind must be premarket|postmarket, got {when_kind!r}")

    app_cfg = load_app_config()
    ranker_cfg = app_cfg.get("ranker") or {}
    conviction_threshold = float(ranker_cfg.get("conviction_threshold", 0.6))
    max_new_ideas = int(ranker_cfg.get("max_new_ideas_per_run", 5))

    conn = connect_mefdb()
    try:
        run_uid, started_at = _open_daily_run(conn, when_kind)
        try:
            counts = _universe_counts(conn)
            universe_total = counts["stocks"] + counts["etfs"]

            evidence: EvidenceBundle = pull_latest_evidence()
            all_candidates = rank(evidence)
            candidate_uid_map = _insert_candidates(conn, run_uid, all_candidates)

            survivors = select_for_emission(
                all_candidates,
                conviction_threshold=conviction_threshold,
                max_new_ideas=max_new_ideas,
            )
            _mark_emitted(conn, [candidate_uid_map[c.symbol] for c in survivors])
            emitted_rows = _insert_recommendations(conn, run_uid, survivors, candidate_uid_map)

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
                notes=f"as_of={evidence.as_of_date.isoformat()} threshold={conviction_threshold} cap={max_new_ideas}",
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
            )
            return {
                "run_uid":                 run_uid,
                "when_kind":               when_kind,
                "intent":                  _INTENT[when_kind],
                "as_of_date":              evidence.as_of_date.isoformat(),
                "universe_total":          universe_total,
                "symbols_evaluated":       symbols_evaluated,
                "candidates_passed":       candidates_passed,
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
