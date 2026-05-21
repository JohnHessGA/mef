# MEF Job 1 — Entry-Quality Research Plan

Version: 2026-05-20 (initial)
Status: Research package — **does not change recommendation logic**

This document explains the research package created to study which
conditions historically separate useful trend-continuation entries from
weak "already ran / poor entry" candidates. Triggered by the NDAQ /
OXY diagnosis (`docs/research/` adjacent notes; see commit history).

The package is read-only. Nothing here modifies MEFDB or SHDB.

---

## Why we built this

The current Job 1 trend engine produced two questionable Actionable
ideas (NDAQ, OXY) on the 2026-05-20 run. The post-mortem identified
candidate weaknesses (extension from SMA200, big 63d run-up with little
pullback, single-engine selection, modest risk/reward) but no production
change has been chosen yet. **Before** tuning thresholds, adding an
entry-quality overlay, or tightening the LLM gate, we want quantitative
evidence from the existing MEFDB/SHDB record about which entry-quality
proxies actually predict forward returns.

This package is the research tool, not the fix.

---

## Files in this package

| Path | Purpose |
|---|---|
| `scripts/research/mef_entry_quality_research.sql` | Annotated SQL — section-by-section definitions of the base cohort, forward-return joins, and all eight cohort buckets. Useful as documentation and for running pieces directly against `psql -d mefdb` / `psql -d shdb`. |
| `scripts/research/run_entry_quality_research.py` | Read-only Python runner. Orchestrates the cross-database join (mefdb has no FDW to shdb on this host), aggregates each cohort, and prints the cohort tables as Markdown. |
| `docs/research/mef_entry_quality_research_plan.md` | This file. |

---

## What the script measures

For every **trend-engine, bullish, conviction ≥ 0.50** candidate in
`mef.candidate` (i.e., everything that reached the per-engine top-N
selection pool that the LLM gate then sees), the runner joins:

- the entry-quality features the ranker actually used (extracted from
  `feature_json`),
- forward 10 / 20 / 30 trading-day returns from
  `mart.stock_equity_daily` (computed via `LEAD()` window functions),
- the same-window SPY return from `mart.stock_etf_daily` as a benchmark.

It then buckets the cohort eight ways and reports per-bucket:

- sample count
- median forward 10d / 20d / 30d return
- 20d / 30d win rate (`fwd > 0`)
- median max-drawdown over the next 20d / 30d
- median return vs SPY over 30d

The eight cohorts directly map to the eight research questions in the
spec:

| Cohort | Hypothesis |
|---|---|
| A. Extension from SMA200 | Extreme extension (>15%) predicts weaker forward returns. |
| B. 63d run-up | Forward returns degrade as run-up grows. |
| C. Run-up with little pullback | "Ran a lot AND no pullback yet" is the worst regime. |
| D. SMA200 cushion | <3% cushion above SMA200 fails more often. |
| E. Choppy recovery | A strong 63d alongside a tepid 126d / 252d describes a round-trip. |
| F. Risk/reward geometry | Low R:R cohorts under-perform. |
| G. Engine confirmation | Multi-engine candidates outperform trend-only. |
| H. Negative FCF | Negative-FCF trend candidates are riskier than the chart alone implies. |

---

## How to run

```bash
source ~/repos/mef/.venv/bin/activate

# Print the tables to stdout
python scripts/research/run_entry_quality_research.py

# Capture to a dated Markdown file
python scripts/research/run_entry_quality_research.py \
  > docs/research/entry_quality_$(date +%F).md

# Suppress sparse buckets (default is 20; lower for finer slices)
python scripts/research/run_entry_quality_research.py --min-bucket-size 10
```

Connections come from `config/postgres.secrets.yaml` via the standard
`mef.config.load_postgres_config()`. The script sets each connection
`readonly=True`; no schema modification is possible even by accident.

To inspect a single section of the SQL by hand (against psql):

```bash
# mefdb sections
psql -h localhost -U mef_user -d mefdb -f scripts/research/mef_entry_quality_research.sql
# shdb sections — note that section 2 is parameterised; copy the symbols
# array in by hand or use the Python runner.
```

---

## What to paste back for review

The script's stdout is a single Markdown document. Paste it whole.
Include:

