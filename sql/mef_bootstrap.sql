-- MEF bootstrap — creates mef_user role, mefdb database, and grants SELECT on
-- SHDB schemas (mart, shdb) plus CONNECT on overwatch so `mef status` can
-- reach all three databases.
--
-- Run once as postgres superuser:
--     sudo -u postgres psql -f ~/repos/mef/sql/mef_bootstrap.sql
--
-- This script is idempotent. Safe to re-run.

\set ON_ERROR_STOP on

-- ─────────────────────────────────────────────────────────────────────────
-- 1. mef_user role
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mef_user') THEN
        CREATE ROLE mef_user WITH LOGIN PASSWORD 'mef_local_2026';
        RAISE NOTICE 'Created role mef_user';
    ELSE
        RAISE NOTICE 'Role mef_user already exists — skipping';
    END IF;
END$$;

-- ─────────────────────────────────────────────────────────────────────────
-- 2. mefdb database (owned by mef_user)
-- ─────────────────────────────────────────────────────────────────────────
SELECT 'CREATE DATABASE mefdb OWNER mef_user'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'mefdb')\gexec

-- ─────────────────────────────────────────────────────────────────────────
-- 3. SHDB read grants — connect to shdb and grant SELECT to mef_user
-- ─────────────────────────────────────────────────────────────────────────
\c shdb

GRANT CONNECT ON DATABASE shdb TO mef_user;

GRANT USAGE ON SCHEMA mart         TO mef_user;
GRANT USAGE ON SCHEMA shdb         TO mef_user;

GRANT SELECT ON ALL TABLES IN SCHEMA mart TO mef_user;
GRANT SELECT ON ALL TABLES IN SCHEMA shdb TO mef_user;

-- Future tables created by udc_user automatically become readable by mef_user.
-- Mirrors the rse_user pattern.
ALTER DEFAULT PRIVILEGES FOR ROLE udc_user IN SCHEMA mart
    GRANT SELECT ON TABLES TO mef_user;
ALTER DEFAULT PRIVILEGES FOR ROLE udc_user IN SCHEMA shdb
    GRANT SELECT ON TABLES TO mef_user;

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Overwatch connectivity — CONNECT + USAGE on ow schema
--    ow.mef_* tables and per-table privileges come later, when we create them.
-- ─────────────────────────────────────────────────────────────────────────
\c overwatch

GRANT CONNECT ON DATABASE overwatch TO mef_user;
GRANT USAGE ON SCHEMA ow TO mef_user;

-- ─────────────────────────────────────────────────────────────────────────
-- 5. mefdb: mef_user is the owner, so no extra grants needed here.
--    Schema `mef` will be created by `mef init-db` running as mef_user.
-- ─────────────────────────────────────────────────────────────────────────
\c mefdb

\echo ''
\echo '================================================================'
\echo 'MEF bootstrap complete'
\echo '================================================================'
\echo 'Created (or verified): role mef_user, database mefdb'
\echo 'Granted SELECT to mef_user on: shdb.mart, shdb.shdb'
\echo 'Granted CONNECT + USAGE ow to mef_user on: overwatch'
\echo ''
\echo 'Next steps (run from ~/repos/mef/ as your user, not postgres):'
\echo '  1. python3 -m venv venv && source venv/bin/activate'
\echo '  2. pip install -e .'
\echo '  3. mef status      # smoke test — all connections should be green'
\echo '  4. mef init-db     # creates schema mef and all MEFDB tables'
\echo '================================================================'
