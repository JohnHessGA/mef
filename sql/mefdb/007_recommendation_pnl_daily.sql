-- MEF / MEFDB — migration 007: daily mark-to-market P&L tracking.
--
-- One row per (rec_uid, as_of_date) for every active recommendation.
-- Written by the daily pipeline so we accumulate the full P&L curve over
-- the holding period. Answers "where in the holding window did the gains
-- come from?" — straight-line drift vs late pop vs early spike-then-fade.
--
-- Also written on the day a rec closes, with is_close_day=TRUE, so the
-- series has a clean endpoint even though the rec is no longer active.
--
-- Idempotent: ON CONFLICT (rec_uid, as_of_date) DO UPDATE on every write,
-- so re-running the daily sweep on the same day overwrites with the
-- latest computation rather than erroring.
--
-- Why NOT pack this into mef.position_snapshot: position_snapshot is a
-- raw mirror of a Fidelity CSV — one row per position per import,
-- independent of whether MEF tracks that rec. recommendation_pnl_daily
-- is a rec-specific, MEF-computed time series. Keep them separate.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

CREATE TABLE IF NOT EXISTS mef.recommendation_pnl_daily (
    rec_uid                     TEXT NOT NULL REFERENCES mef.recommendation(uid),
    as_of_date                  DATE NOT NULL,
    quantity                    NUMERIC(18,4),
    cost_basis_per_share        NUMERIC(18,4),
    last_price                  NUMERIC(14,4),
    market_value                NUMERIC(18,4),
    unrealized_pnl_usd          NUMERIC(14,2),
    unrealized_pnl_pct          NUMERIC(10,6),
    days_held_so_far            INTEGER,
    is_close_day                BOOLEAN NOT NULL DEFAULT FALSE,
    price_source                TEXT,                    -- 'position_snapshot' | 'mart' | 'none'
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rec_uid, as_of_date)
);

CREATE INDEX IF NOT EXISTS ix_recommendation_pnl_daily_rec_uid
    ON mef.recommendation_pnl_daily (rec_uid, as_of_date DESC);

CREATE INDEX IF NOT EXISTS ix_recommendation_pnl_daily_close_day
    ON mef.recommendation_pnl_daily (rec_uid)
    WHERE is_close_day = TRUE;
