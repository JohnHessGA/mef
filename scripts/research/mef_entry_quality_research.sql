-- =========================================================================
-- MEF Job 1 — Entry Quality Research SQL
-- =========================================================================
--
-- Purpose: study which conditions historically separate useful trend-
--          continuation entries from weak "already ran / poor entry"
--          candidates. Research only — NOT for production scoring.
--
-- Scope: trend-engine, bullish posture candidates from mef.candidate
--        whose final conviction cleared the 0.50 threshold (i.e., were
--        eligible to reach the per-engine top-N pool that the LLM gate sees).
--
-- Authoritative companion: docs/research/mef_entry_quality_research_plan.md.
-- Driver:   scripts/research/run_entry_quality_research.py (read-only).
--
-- READ-ONLY: every statement here is a SELECT. The runner connects with
-- the standard mefdb / shdb credentials and never opens a transaction
-- that modifies state.
--
-- Two databases. The mef.* tables live in mefdb; mart.* lives in shdb.
-- The runner pulls each side separately and joins in Python — postgres_fdw
-- is not configured between mefdb and shdb on this host. Each section below
-- is labelled [MEFDB] or [SHDB] for clarity.
--
-- =========================================================================
-- Section 0 — Sample-size sanity (run first to confirm research feasibility)
-- =========================================================================

-- [MEFDB]
-- How many trend-bullish candidates exist by run-week, and what fraction
-- have a 10/20/30-day forward window available at today's date?
SELECT
    date_trunc('week', dr.started_at)::date AS week,
    count(*) FILTER (WHERE c.engine='trend' AND c.posture='bullish'
                       AND c.conviction_score >= 0.50) AS n_trend_bullish,
    count(*) FILTER (WHERE dr.started_at::date <= CURRENT_DATE - 10
                       AND c.engine='trend' AND c.posture='bullish'
                       AND c.conviction_score >= 0.50) AS has_10d_fwd,
    count(*) FILTER (WHERE dr.started_at::date <= CURRENT_DATE - 20
                       AND c.engine='trend' AND c.posture='bullish'
                       AND c.conviction_score >= 0.50) AS has_20d_fwd,
    count(*) FILTER (WHERE dr.started_at::date <= CURRENT_DATE - 30
                       AND c.engine='trend' AND c.posture='bullish'
                       AND c.conviction_score >= 0.50) AS has_30d_fwd
  FROM mef.candidate c
  JOIN mef.daily_run dr ON dr.uid = c.run_uid
 WHERE dr.status = 'ok'
 GROUP BY week
 ORDER BY week;


-- =========================================================================
-- Section 1 — Base cohort: trend-engine bullish candidates with their
--             entry-quality features extracted from feature_json
-- =========================================================================
--
-- The runner materializes this slice from mefdb and joins it against
-- per-symbol forward returns from shdb.

-- [MEFDB]
SELECT
    c.uid                                                AS candidate_uid,
    c.run_uid,
    -- as_of date for this run; SHDB bar_date the ranker scored against.
    -- Stored only in daily_run.notes for now (e.g. "as_of=2026-05-19 ...").
    -- Treat NULL as "couldn't parse — exclude from forward-return joins".
    substring(dr.notes from 'as_of=(\d{4}-\d{2}-\d{2})')::date  AS bar_date,
    c.symbol,
    c.engine,
    c.posture,
    c.conviction_score,
    c.raw_conviction,
    c.hazard_penalty_total,
    c.eligibility_pass,
    c.selected_pre_llm,
    c.emitted,
    c.llm_gate_decision,
    -- Per-symbol entry plan (populated when the trend engine produced one).
    c.proposed_entry_zone,
    c.proposed_stop,
    c.proposed_target,
    -- Selected feature_json values used by the ranker for this row.
    (c.feature_json->>'close')::numeric             AS close,
    (c.feature_json->>'sma_50')::numeric            AS sma_50,
    (c.feature_json->>'sma_200')::numeric           AS sma_200,
    (c.feature_json->>'sma_50_slope')::numeric      AS sma_50_slope,
    (c.feature_json->>'return_5d')::numeric         AS return_5d,
    (c.feature_json->>'return_20d')::numeric        AS return_20d,
    (c.feature_json->>'return_63d')::numeric        AS return_63d,
    (c.feature_json->>'return_126d')::numeric       AS return_126d,
    (c.feature_json->>'return_252d')::numeric       AS return_252d,
    (c.feature_json->>'rs_vs_spy_63d')::numeric     AS rs_vs_spy_63d,
    (c.feature_json->>'rsi_14')::numeric            AS rsi_14,
    (c.feature_json->>'macd_histogram')::numeric    AS macd_histogram,
    (c.feature_json->>'atr_14')::numeric            AS atr_14,
    (c.feature_json->>'drawdown_current')::numeric  AS drawdown_current,
    (c.feature_json->>'free_cash_flow')::numeric    AS free_cash_flow,
    (c.feature_json->>'pe_trailing')::numeric       AS pe_trailing,
    c.feature_json->>'sector'                       AS sector
  FROM mef.candidate c
  JOIN mef.daily_run dr ON dr.uid = c.run_uid
 WHERE dr.status = 'ok'
   AND c.engine = 'trend'
   AND c.posture = 'bullish'
   AND c.conviction_score >= 0.50
