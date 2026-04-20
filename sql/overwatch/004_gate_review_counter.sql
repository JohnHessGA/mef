-- MEF / Overwatch — migration 004: gate_review counter on ow.mef_run.
--
-- Adds gate_review alongside gate_approved / gate_rejected / gate_unavailable
-- so Grafana panels can show the full 4-way disposition breakdown per run.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO ow, public;

ALTER TABLE ow.mef_run
    ADD COLUMN IF NOT EXISTS gate_review INTEGER;
