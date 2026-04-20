-- MEF / MEFDB — migration 008: actual realized P&L columns on mef.score.
--
-- The existing estimated_pnl_100_shares_usd is a synthetic stand-in
-- (entry vs exit close, scaled to 100 shares). These new columns hold
-- the **actual** trade data when the user fills it in via
-- 'mef link-trade <rec-uid>'. Until PHDB wires up Fidelity transaction
-- history for automatic linking, this is the manual bridge.
--
-- realized_pnl_per_day is the headline metric for the user's stated
-- goal: maximize profit in the shortest amount of time. Populated when
-- both realized_buy_date and realized_sell_date are known.
--
-- All columns are nullable — a score row may exist (closed rec, scored)
-- without actual trade data yet. Consumers prefer actuals when present,
-- fall back to estimated_pnl_100_shares_usd otherwise.
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

ALTER TABLE mef.score
    ADD COLUMN IF NOT EXISTS realized_qty          NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS realized_buy_price    NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS realized_buy_date     DATE,
    ADD COLUMN IF NOT EXISTS realized_sell_price   NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS realized_sell_date    DATE,
    ADD COLUMN IF NOT EXISTS realized_pnl_usd      NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS realized_pnl_per_day  NUMERIC(12,4);

CREATE INDEX IF NOT EXISTS ix_score_realized_pnl_per_day
    ON mef.score (realized_pnl_per_day DESC NULLS LAST)
    WHERE realized_pnl_per_day IS NOT NULL;
