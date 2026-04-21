-- MEF / MEFDB — migration 009: multi-engine ranker scaffolding.
--
-- Changes:
--   1. Add mef.candidate.engine — one of 'trend', 'mean_reversion',
--      'value'. Tags every candidate row with the ranker engine that
--      produced it. Default 'trend' for backfill; all existing rows
--      come from the single pre-existing engine.
--   2. Add mef.recommendation.source_engines TEXT[] — the engines
--      whose candidates contributed to this recommendation. A union
--      recommendation will have multiple entries here when the same
--      symbol was picked by more than one engine in the same run.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

-- ─── engine column on mef.candidate ───
ALTER TABLE mef.candidate
    ADD COLUMN IF NOT EXISTS engine TEXT NOT NULL DEFAULT 'trend';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'candidate_engine_chk'
           AND conrelid = 'mef.candidate'::regclass
    ) THEN
        ALTER TABLE mef.candidate
          ADD CONSTRAINT candidate_engine_chk
          CHECK (engine IN ('trend', 'mean_reversion', 'value'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_candidate_run_engine
    ON mef.candidate (run_uid, engine);

-- ─── source_engines column on mef.recommendation ───
ALTER TABLE mef.recommendation
    ADD COLUMN IF NOT EXISTS source_engines TEXT[];

-- Backfill: every existing recommendation came from the single
-- pre-existing engine ('trend'). Only touch NULL rows so re-running
-- the migration doesn't clobber a correctly-populated array.
UPDATE mef.recommendation
   SET source_engines = ARRAY['trend']
 WHERE source_engines IS NULL;

-- ─── shadow_score + paper_score: engine column for per-engine audit ───
-- Tables may not exist in every environment; guarded by ALTER ... ADD
-- COLUMN IF NOT EXISTS which is a no-op when the parent table is absent
-- under `information_schema` guard.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema='mef' AND table_name='shadow_score') THEN
        ALTER TABLE mef.shadow_score
            ADD COLUMN IF NOT EXISTS engine TEXT;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema='mef' AND table_name='paper_score') THEN
        ALTER TABLE mef.paper_score
            ADD COLUMN IF NOT EXISTS engine TEXT;
    END IF;
END$$;

-- Backfill shadow / paper score engine column from the candidate's
-- engine value. Only touch rows where it's still NULL.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='mef' AND table_name='shadow_score'
                  AND column_name='engine') THEN
        EXECUTE $sql$
            UPDATE mef.shadow_score s
               SET engine = c.engine
              FROM mef.candidate c
             WHERE s.candidate_uid = c.uid
               AND s.engine IS NULL
        $sql$;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='mef' AND table_name='paper_score'
                  AND column_name='engine') THEN
        EXECUTE $sql$
            UPDATE mef.paper_score p
               SET engine = c.engine
              FROM mef.candidate c
             WHERE p.candidate_uid = c.uid
               AND p.engine IS NULL
        $sql$;
    END IF;
END$$;
