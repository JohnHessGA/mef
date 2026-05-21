-- MEF Step 2 — allow neutral `run` value on mef.daily_run.when_kind.
--
-- Step 1 left the original two-value CHECK in place to preserve Grafana
-- compatibility. This migration is purely additive: it widens the allowed
-- set from {'premarket', 'postmarket'} to {'premarket', 'postmarket', 'run'}.
--
-- Existing rows remain valid (the two legacy values are still in the set).
-- The deprecated `premarket-run` / `postmarket-run` CLI aliases continue
-- to stamp their legacy values for dashboard continuity; only plain
-- `mef run` writes the new `run` value.
--
-- Idempotent: DROP IF EXISTS + ADD CONSTRAINT inside a DO block so re-runs
-- are no-ops.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'daily_run_when_kind_check'
           AND conrelid = 'mef.daily_run'::regclass
    ) THEN
        ALTER TABLE mef.daily_run
            DROP CONSTRAINT daily_run_when_kind_check;
    END IF;

    ALTER TABLE mef.daily_run
        ADD CONSTRAINT daily_run_when_kind_check
        CHECK (when_kind IN ('premarket', 'postmarket', 'run'));
END $$;
