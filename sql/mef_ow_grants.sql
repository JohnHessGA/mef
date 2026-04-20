-- One-off grant: let mef_user create its own ow.mef_* telemetry tables.
--
-- Run as postgres superuser (after copying to /tmp — postgres can't read
-- under /home/johnh/repos/):
--
--     cp ~/repos/mef/sql/mef_ow_grants.sql /tmp/
--     sudo -u postgres psql -f /tmp/mef_ow_grants.sql
--
-- Idempotent.

\set ON_ERROR_STOP on

\c overwatch

GRANT CREATE ON SCHEMA ow TO mef_user;

-- Future tables created by mef_user are readable + writable by mef_user
-- (already true since they'd be owner) and additionally readable by
-- ow_user so OW dashboards can SELECT them.
ALTER DEFAULT PRIVILEGES FOR ROLE mef_user IN SCHEMA ow
    GRANT SELECT ON TABLES TO ow_user;

\echo ''
\echo '================================================================'
\echo 'mef_user can now CREATE in schema ow.'
\echo 'Future ow.mef_* tables will be readable by ow_user.'
\echo '================================================================'
