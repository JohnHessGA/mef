-- MEF / MEFDB — migration 003: shadow scoring of LLM-rejected candidates.
--
-- Purpose: make the LLM gate auditable. For every candidate the gate
-- rejected, we forward-simulate "what would have happened if we had
-- emitted it as a recommendation" using the same stop/target/time_exit
-- the candidate carried, and store the realized outcome here.
--
-- Why a separate table from mef.score:
--   - Different key. mef.score is keyed on rec_uid (real recs).
--     Rejected candidates never become recommendations, so they have
--     no rec_uid — they're keyed on candidate_uid here.
--   - Different audience. mef.score reports on actual decisions and
--     drives win/loss totals. mef.shadow_score is gate-quality
--     telemetry: was the LLM right to reject? It's never shown to the
--     user as a "win" — only summarized in audit comparisons.
--
-- Columns mirror mef.score so the two can be UNION-ed for analysis.
--
-- Outcome semantics match mef.score (close-based comparison vs stop /
-- target). See src/mef/shadow_scoring.py for the forward-walk rules.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

CREATE TABLE IF NOT EXISTS mef.shadow_score (
    shadow_score_id                 BIGSERIAL PRIMARY KEY,
    uid                             TEXT NOT NULL UNIQUE,    -- SS-000001
    candidate_uid                   TEXT NOT NULL UNIQUE REFERENCES mef.candidate(uid),
    gate_decision                   TEXT NOT NULL,           -- snapshot of llm_gate_decision (typically 'reject')
    outcome                         TEXT NOT NULL CHECK (outcome IN ('win','loss','timeout')),
    entry_price                     NUMERIC(14,4),
    exit_price                      NUMERIC(14,4),
    entry_date                      DATE,
    exit_date                       DATE,
    days_held                       INTEGER,
    estimated_pnl_100_shares_usd    NUMERIC(14,2),
    spy_return_same_window          NUMERIC(10,6),
    sector_etf_symbol               TEXT,
    sector_etf_return_same_window   NUMERIC(10,6),
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_shadow_score_outcome
    ON mef.shadow_score (outcome);

CREATE INDEX IF NOT EXISTS ix_shadow_score_gate_decision
    ON mef.shadow_score (gate_decision);
