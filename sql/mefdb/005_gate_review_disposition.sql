-- MEF / MEFDB — migration 005: 3-way LLM gate disposition + issue_type.
--
-- Changes:
--   1. Widen mef.candidate.llm_gate_decision CHECK to include 'review'
--      alongside the existing 'approve', 'reject', 'unavailable'.
--   2. Add mef.candidate.llm_gate_issue_type — server-validated enum
--      (mechanical / risk_shape / volatility_mismatch / posture_mismatch /
--       asset_structure / options_structure / missing_context / none),
--      so audit queries can cluster gate decisions by reason class.
--
-- Why a separate column from llm_gate_reason: the reason is a one-sentence
-- free-text explanation; the issue_type is a hard-validated enum that's
-- safe to GROUP BY. The LLM is asked to populate both.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

-- ─── Replace the decision CHECK to allow 'review' ───
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'candidate_llm_gate_decision_chk'
           AND conrelid = 'mef.candidate'::regclass
    ) THEN
        ALTER TABLE mef.candidate
          DROP CONSTRAINT candidate_llm_gate_decision_chk;
    END IF;
END$$;

ALTER TABLE mef.candidate
    ADD CONSTRAINT candidate_llm_gate_decision_chk
    CHECK (llm_gate_decision IS NULL
           OR llm_gate_decision IN ('approve', 'review', 'reject', 'unavailable'));

-- ─── Add issue_type column with its own CHECK ───
ALTER TABLE mef.candidate
    ADD COLUMN IF NOT EXISTS llm_gate_issue_type TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'candidate_llm_gate_issue_type_chk'
           AND conrelid = 'mef.candidate'::regclass
    ) THEN
        ALTER TABLE mef.candidate
          ADD CONSTRAINT candidate_llm_gate_issue_type_chk
          CHECK (llm_gate_issue_type IS NULL
                 OR llm_gate_issue_type IN (
                       'none', 'mechanical', 'risk_shape', 'volatility_mismatch',
                       'posture_mismatch', 'asset_structure', 'options_structure',
                       'missing_context'
                 ));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_candidate_llm_gate_issue_type
    ON mef.candidate (llm_gate_issue_type)
    WHERE llm_gate_issue_type IS NOT NULL;
