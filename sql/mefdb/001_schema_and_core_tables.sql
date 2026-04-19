-- MEF / MEFDB — initial schema and all v1 tables.
--
-- Canonical reference: docs/mef_design_spec.md §11.
--
-- Runs as mef_user (owner of mefdb). No sudo needed.
--
-- Idempotent: safe to re-run. Uses CREATE ... IF NOT EXISTS throughout.
--
-- Manual run:
--     PGPASSWORD=mef_local_2026 psql -h localhost -U mef_user -d mefdb \
--         -v ON_ERROR_STOP=1 -f sql/mefdb/001_schema_and_core_tables.sql
--
-- Or via the CLI:
--     mef init-db

\set ON_ERROR_STOP on

-- ─────────────────────────────────────────────────────────────────────────
-- Schema
-- ─────────────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS mef;

SET search_path TO mef, public;


-- ═════════════════════════════════════════════════════════════════════════
--  UNIVERSE (2 tables) — loaded from notes/ files via `mef universe load`
-- ═════════════════════════════════════════════════════════════════════════

-- universe_stock — the 305 stocks in the curated equity universe
CREATE TABLE IF NOT EXISTS mef.universe_stock (
    symbol                    TEXT PRIMARY KEY,
    company_name              TEXT,
    sector                    TEXT,
    industry                  TEXT,
    avg_close_90d             NUMERIC(14,4),
    avg_volume_90d            BIGINT,
    avg_dollar_volume_90d     BIGINT,
    market_cap_usd            BIGINT,
    options_expirations       INTEGER,
    total_open_interest       BIGINT,
    last_refreshed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- universe_etf — the 15 core ETFs
CREATE TABLE IF NOT EXISTS mef.universe_etf (
    symbol              TEXT PRIMARY KEY,
    role                TEXT NOT NULL,    -- broad_market | size | style_value | style_growth | sector_* | industry_*
    description         TEXT,
    last_refreshed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ═════════════════════════════════════════════════════════════════════════
--  DAILY RUN + CANDIDATE (2 tables)
-- ═════════════════════════════════════════════════════════════════════════

-- daily_run — one row per scheduled run
CREATE TABLE IF NOT EXISTS mef.daily_run (
    run_id                  BIGSERIAL PRIMARY KEY,
    uid                     TEXT NOT NULL UNIQUE,          -- DR-000001
    when_kind               TEXT NOT NULL CHECK (when_kind IN ('premarket','postmarket')),
    intent                  TEXT NOT NULL,                 -- today_after_10am | next_trading_day
    started_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at                TIMESTAMPTZ,
    status                  TEXT NOT NULL DEFAULT 'running', -- running | ok | failed | partial
    symbols_evaluated       INTEGER,
    candidates_passed       INTEGER,
    recommendations_emitted INTEGER,
    email_sent_at           TIMESTAMPTZ,
    notes                   TEXT,
    error_text              TEXT
);

CREATE INDEX IF NOT EXISTS ix_daily_run_started_at_desc
    ON mef.daily_run (started_at DESC);

-- candidate — one row per (run, symbol)
CREATE TABLE IF NOT EXISTS mef.candidate (
    candidate_id            BIGSERIAL PRIMARY KEY,
    uid                     TEXT NOT NULL UNIQUE,          -- C-000001
    run_uid                 TEXT NOT NULL REFERENCES mef.daily_run(uid),
    symbol                  TEXT NOT NULL,
    asset_kind              TEXT NOT NULL CHECK (asset_kind IN ('stock','etf')),
    posture                 TEXT NOT NULL CHECK (posture IN ('bullish','bearish_caution','range_bound','no_edge')),
    conviction_score        NUMERIC(7,4),
    feature_json            JSONB,
    proposed_expression     TEXT,
    proposed_entry_zone     TEXT,
    proposed_stop           NUMERIC(14,4),
    proposed_target         NUMERIC(14,4),
    proposed_time_exit      DATE,
    emitted                 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_candidate_run_symbol
    ON mef.candidate (run_uid, symbol);


-- ═════════════════════════════════════════════════════════════════════════
--  RECOMMENDATION LIFECYCLE (2 tables)
-- ═════════════════════════════════════════════════════════════════════════

-- recommendation — the user-visible output; lifecycle lives here
CREATE TABLE IF NOT EXISTS mef.recommendation (
    recommendation_id       BIGSERIAL PRIMARY KEY,
    uid                     TEXT NOT NULL UNIQUE,          -- R-000001
    run_uid                 TEXT NOT NULL REFERENCES mef.daily_run(uid),
    candidate_uid           TEXT NOT NULL REFERENCES mef.candidate(uid),
    symbol                  TEXT NOT NULL,
    asset_kind              TEXT NOT NULL CHECK (asset_kind IN ('stock','etf')),
    posture                 TEXT NOT NULL,
    expression              TEXT NOT NULL,                 -- buy_shares | buy_etf | covered_call | cash_secured_put | reduce | exit | hedge
    entry_method            TEXT,
    entry_window_end        DATE,
    stop_level              NUMERIC(14,4),
    invalidation_rule       TEXT,
    target_level            NUMERIC(14,4),
    target_rule             TEXT,
    time_exit_date          DATE,
    confidence              NUMERIC(5,4),
    reasoning_summary       TEXT,
    llm_review_color        TEXT,
    llm_review_concern      TEXT,
    state                   TEXT NOT NULL DEFAULT 'proposed'
                              CHECK (state IN (
                                  'proposed','active','dismissed','expired',
                                  'closed_win','closed_loss','closed_timeout'
                              )),
    state_changed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    state_changed_by        TEXT,                          -- run | import | cli
    active_match_position_uid TEXT,                        -- fk to position_snapshot.uid once position is inferred
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_recommendation_state_symbol
    ON mef.recommendation (state, symbol);
CREATE INDEX IF NOT EXISTS ix_recommendation_run
    ON mef.recommendation (run_uid);

-- recommendation_update — per-run delta log for active recommendations
CREATE TABLE IF NOT EXISTS mef.recommendation_update (
    update_id           BIGSERIAL PRIMARY KEY,
    uid                 TEXT NOT NULL UNIQUE,              -- U-000001
    rec_uid             TEXT NOT NULL REFERENCES mef.recommendation(uid),
    run_uid             TEXT NOT NULL REFERENCES mef.daily_run(uid),
    prior_state         TEXT,
    new_state           TEXT,
    prior_stop          NUMERIC(14,4),
    new_stop            NUMERIC(14,4),
    prior_target        NUMERIC(14,4),
    new_target          NUMERIC(14,4),
    prior_time_exit     DATE,
    new_time_exit       DATE,
    thesis_status       TEXT CHECK (thesis_status IN ('intact','weakening','broken') OR thesis_status IS NULL),
    guidance            TEXT,                              -- hold | reduce | exit | hedge | raise_stop | tighten_target | revise_entry | ...
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ═════════════════════════════════════════════════════════════════════════
--  POSITION TRACKING (2 tables)
-- ═════════════════════════════════════════════════════════════════════════

-- import_batch — one row per Fidelity CSV import
CREATE TABLE IF NOT EXISTS mef.import_batch (
    import_id       BIGSERIAL PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,                  -- I-000001
    source_path     TEXT NOT NULL,
    file_hash       TEXT,
    as_of_date      DATE,
    row_count       INTEGER,
    status          TEXT NOT NULL DEFAULT 'ok',            -- ok | failed
    error_text      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- position_snapshot — one row per position per import
CREATE TABLE IF NOT EXISTS mef.position_snapshot (
    position_id             BIGSERIAL PRIMARY KEY,
    uid                     TEXT NOT NULL UNIQUE,          -- P-000001
    import_uid              TEXT NOT NULL REFERENCES mef.import_batch(uid),
    account                 TEXT,
    symbol                  TEXT NOT NULL,
    quantity                NUMERIC(18,4),
    cost_basis_total        NUMERIC(18,4),
    cost_basis_per_share    NUMERIC(18,4),
    last_price              NUMERIC(14,4),
    market_value            NUMERIC(18,4),
    as_of_date              DATE
);

CREATE INDEX IF NOT EXISTS ix_position_snapshot_symbol_date
    ON mef.position_snapshot (symbol, as_of_date);


-- ═════════════════════════════════════════════════════════════════════════
--  BENCHMARK CACHE (1 table — optional, populated only if perf requires)
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.benchmark_snapshot (
    date            DATE NOT NULL,
    symbol          TEXT NOT NULL,
    close           NUMERIC(14,4),
    return_1d       NUMERIC(10,6),
    return_20d      NUMERIC(10,6),
    return_60d      NUMERIC(10,6),
    PRIMARY KEY (date, symbol)
);


-- ═════════════════════════════════════════════════════════════════════════
--  SCORING (1 table)
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.score (
    score_id                        BIGSERIAL PRIMARY KEY,
    uid                             TEXT NOT NULL UNIQUE,  -- S-000001
    rec_uid                         TEXT NOT NULL UNIQUE REFERENCES mef.recommendation(uid),
    outcome                         TEXT NOT NULL CHECK (outcome IN ('win','loss','timeout')),
    entry_price                     NUMERIC(14,4),
    exit_price                      NUMERIC(14,4),
    entry_date                      DATE,
    exit_date                       DATE,
    days_held                       INTEGER,
    estimated_pnl_100_shares_usd    NUMERIC(14,2),
    spy_return_same_window          NUMERIC(10,6),
    sector_etf_symbol               TEXT,
    sector_etf_return_same_window   NUMERIC(10,6),
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ═════════════════════════════════════════════════════════════════════════
--  LLM TRACE (1 table)
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.llm_trace (
    llm_id          BIGSERIAL PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,                  -- L-000001
    run_uid         TEXT REFERENCES mef.daily_run(uid),
    candidate_uid   TEXT REFERENCES mef.candidate(uid),
    provider        TEXT,
    model           TEXT,
    prompt_text     TEXT,
    response_text   TEXT,
    elapsed_ms      INTEGER,
    status          TEXT,                                  -- ok | error | timeout
    error_text      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_llm_trace_run_created
    ON mef.llm_trace (run_uid, created_at);


-- ═════════════════════════════════════════════════════════════════════════
--  COMMAND LOG (1 table)
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.command_log (
    command_id      BIGSERIAL PRIMARY KEY,
    command         TEXT NOT NULL,                         -- full argv joined with spaces
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    exit_status     INTEGER,
    notes           TEXT
);
