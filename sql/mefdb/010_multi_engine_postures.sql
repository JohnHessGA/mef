-- MEF / MEFDB — migration 010: widen candidate posture CHECK for multi-engine.
--
-- Each new engine has its own posture vocabulary:
--   - mean_reversion → 'oversold_bouncing'
--   - value          → 'value_quality'
-- The original CHECK constraint allowed only the trend engine's
-- postures (bullish, bearish_caution, range_bound, no_edge) and rejects
-- rows from the new engines. Widen to include the new values.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'candidate_posture_check'
           AND conrelid = 'mef.candidate'::regclass
    ) THEN
        ALTER TABLE mef.candidate DROP CONSTRAINT candidate_posture_check;
    END IF;
END$$;

ALTER TABLE mef.candidate
    ADD CONSTRAINT candidate_posture_check
    CHECK (posture IN (
        'bullish',
        'bearish_caution',
        'range_bound',
        'no_edge',
        'oversold_bouncing',
        'value_quality'
    ));