;


-- =========================================================================
-- Section 2 — Forward returns per (symbol, bar_date)
-- =========================================================================
--
-- Compute the 10/20/30 trading-day forward returns for every symbol the
-- base cohort references. Window function offset, then the runner joins
-- on (symbol, bar_date).

-- [SHDB]
SELECT
    symbol,
    bar_date,
    close                                                          AS entry_close,
    LEAD(close, 10) OVER w / NULLIF(close, 0) - 1                  AS fwd_10d_return,
    LEAD(close, 20) OVER w / NULLIF(close, 0) - 1                  AS fwd_20d_return,
    LEAD(close, 30) OVER w / NULLIF(close, 0) - 1                  AS fwd_30d_return,
    -- Worst close inside the next 20 / 30 trading days, for max-drawdown studies.
    MIN(close) OVER w_fwd_20                                       AS min_close_next_20d,
    MIN(close) OVER w_fwd_30                                       AS min_close_next_30d
  FROM mart.stock_equity_daily
 WHERE bar_date >= (CURRENT_DATE - INTERVAL '300 day')             -- comfortable cushion
   AND symbol = ANY(%(symbols)s)                                   -- bound to cohort symbols
WINDOW
    w        AS (PARTITION BY symbol ORDER BY bar_date),
    w_fwd_20 AS (PARTITION BY symbol ORDER BY bar_date
                  ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING),
    w_fwd_30 AS (PARTITION BY symbol ORDER BY bar_date
                  ROWS BETWEEN 1 FOLLOWING AND 30 FOLLOWING)
;


-- =========================================================================
-- Section 3 — Same-window SPY return (for benchmark-relative cohort metrics)
-- =========================================================================
-- The runner fetches this once for SPY only and joins on bar_date.

-- [SHDB]
SELECT
    bar_date,
    close                                                          AS spy_close,
    LEAD(close, 10) OVER w / NULLIF(close, 0) - 1                  AS spy_fwd_10d,
    LEAD(close, 20) OVER w / NULLIF(close, 0) - 1                  AS spy_fwd_20d,
    LEAD(close, 30) OVER w / NULLIF(close, 0) - 1                  AS spy_fwd_30d
  FROM mart.stock_etf_daily
 WHERE symbol = 'SPY'
   AND bar_date >= (CURRENT_DATE - INTERVAL '300 day')
WINDOW w AS (ORDER BY bar_date)
;


-- =========================================================================
-- Cohort definitions — performed in the runner against the joined dataset.
-- The text below documents each cohort so an operator can re-derive them
-- without running the Python script.
-- =========================================================================

-- =========================================================================
-- Section 4 — Cohort A: extension from SMA200
-- =========================================================================
-- ext = (close - sma_200) / sma_200   (positive when close above SMA200)
--
-- Buckets:
--   ext <  0.05                       — 0–5%
--   0.05 <= ext < 0.10                — 5–10%
--   0.10 <= ext < 0.15                — 10–15%
--   0.15 <= ext < 0.20                — 15–20%
--   0.20 <= ext < 0.25                — 20–25%
--   ext >= 0.25                       — >25%
--
-- Hypothesis: extreme extension (>15%) predicts weaker forward returns
-- and higher near-term drawdowns. NDAQ (today: +1.7% above SMA200) and
-- OXY (+27%) bracket this range.


