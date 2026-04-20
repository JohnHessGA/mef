-- MEF / Overwatch — migration 002: shadow-score counters on ow.mef_run.
--
-- Adds two nullable counters so each run row records how many rejected
-- candidates were forward-simulated this run (shadow_scored) and how
-- many were deferred because their time_exit hasn't elapsed yet
-- (shadow_deferred). Lets Grafana show "did the LLM gate help?" trends
-- without a join into MEFDB.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO ow, public;

ALTER TABLE ow.mef_run
    ADD COLUMN IF NOT EXISTS shadow_scored   INTEGER,
    ADD COLUMN IF NOT EXISTS shadow_deferred INTEGER;