- the `Step 1` and `Step 2` headers (cohort counts and forward-window
  coverage — gives reviewers a feel for sample-size validity),
- all eight cohort tables (suppress buckets below `n=20` by default —
  raise that floor when reviewing a noisy table).

If a specific finding looks anomalous, paste the cohort definition from
the SQL companion file alongside the table so reviewers can confirm the
bucket boundaries.

---

## Known limitations (call out in any analysis)

1. **Short history.** MEF began emitting candidates on 2026-04-19;
   today is 2026-05-20. That's 31 calendar days of runs (~13 distinct
   bar_dates after dedup), so:
   - **0 candidates** currently have a complete 30 trading-day forward
     window. The `med fwd 30d`, `win 30d`, and `med vs SPY 30d` columns
     render as `—` until ~mid-June 2026.
   - ~1,366 candidates have 20-day forward returns; ~2,434 have 10-day.
   - Re-run this script at the end of every month and the 30d columns
     populate retroactively.

2. **Window-effect risk.** With only 13 distinct bar_dates, every
   "cohort" overlaps in time. A market dip in late April hits every
   bucket whose candidates were generated then. The 0% 20d win rate for
   the `r:r <1.2` cohort is the loudest example — most of those rows
   came from a single run whose 20d-forward window happens to land on a
   broad selloff. Treat these tables as descriptive (what happened in
   *this* market) rather than predictive. Repeat across a second
   independent month before drawing rules.

3. **Engine-confirmation cohort is conservative.** The
   `_ENGINE_CONFIRMATION_SQL` only counts non-`no_edge` postures from
   `mean_reversion` / `value` with `conviction_score >= 0.40`. The 0.40
   floor is a guess — lower it (to e.g. 0.30) to widen what counts as
   "confirmation," or tighten it to require the other engine cleared
   its own per-engine top-N. The current floor matches the engine's
   own `posture = no_edge` cut.

4. **No survivorship correction.** Candidates whose entry bar fell on
   a delisting / illiquid date are simply absent from the forward-
   return join (~138 candidates have no SHDB join hit). Not material at
   this sample size; might matter for tier 4 / volatile_special_situation
   names if the panel grows.

5. **feature_json gaps.** ~38% of trend+bullish candidates are
   missing `free_cash_flow` and `return_126d`. Cohort H "FCF: missing"
   is genuinely "we didn't capture it," not "the company has no FCF."
   The choppy-recovery cohort (E) is nearly empty for the same reason —
   `return_126d` is needed for the cleanest filter.

6. **No options / structural features.** Implied vol, term structure,
   skew, and open-interest cohort splits are not in this package. SHDB
   has the data (`mart.stock_equity_daily.atm_iv_30d`, `iv_rank`,
   `iv_percentile`), but the trend engine's `feature_json` doesn't
   persist them today. Add them in a follow-up package once we know
   which scalar features matter.

7. **One-window-only stop-out modeling.** The "max-dd" columns are the
   trough close over the next 20/30 trading days, not intraday lows.
   Stops would have triggered more often on intraday wicks; the
   research understates downside.

---

## What the first run already tells us (sanity check, 2026-05-20)

Headline findings from a single run of the script today — **do not
generalize beyond this market window**:

- **Cohort A (extension from SMA200)** — the `>25%` bucket
  (n=772) has the *highest* med 20d return (+7.80%, win 71%). This is
  the opposite of the hypothesis. The bucket is almost certainly
  dominated by a single sector running hard (energy/AI infra) in this
  market window. Worth slicing by `sector` before drawing any rule.
- **Cohort B (63d run-up)** — clean monotone gradient: stronger
  recent return → stronger forward 20d. The `>30%` bucket: n=450, med
  20d +15.25%, win 84%. The `<5%` bucket: n=793, med 20d -5.52%, win
  29%. Again likely a single-window effect, but a real one in *this*
  window.
- **Cohort C (runup + no pullback)** — the worst-hypothesized bucket
  ("runup>20% & dd > -5%", n=572) actually performed *best* (med 20d
  +12.85%, win 71%). Either the hypothesis is wrong, or our window is
  in a momentum regime that masks the longer-run revert.