-- =========================================================================
-- Section 5 — Cohort B: recent 63d run-up
-- =========================================================================
-- buckets on return_63d:
--   < 0.05                            — <5%
--   0.05 <= r < 0.10                  — 5–10%
--   0.10 <= r < 0.20                  — 10–20%
--   0.20 <= r < 0.30                  — 20–30%
--   r >= 0.30                         — >30%
--
-- Hypothesis: forward returns degrade as run-up grows. OXY at +31.8% is
-- the canonical case.


-- =========================================================================
-- Section 6 — Cohort C: run-up with little pullback (combined feature)
-- =========================================================================
-- Sub-cohorts within `return_63d > 0.20`:
--   drawdown_current >  -0.05         — very little pullback after the run
--   -0.10 <= drawdown_current <= -0.05 — modest pullback
--   drawdown_current <  -0.10         — meaningful pullback
--
-- Hypothesis: "ran a lot AND no pullback yet" is the worst regime.


-- =========================================================================
-- Section 7 — Cohort D: SMA200 cushion (thin-margin filter)
-- =========================================================================
-- cushion = (close - sma_200) / sma_200   (only candidates with close > sma_200)
--
--   0.00 <= c < 0.03                  — 0–3%
--   0.03 <= c < 0.05                  — 3–5%
--   0.05 <= c < 0.10                  — 5–10%
--   c >= 0.10                         — >10%
--
-- Hypothesis: <3% cushion fails more often (the trend line is just below).


-- =========================================================================
-- Section 8 — Cohort E: choppy-recovery patterns
-- =========================================================================
-- E1: return_63d > 0.12 AND return_126d < 0.05
-- E2: return_63d > 0.12 AND return_252d < 0.15
--
-- Hypothesis: a strong 63d alongside a tepid 126d / 252d describes a
-- round-trip that just made it back — the classic NDAQ shape.


-- =========================================================================
-- Section 9 — Cohort F: risk/reward geometry
-- =========================================================================
-- For candidates with all three of proposed_entry_zone, proposed_stop,
-- proposed_target populated. Entry-mid extracted from the "$X-$Y" string.
--
-- r_r = (target - entry_mid) / (entry_mid - stop)
--
--   r_r < 1.2                         — bad geometry
--   1.2 <= r_r < 1.5                  — marginal
--   1.5 <= r_r < 2.0                  — acceptable
--   r_r >= 2.0                        — good
--
-- Hypothesis: low R:R cohorts under-perform.


-- =========================================================================
-- Section 10 — Cohort G: engine confirmation
-- =========================================================================
-- For each trend-bullish candidate's (symbol, run_uid), how many OTHER
-- engines surfaced a non-no_edge posture for the same symbol in the same run?
--
--   trend only                        — no corroborating engine
--   trend + value                     — value also non-no_edge
--   trend + mean_reversion            — mean-rev also non-no_edge
--   multi-engine                      — any 2+ confirmation
--
-- Hypothesis: multi-engine candidates outperform single-engine.
-- Implementation note: this requires a self-join inside mefdb (cheap;
-- the runner handles it via a separate query).


-- =========================================================================
-- Section 11 — Cohort H: negative FCF for trend candidates
-- =========================================================================
--   free_cash_flow < 0                — negative FCF
--   free_cash_flow >= 0               — positive FCF
--   free_cash_flow IS NULL            — missing FCF
--
-- Hypothesis: negative-FCF trend candidates are riskier even when chart
-- looks clean. The value engine already vetoes them; the trend engine
-- does not. OXY today: FCF = -$1.528B.


-- =========================================================================
-- Output schema (per cohort)
-- =========================================================================
-- The runner emits this per-row table for every cohort:
--   cohort_name             text
--   bucket                  text
--   n                       int
--   median_fwd_10d_return   numeric
--   median_fwd_20d_return   numeric
--   median_fwd_30d_return   numeric
--   win_rate_20d            numeric  -- pct of rows with fwd_20d_return > 0
--   win_rate_30d            numeric  -- pct of rows with fwd_30d_return > 0
--   median_max_drawdown_30d numeric  -- median of (min_close_next_30d/entry_close - 1)
--   median_return_vs_spy_30d numeric -- median of (fwd_30d_return - spy_fwd_30d)
--
-- =========================================================================
