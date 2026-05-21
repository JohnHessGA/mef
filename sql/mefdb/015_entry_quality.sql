-- MEF Job 1 — Entry Quality Overlay v1
--
-- Adds four nullable columns to mef.candidate so the deterministic
-- entry-quality verdict (computed in src/mef/entry_quality.py) is
-- persisted alongside the existing Layer-A/B/C audit fields added by
-- migration 011.
--
-- Pattern: matches the per-candidate audit pattern (raw_conviction,
-- hazard_penalty_*, eligibility_pass, …). Dedicated columns rather
-- than feature_json keys so future research can `SELECT … GROUP BY
-- entry_quality_status` without ``->>`` casts and so entry_quality_
-- risk_reward stays a proper NUMERIC.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + CHECK constraint guarded by
-- pg_constraint existence so re-runs are no-ops.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

ALTER TABLE mef.candidate
    ADD COLUMN IF NOT EXISTS entry_quality_status      TEXT NULL,
    ADD COLUMN IF NOT EXISTS entry_quality_flags       TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS entry_quality_summary     TEXT NULL,
    ADD COLUMN IF NOT EXISTS entry_quality_risk_reward NUMERIC(7,2) NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'candidate_entry_quality_status_chk') THEN
        ALTER TABLE mef.candidate
            ADD CONSTRAINT candidate_entry_quality_status_chk
            CHECK (entry_quality_status IS NULL
                   OR entry_quality_status IN ('pass', 'watch'));
    END IF;
END $$;

-- Partial index on the demoted rows. Cheap (small population), useful
-- for any "how many entry-quality demotions today" query without
-- scanning the full candidate table.
CREATE INDEX IF NOT EXISTS ix_candidate_entry_quality_watch
    ON mef.candidate (run_uid)
 WHERE entry_quality_status = 'watch';
