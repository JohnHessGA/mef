-- MEF Job 2 — Core Pullback Watchlist: tier reference, watchlist, snapshot.
--
-- Canonical design: docs/mef_core_pullback_watchlist.md.
--
-- Operational symbol lists for Job 2 live in MEFDB (not YAML, not markdown).
-- This migration creates:
--
--   mef.core_pullback_tier        — five tier rows + drawdown thresholds
--   mef.core_pullback_watchlist   — 10 ETFs + 50 stocks, tier-assigned
--   mef.core_pullback_snapshot    — empty, ready for the pullback engine
--
-- Idempotent: re-running upserts seed rows without disturbing operator edits.
-- The seed `enabled = TRUE` is set on insert only (ON CONFLICT does NOT
-- overwrite it), so operators can disable a row in the DB without it
-- bouncing back on every migration re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;


-- ═════════════════════════════════════════════════════════════════════════
-- TIERS — drawdown thresholds + display metadata per tier
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.core_pullback_tier (
    tier_code               TEXT PRIMARY KEY,
    display_name            TEXT NOT NULL,
    asset_group             TEXT NOT NULL,           -- 'etf' | 'stock'
    visibility_drawdown     NUMERIC(6,4) NOT NULL,   -- e.g. 0.0300 = 3%
    buy_zone_drawdown       NUMERIC(6,4) NOT NULL,
    deep_drawdown           NUMERIC(6,4) NOT NULL,
    min_risk_reward         NUMERIC(6,2) NULL,
    requires_stabilization  BOOLEAN NOT NULL DEFAULT TRUE,
    display_order           INTEGER NOT NULL,
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'core_pullback_tier_asset_group_chk') THEN
        ALTER TABLE mef.core_pullback_tier
            ADD CONSTRAINT core_pullback_tier_asset_group_chk
            CHECK (asset_group IN ('etf', 'stock'));
    END IF;
END $$;

-- Seed thresholds match docs/mef_core_pullback_watchlist.md §Pullback Thresholds.
-- Operator-tunable: ON CONFLICT updates the *threshold* columns and display
-- metadata, but leaves `enabled` and `min_risk_reward` alone so manual edits
-- survive re-runs.
INSERT INTO mef.core_pullback_tier (
    tier_code, display_name, asset_group,
    visibility_drawdown, buy_zone_drawdown, deep_drawdown,
    requires_stabilization, display_order
) VALUES
    ('core_market_etf',            'Tier 1 — Core market ETF',           'etf',   0.0300, 0.0500, 0.0800, TRUE, 10),
    ('core_growth_etf',            'Tier 1 — Core growth ETF',           'etf',   0.0400, 0.0700, 0.1200, TRUE, 20),
    ('elite_compounder',           'Tier 2 — Elite compounder',          'stock', 0.0500, 0.0800, 0.1500, TRUE, 30),
    ('quality_growth',             'Tier 3 — Quality growth',            'stock', 0.0700, 0.1000, 0.1800, TRUE, 40),
    ('volatile_special_situation', 'Tier 4 — Volatile / special situation','stock', 0.1000, 0.1500, 0.2500, TRUE, 50)
ON CONFLICT (tier_code) DO UPDATE SET
    display_name           = EXCLUDED.display_name,
    asset_group            = EXCLUDED.asset_group,
    visibility_drawdown    = EXCLUDED.visibility_drawdown,
    buy_zone_drawdown      = EXCLUDED.buy_zone_drawdown,
    deep_drawdown          = EXCLUDED.deep_drawdown,
    requires_stabilization = EXCLUDED.requires_stabilization,
    display_order          = EXCLUDED.display_order,
    updated_at             = now();


