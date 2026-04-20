-- MEF / MEFDB — migration 006: activation provenance on mef.recommendation.
--
-- The auto-activation rule flips a proposed rec to 'active' when a matching
-- holding shows up in the latest CSV import. That's correct mechanically,
-- but it conflates two very different cases:
--
--   - You bought the stock BECAUSE MEF recommended it (mef_attributed).
--   - You already owned the stock for unrelated reasons (pre_existing) —
--     MEF takes credit it didn't earn, contaminating the win/loss audit.
--   - You bought it well after the entry window, or otherwise out-of-band
--     (independent) — ambiguous; default-leans-not-MEF.
--
-- Storing the provenance lets downstream audits ('mef gate-audit',
-- future P&L roll-ups) report MEF-attributed outcomes separately from
-- ambient ones. Inferred at activation time; user-overridable via
-- 'mef tag <rec> --provenance ...'.
--
-- Detection rule (positions/activator.py applies this):
--   * If symbol's earliest position_snapshot.as_of_date < rec.created_at::date
--     → 'pre_existing'
--   * Else if earliest as_of_date is within [rec.created_at, entry_window_end]
--     → 'mef_attributed'
--   * Else
--     → 'independent'
--
-- Recs that never auto-activate retain provenance=NULL.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

ALTER TABLE mef.recommendation
    ADD COLUMN IF NOT EXISTS provenance     TEXT,
    ADD COLUMN IF NOT EXISTS provenance_set_by TEXT;     -- 'activator' | 'cli' | NULL

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'recommendation_provenance_chk'
           AND conrelid = 'mef.recommendation'::regclass
    ) THEN
        ALTER TABLE mef.recommendation
          ADD CONSTRAINT recommendation_provenance_chk
          CHECK (provenance IS NULL
                 OR provenance IN ('mef_attributed', 'pre_existing', 'independent'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_recommendation_provenance
    ON mef.recommendation (provenance)
    WHERE provenance IS NOT NULL;
