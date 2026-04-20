-- MEF telemetry tables in the overwatch database (schema `ow`).
--
-- Two tables, mirroring the MDC / UDC / RSE pattern:
--   ow.mef_run    — one row per scheduled mef run (counts + status + duration)
--   ow.mef_event  — discrete events (info / warning / error) bound to a run
--
-- Owned by mef_user (granted CREATE on schema ow via sql/mef_ow_grants.sql).
-- ow_user can SELECT (default privilege grant).
--
-- Idempotent — uses CREATE ... IF NOT EXISTS.

\set ON_ERROR_STOP on

SET search_path TO ow, public;

-- ─────────────────────────────────────────────────────────────────────────
-- ow.mef_run — one row per scheduled run
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ow.mef_run (
    run_uid                  TEXT PRIMARY KEY,        -- mirrors mef.daily_run.uid
    when_kind                TEXT NOT NULL,            -- premarket | postmarket
    intent                   TEXT,                     -- today_after_10am | next_trading_day
    started_at               TIMESTAMPTZ NOT NULL,
    ended_at                 TIMESTAMPTZ,
    status                   TEXT NOT NULL,            -- running | ok | failed | partial
    duration_seconds         NUMERIC(10,3),
    symbols_evaluated        INTEGER,
    candidates_passed        INTEGER,
    recommendations_emitted  INTEGER,
    gate_approved            INTEGER,
    gate_rejected            INTEGER,
    gate_unavailable         INTEGER,
    lifecycle_expired        INTEGER,
    lifecycle_closed         INTEGER,
    scored                   INTEGER,
    email_sent               BOOLEAN NOT NULL DEFAULT FALSE,
    error_text               TEXT
);

CREATE INDEX IF NOT EXISTS ix_mef_run_started_at_desc
    ON ow.mef_run (started_at DESC);

CREATE INDEX IF NOT EXISTS ix_mef_run_status
    ON ow.mef_run (status, started_at DESC);


-- ─────────────────────────────────────────────────────────────────────────
-- ow.mef_event — discrete events from a run
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ow.mef_event (
    event_id    BIGSERIAL PRIMARY KEY,
    run_uid     TEXT,                                  -- nullable (some events aren't run-bound)
    severity    TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code        TEXT NOT NULL,                         -- e.g. run_started, gate_unavailable
    message     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_mef_event_run_created
    ON ow.mef_event (run_uid, created_at);

CREATE INDEX IF NOT EXISTS ix_mef_event_severity_created
    ON ow.mef_event (severity, created_at DESC);