- **Cohort F (risk/reward)** — the `<1.2` bucket (n=326) had a
  **0% win rate at 20d**. Striking even allowing for window effects;
  worth carrying into any rule conversation.
- **Cohort G (engine confirmation)** — `trend only` (n=2175, win 54%)
  *outperformed* `trend + value` (n=878, win 36%). Counter-intuitive.
  Most likely cause: `value` engine confirms cheap-but-stalled names
  whose trend is just a recovery; needs investigation.
- **Cohort H (negative FCF)** — negative FCF (n=505) had win rate 25%,
  vs positive FCF (n=1048) at 36% and missing (n=1500) at 55%. Modest
  signal but real — the value engine's hard FCF veto looks justified
  by the data even at this short horizon.

These observations are anchors for a future discussion, not rules. Each
needs at least one more month of out-of-sample bar_dates before MEF's
production scoring should react to them.

---

## Direct answers to the questions in the spec

1. **Is this research practical with current MEFDB/SHDB tables?**
   Yes, but the window is short. We have 3,053 trend-bullish candidates
   over 13 distinct bar_dates. Cohort-level medians are meaningful;
   forward 30d returns aren't available yet for any candidate.

2. **Are forward returns already available, or do we need to self-join
   price tables?**
   We self-join. SHDB's mart does not carry materialized
   `forward_10d`/`forward_20d`/`forward_30d` columns (only
   `forward_eps_growth_pct`, a fundamental). The runner computes
   forward returns on the fly via `LEAD()` over `mart.stock_equity_daily`
   bounded to the cohort's symbols. `mef.paper_score` and
   `mef.shadow_score` *do* carry realized forward outcomes, but only
   for emitted recs (176 + 840 rows) and on engine-defined hold windows
   (stop/target/timeout), not fixed 10/20/30d windows — so they don't
   answer the bucket questions here, though they're useful as a sanity
   cross-check on the trend-only emitted cohort.

3. **Does MEF currently persist enough feature data to analyze old
   candidates reliably?**
   For the most-important features yes — `close`, `sma_200`,
   `drawdown_current`, `return_63d`, `rsi_14`, `macd_histogram`,
   `proposed_*` levels are present on essentially every trend+bullish
   row. Gaps:
   - `return_126d` and `free_cash_flow` are missing on ~38% of rows.
   - `sma_200_slope` is not in `feature_json` at all.
   - `atm_iv_*` / options-volatility features are not captured.
   These are worth adding to the feature_json persistence in a future
   step so retrospective cohort work doesn't have to skip them.

4. **Are candidate samples large enough to draw useful conclusions?**
   For coarse buckets (A, B, D, F, G, H): yes, each major bucket
   has ≥200 candidates. For combined-feature buckets (C, E): borderline
   (some sub-buckets are 35-74 rows). For the strongest scientific
   conclusions, wait one more month, then re-run; that will roughly
   double the panel and add a second independent 30d-forward window.

5. **Which proposed criteria look easiest to evaluate now?**
   - Cohort A (extension from SMA200) — easy; clean buckets.
   - Cohort B (63d run-up) — easy; one-feature cut.
   - Cohort F (risk/reward) — easy *for candidates with a populated
     plan*; only `selected_pre_llm = True` rows have entry/stop/target.
   - Cohort H (negative FCF) — easy; binary feature.

6. **Which criteria require new data capture before we can analyze
   them properly?**
   - **Options-vol / IV-rank cohorts** — SHDB has the source columns
     but trend's `feature_json` doesn't persist them. Add to the
     evidence puller.
   - **Sector neutrality** — `sector` is captured but we don't
     currently bucket by sector × extension. Could be done in this
     package by extending the bucket functions, but the sample per
     sector × bucket cell is too small at today's panel.
   - **Volatility regime (VIX or realized-vol percentile)** — not
     captured at run time.
   - **News / sentiment / event proximity** — captured for the
     emitted recs via the LLM payload, but not back-fillable for the
     candidate cohort that *didn't* reach the gate.

   The cleanest next data-capture step (if/when we want it) is widening
   `feature_json` on `mef.candidate` to include `atm_iv_30d`,
   `iv_percentile`, `sma_200_slope`, and `vol_regime`, then re-running
   this same research package in a month with the richer feature set.
