-- MEF / MEFDB — migration 004: paper-trade scoring of every emitted rec.
--
-- Purpose: speed up validation. Right now we only learn the realized
-- outcome of a recommendation when the user actually buys the symbol
-- (and IRA Guard's CSV import flips it to active and eventually closed).
-- That activation rate is sparse — at 1-2 trades/week, calibration
-- takes 6-12 months.
--
-- Paper scoring runs the same forward-walk simulation we use for
-- shadow-scoring rejected candidates, but applied to every emitted
-- recommendation (gate decision in 'approve' or 'unavailable'). Entry
-- price, stop, target, and time_exit are all already on the candidate;
-- we just walk close prices forward and classify the outcome.
--
-- Why a separate table from mef.score:
--   - mef.score is keyed on real position activation (entry_price
--     comes from the user's actual cost basis). It's authoritative
--     for "what John actually made or lost."
--   - mef.paper_score is synthetic — the entry is the candidate's
--     close-of-run-day, the same anchor mef.shadow_score uses. It
--     answers "what would have happened if you had bought every
--     emitted rec at the run-day close."
--   - Both can coexist for the same rec_uid; consumers prefer mef.score
--     when present.
--
-- Why a separate table from mef.shadow_score:
--   - shadow_score is for *rejected* candidates (no rec_uid exists).
--     paper_score is for *emitted* recommendations (rec_uid required).
--   - The forward-walk algorithm and outcome columns are identical, so
--     the two tables can be UNION-ed in audit queries — see the future
--     `mef gate-audit` command, which compares approved-paper-trades
--     vs rejected-shadow-trades using the same methodology.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

CREATE TABLE IF NOT EXISTS mef.paper_score (
    paper_score_id                  BIGSERIAL PRIMARY KEY,
    uid                             TEXT NOT NULL UNIQUE,    -- PS-000001
    rec_uid                         TEXT NOT NULL UNIQUE REFERENCES mef.recommendation(uid),
    candidate_uid                   TEXT NOT NULL REFERENCES mef.candidate(uid),
    gate_decision                   TEXT NOT NULL,           -- snapshot: approve | unavailable
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

CREATE INDEX IF NOT EXISTS ix_paper_score_outcome
    ON mef.paper_score (outcome);

CREATE INDEX IF NOT EXISTS ix_paper_score_gate_decision
    ON mef.paper_score (gate_decision);
