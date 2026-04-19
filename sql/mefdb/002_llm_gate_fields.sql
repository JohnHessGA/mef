-- MEF / MEFDB — migration 002: LLM gate audit columns on mef.candidate.
--
-- Adds two nullable columns so every candidate — whether it ships as a
-- recommendation or not — carries the LLM gate decision and one-sentence
-- rationale. Rejected ideas never become recommendations, so this is the
-- only place their audit trail lives.
--
-- Allowed values for llm_gate_decision:
--   NULL           — gate was not run for this candidate (e.g. didn't make the top-N cap)
--   'approve'      — LLM approved; a mef.recommendation was created
--   'reject'       — LLM rejected; candidate stays on mef.candidate only
--   'unavailable'  — LLM call failed; candidate shipped with "not reviewed" note
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

ALTER TABLE mef.candidate
    ADD COLUMN IF NOT EXISTS llm_gate_decision TEXT,
    ADD COLUMN IF NOT EXISTS llm_gate_reason   TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'candidate_llm_gate_decision_chk'
           AND conrelid = 'mef.candidate'::regclass
    ) THEN
        ALTER TABLE mef.candidate
          ADD CONSTRAINT candidate_llm_gate_decision_chk
          CHECK (llm_gate_decision IS NULL
                 OR llm_gate_decision IN ('approve', 'reject', 'unavailable'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_candidate_llm_gate_decision
    ON mef.candidate (llm_gate_decision)
    WHERE llm_gate_decision IS NOT NULL;