-- ═════════════════════════════════════════════════════════════════════════
-- WATCHLIST — symbol → tier assignment
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.core_pullback_watchlist (
    symbol         TEXT PRIMARY KEY,
    asset_kind     TEXT NOT NULL,
    tier_code      TEXT NOT NULL REFERENCES mef.core_pullback_tier(tier_code),
    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    display_order  INTEGER NOT NULL,
    rationale      TEXT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'core_pullback_watchlist_asset_kind_chk') THEN
        ALTER TABLE mef.core_pullback_watchlist
            ADD CONSTRAINT core_pullback_watchlist_asset_kind_chk
            CHECK (asset_kind IN ('stock', 'etf'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_core_pullback_watchlist_tier
    ON mef.core_pullback_watchlist (tier_code);
CREATE INDEX IF NOT EXISTS ix_core_pullback_watchlist_enabled
    ON mef.core_pullback_watchlist (enabled) WHERE enabled;

-- Seed: 10 ETFs + 50 stocks per docs/mef_core_pullback_watchlist.md §Universe.
-- ON CONFLICT updates tier_code + display_order + updated_at so a tier
-- reassignment in the migration propagates, but leaves `enabled` and
-- `rationale` alone (operator-editable).
INSERT INTO mef.core_pullback_watchlist (symbol, asset_kind, tier_code, display_order) VALUES
    -- ETFs (tier 1) — display_order 100-block reserves stock space below
    ('SPY',   'etf', 'core_market_etf', 110),
    ('QQQ',   'etf', 'core_growth_etf', 120),
    ('VTI',   'etf', 'core_market_etf', 130),
    ('ONEQ',  'etf', 'core_growth_etf', 140),
    ('IWM',   'etf', 'core_market_etf', 150),
    ('SCHG',  'etf', 'core_growth_etf', 160),
    ('VUG',   'etf', 'core_growth_etf', 170),
    ('XLK',   'etf', 'core_growth_etf', 180),
    ('SMH',   'etf', 'core_growth_etf', 190),
    ('SCHD',  'etf', 'core_market_etf', 200),

    -- Tier 2 — elite compounders (12)
    ('NVDA',  'stock', 'elite_compounder', 305),
    ('MSFT',  'stock', 'elite_compounder', 310),
    ('GOOGL', 'stock', 'elite_compounder', 315),
    ('AMZN',  'stock', 'elite_compounder', 320),
    ('META',  'stock', 'elite_compounder', 325),
    ('AAPL',  'stock', 'elite_compounder', 330),
    ('AVGO',  'stock', 'elite_compounder', 335),
    ('LLY',   'stock', 'elite_compounder', 340),
    ('COST',  'stock', 'elite_compounder', 345),
    ('NFLX',  'stock', 'elite_compounder', 350),
    ('ORCL',  'stock', 'elite_compounder', 355),
    ('AMD',   'stock', 'elite_compounder', 360),

    -- Tier 3 — quality growth (15)
    ('JPM',   'stock', 'quality_growth', 405),
    ('BRK.B', 'stock', 'quality_growth', 410),
    ('UNH',   'stock', 'quality_growth', 415),
    ('ISRG',  'stock', 'quality_growth', 420),
    ('ADBE',  'stock', 'quality_growth', 425),
    ('INTU',  'stock', 'quality_growth', 430),
    ('ASML',  'stock', 'quality_growth', 435),
    ('TSM',   'stock', 'quality_growth', 440),
    ('CRM',   'stock', 'quality_growth', 445),
    ('NOW',   'stock', 'quality_growth', 450),
    ('PANW',  'stock', 'quality_growth', 455),
    ('CRWD',  'stock', 'quality_growth', 460),
    ('UBER',  'stock', 'quality_growth', 465),
    ('SHOP',  'stock', 'quality_growth', 470),
    ('LIN',   'stock', 'quality_growth', 475),

    -- Tier 4 — volatile / special situation (23)
    ('TSLA',  'stock', 'volatile_special_situation', 505),
    ('INTC',  'stock', 'volatile_special_situation', 510),
    ('PLTR',  'stock', 'volatile_special_situation', 515),
    ('ARM',   'stock', 'volatile_special_situation', 520),
    ('MU',    'stock', 'volatile_special_situation', 525),
    ('SNOW',  'stock', 'volatile_special_situation', 530),
    ('DDOG',  'stock', 'volatile_special_situation', 535),
    ('NET',   'stock', 'volatile_special_situation', 540),
    ('MDB',   'stock', 'volatile_special_situation', 545),
    ('RBLX',  'stock', 'volatile_special_situation', 550),
    ('COIN',  'stock', 'volatile_special_situation', 555),
    ('HOOD',  'stock', 'volatile_special_situation', 560),
    ('SOFI',  'stock', 'volatile_special_situation', 565),
    ('SMCI',  'stock', 'volatile_special_situation', 570),
    ('DELL',  'stock', 'volatile_special_situation', 575),
    ('APP',   'stock', 'volatile_special_situation', 580),
    ('ANET',  'stock', 'volatile_special_situation', 585),
    ('VRT',   'stock', 'volatile_special_situation', 590),
    ('CAVA',  'stock', 'volatile_special_situation', 595),
    ('CELH',  'stock', 'volatile_special_situation', 600),
    ('TTD',   'stock', 'volatile_special_situation', 605),
    ('ENPH',  'stock', 'volatile_special_situation', 610),
    ('NVO',   'stock', 'volatile_special_situation', 615)
ON CONFLICT (symbol) DO UPDATE SET
    asset_kind    = EXCLUDED.asset_kind,
    tier_code     = EXCLUDED.tier_code,
    display_order = EXCLUDED.display_order,
    updated_at    = now();


-- ═════════════════════════════════════════════════════════════════════════
-- SNAPSHOT — per-run, per-symbol pullback state. Empty until the engine
-- lands. UID prefix for this table is `PS-` (pullback snapshot).
-- ═════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS mef.core_pullback_snapshot (
    snapshot_uid       TEXT PRIMARY KEY,
    run_uid            TEXT NOT NULL REFERENCES mef.daily_run(uid) ON DELETE CASCADE,
    symbol             TEXT NOT NULL REFERENCES mef.core_pullback_watchlist(symbol),
    as_of_date         DATE NULL,
    close              NUMERIC(14,4) NULL,
    status             TEXT NOT NULL,
    drawdown_63d       NUMERIC(7,4) NULL,
    drawdown_252d      NUMERIC(7,4) NULL,
    starter_buy_level  NUMERIC(14,4) NULL,
    better_buy_level   NUMERIC(14,4) NULL,
    deep_buy_level     NUMERIC(14,4) NULL,
    trend_health       TEXT NULL,
    stabilization      TEXT NULL,
    risk_reward        NUMERIC(7,2) NULL,
    reasons            JSONB NULL,
    cautions           JSONB NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'core_pullback_snapshot_status_chk') THEN
        ALTER TABLE mef.core_pullback_snapshot
            ADD CONSTRAINT core_pullback_snapshot_status_chk
            CHECK (status IN (
                'NO_PULLBACK',
                'PULLBACK_FORMING',
                'BUY_ZONE_ACTIVE',
                'DEEP_PULLBACK_OPPORTUNITY',
                'FALLING_KNIFE_WAIT',
                'THESIS_BROKEN_REVIEW'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_core_pullback_snapshot_run
    ON mef.core_pullback_snapshot (run_uid);
CREATE INDEX IF NOT EXISTS ix_core_pullback_snapshot_symbol_date
    ON mef.core_pullback_snapshot (symbol, as_of_date DESC);
