-- MEF / Overwatch — migration 003: paper-trade counters on ow.mef_run.
--
-- Mirrors the shadow-score counter pair from migration 002. Lets a
-- Grafana panel show paper-scored vs deferred per run, alongside the
-- existing real-score and shadow-score counters.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO ow, public;

ALTER TABLE ow.mef_run
    ADD COLUMN IF NOT EXISTS paper_scored   INTEGER,
    ADD COLUMN IF NOT EXISTS paper_deferred INTEGER;
