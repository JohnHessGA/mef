-- MEF / MEFDB — migration 011: layered gating + hazard overlay.
--
-- Splits the monolithic conviction_score into raw + final, persists
-- the hazard-overlay decomposition, and makes hazard-suppressed and
-- ineligibility first-class candidate outcomes.
--
-- Layer model (see docs/mef_layered_gating.md):
--   A. Eligibility — universe + data freshness + per-engine earnings blackout
--   B. Hazard overlay — macro events, earnings-proximity (trend), later: regime/vol
--   C. Per-engine thesis — ranker signals, value FCF veto
--
-- New columns on mef.candidate:
--   raw_conviction                 — engine's belief before overlays
--   hazard_penalty_total           — sum of applied hazard components (capped 0.10)
--   hazard_penalty_macro           — macro component only
--   hazard_penalty_earnings_prox   — earnings-proximity component (trend)
--   hazard_event_type              — top-impact macro event driving the macro penalty
--   hazard_flags                   — short-tag list (e.g. {"macro:FOMC","earn_prox:6-10d"})
--   selected_pre_llm               — final_conviction >= threshold
--   suppressed_by_hazard           — posture valid AND final < threshold
--   eligibility_pass               — Layer A verdict
--   eligibility_fail_reasons       — short strings for Layer A failures
--
-- conviction_score on mef.candidate remains the value the selectors use —
-- i.e. final_conviction. No data churn for existing rows: older candidates
-- had no hazard overlay, so their raw_conviction is backfilled from
-- conviction_score and hazard_penalty_total = 0.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

-- ─── Raw + final split + hazard decomposition ───
ALTER TABLE mef.candidate
    ADD COLUMN IF NOT EXISTS raw_conviction               NUMERIC(7,4),
    ADD COLUMN IF NOT EXISTS hazard_penalty_total         NUMERIC(7,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hazard_penalty_macro         NUMERIC(7,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hazard_penalty_earnings_prox NUMERIC(7,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hazard_event_type            TEXT,
    ADD COLUMN IF NOT EXISTS hazard_flags                 TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS selected_pre_llm             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS suppressed_by_hazard         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS eligibility_pass             BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS eligibility_fail_reasons     TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

-- Backfill raw_conviction from the legacy single-score column — before
-- this migration, conviction_score WAS raw (no overlay existed).
UPDATE mef.candidate
   SET raw_conviction = conviction_score
 WHERE raw_conviction IS NULL;

-- Helpful indexes for audit queries:
--   "which candidates did the hazard overlay silence?"  → suppressed
--   "how did raw scores compare to final on a given run?" → run + selected
CREATE INDEX IF NOT EXISTS ix_candidate_suppressed
    ON mef.candidate (suppressed_by_hazard)
 WHERE suppressed_by_hazard = TRUE;

CREATE INDEX IF NOT EXISTS ix_candidate_run_selected
    ON mef.candidate (run_uid, selected_pre_llm);
