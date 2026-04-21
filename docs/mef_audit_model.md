# MEF Audit Data Model

Version: 2026-04-21
Status: Reference — update when scoring tables or columns change.

MEF stores **four parallel scoring tables** that together answer
"is this system working, and is the LLM gate adding value?" Each
table has a focused purpose; together they collapse the validation
horizon from "wait months for John to actually buy something and
close it" to "wait weeks for `time_exit` dates to pass."

**2026-04-21 update — per-engine attribution.** `mef.shadow_score`
and `mef.paper_score` both carry an `engine` column (`'trend'`,
`'mean_reversion'`, or `'value'`) so audit queries can ask "which
ranker engine's conviction predicts wins best?" The column is set
at INSERT from the candidate's engine (migration 009 backfilled
existing rows). Example:

```sql
SELECT engine,
       outcome,
       COUNT(*) AS n,
       AVG(estimated_pnl_100_shares_usd) AS avg_pnl
  FROM mef.paper_score
 WHERE gate_decision = 'approve'
 GROUP BY engine, outcome
 ORDER BY engine, outcome;
```

---

## The four tables at a glance

| Table                              | Keyed on                  | Populated by                                       | Question it answers                                                              |
|------------------------------------|---------------------------|----------------------------------------------------|----------------------------------------------------------------------------------|
| `mef.score`                        | `rec_uid` (UNIQUE)        | `mef score` (auto on each daily run)               | What was the actual outcome of recs the user *actually traded*?                  |
| `mef.shadow_score`                 | `candidate_uid` (UNIQUE)  | `mef score` (auto on each daily run)               | What would have happened to LLM-rejected candidates if we'd shipped them?        |
| `mef.paper_score`                  | `rec_uid` (UNIQUE)        | `mef score` (auto on each daily run)               | What would have happened to every emitted rec if you'd bought at run-day close?  |
| `mef.recommendation_pnl_daily`     | `(rec_uid, as_of_date)`   | `snapshot_daily_pnl()` in the daily pipeline       | What was the day-by-day P&L curve over the holding period?                       |

All four use **idempotent writes** (UNIQUE keys + `ON CONFLICT DO
UPDATE` where applicable) and skip rows that already exist. Re-running
`mef score` or `mef run` on the same day is safe.

---

## `mef.score` — actual outcome (real trades)

The authoritative outcome table. Populated only after a recommendation
has cycled through `proposed → active → closed_*`.

Two layers of data:

1. **Synthetic estimate** (always populated when a row exists):
   - `outcome` (`win` / `loss` / `timeout`)
   - `entry_price`, `exit_price` from the matched `position_snapshot`
   - `estimated_pnl_100_shares_usd` — synthetic 100-share scaling
   - `spy_return_same_window`, `sector_etf_return_same_window`

2. **Real-trade overlay** (populated by `mef link-trade`):
   - `realized_qty`, `realized_buy_price`, `realized_buy_date`
   - `realized_sell_price`, `realized_sell_date` (nullable while holding)
   - `realized_pnl_usd`
   - **`realized_pnl_per_day`** — the headline metric for "max profit
     in shortest time": `realized_pnl_usd / max(1, sell_date - buy_date)`

The estimated and real layers coexist. Consumers prefer real values
when present, fall back to estimated otherwise.

When a `mef.score` row's outcome disagrees with the rec's lifecycle
state (e.g., lifecycle saw `closed_timeout` but the score-grade exit
price actually breached target), the rec's `state` is updated to align
— **the score is authoritative** on outcome.

---

## `mef.shadow_score` — what MEF decided not to emit

For every candidate where `llm_gate_decision = 'reject'` OR
`suppressed_by_hazard = TRUE`, MEF forward-walks the would-have-been-
trade through the same stop / target / time_exit the candidate carried,
using close prices from `mart.stock_*_daily`.

This makes **both** the LLM gate and the Layer B hazard overlay
falsifiable: without shadow-scoring, every suppression is a black box —
we'd never know whether the LLM / overlay is removing alpha or removing
landmines.

Same outcome columns as `mef.score`. Plus:

- `gate_decision` — either the literal LLM verdict (`'reject'`) or the
  sentinel string `'hazard_suppressed'` for Layer B suppressions. The
  column answers "why wasn't this emitted?" at audit time.
- Keyed on `candidate_uid` because rejected / suppressed candidates
  never become recommendations — they don't have a `rec_uid`.

Defers scoring when `time_exit` hasn't passed and no breach has
occurred yet — those rows materialize automatically on a later run.

Source: `src/mef/shadow_scoring.py`. Algorithm: `classify_walk()`.

---

## `mef.paper_score` — what every emitted rec would do

Same forward-walk as `mef.shadow_score`, but applied to **every emitted
recommendation** (`gate_decision in {approve, review, unavailable}`).
Reuses `classify_walk()` so the methodology is identical to shadow
scoring — paper and shadow outcomes can be directly compared.

This is the unlock that makes `mef gate-audit` meaningful:

- **Approved** (paper) vs **Rejected** (shadow) → "is the LLM right to reject?"
- **Approved** (paper) vs **Review** (paper) → "is the LLM too cautious in flagging review?"
- **Approved** (paper) vs **Real** (`mef.score`) → "are paper outcomes a good proxy for real outcomes?"

Same outcome columns as `mef.score` plus:

- `rec_uid` (the emitted rec)
- `candidate_uid` (cross-reference back to the candidate row)
- `gate_decision` (`approve` / `review` / `unavailable`)

Source: `src/mef/paper_scoring.py`.

---

## `mef.recommendation_pnl_daily` — the holding-period curve

One row per `(rec_uid, as_of_date)` for every active rec, plus a
**close-day row** (`is_close_day = TRUE`) for any rec that just
transitioned to a closed state.

Answers "**where in the holding window did the gains come from?**" —
straight-line drift, late pop, early spike-then-fade, etc. Useful when
real `realized_pnl_per_day` exists but you want to understand the
shape of the trade, not just its endpoint.

Columns:

- `quantity`, `cost_basis_per_share`, `last_price`, `market_value`
- `unrealized_pnl_usd`, `unrealized_pnl_pct`
- `days_held_so_far`
- `is_close_day` — TRUE on the final row, indexed for fast filtering
- `price_source` — `position_snapshot` (preferred) / `mart` (fallback) / `none`
- `notes`

Price source priority:

1. **`mef.position_snapshot`** for the symbol — typically last night's
   Fidelity CSV, carrying the end-of-day mark with cost basis.
2. **`mart.stock_*_daily`** latest close — fallback when no position
   snapshot exists for the symbol (rare; means user sold but never
   reimported).
3. **Skip** — surfaced in the run summary's `pnl_snapshot` event so
   you know coverage is incomplete.

Idempotent via `ON CONFLICT (rec_uid, as_of_date) DO UPDATE`.

Source: `src/mef/pnl_tracking.py`.

---

## Decision tree: which table answers what

```
"What's MEF's actual win rate for trades I made?"
    → mef.score (filter by outcome)

"What's my actual P&L per day held?"
    → mef.score.realized_pnl_per_day
    → requires `mef link-trade` to have been run

"Is the LLM gate adding value?"
    → mef gate-audit (compares mef.paper_score approve vs mef.shadow_score)
    → wait for ~20 settled outcomes per side before trusting the diff

"Is the LLM too cautious with `review`?"
    → mef.paper_score WHERE gate_decision='review'
    → if win rate ≈ approved → too cautious; if ≈ rejected → caution earned

"How does MEF look if you bought every approved idea at run-day close?"
    → mef.paper_score WHERE gate_decision='approve'

"How did this specific rec progress day by day?"
    → mef.recommendation_pnl_daily WHERE rec_uid=...
    → also visible inline via `mef show <rec-uid>`

"Did MEF actually drive my purchase, or was it ambient?"
    → mef.recommendation.provenance
    → mef_attributed | pre_existing | independent

"What did the LLM reject, and why?"
    → mef rejections (or mef.candidate WHERE llm_gate_decision='reject')
    → llm_gate_issue_type for the structured reason class
```

---

## Sample queries

### Win rate by gate decision (paper scores)

```sql
SELECT gate_decision,
       COUNT(*)                                  AS n,
       COUNT(*) FILTER (WHERE outcome='win')     AS wins,
       ROUND(100.0 * COUNT(*) FILTER (WHERE outcome='win') / COUNT(*), 1) AS win_pct,
       ROUND(AVG(estimated_pnl_100_shares_usd)::numeric, 2) AS avg_pnl_100sh
  FROM mef.paper_score
 GROUP BY gate_decision
 ORDER BY gate_decision;
```

### LLM-rejected vs paper-approved, side by side (the headline)

```sql
WITH approved AS (
    SELECT outcome, estimated_pnl_100_shares_usd
      FROM mef.paper_score WHERE gate_decision = 'approve'
), rejected AS (
    SELECT outcome, estimated_pnl_100_shares_usd
      FROM mef.shadow_score
)
SELECT 'approved' AS bucket, COUNT(*) n,
       ROUND(100.0 * COUNT(*) FILTER (WHERE outcome='win') / COUNT(*), 1) win_pct,
       ROUND(AVG(estimated_pnl_100_shares_usd)::numeric, 2) avg_pnl
  FROM approved
 UNION ALL
SELECT 'rejected', COUNT(*),
       ROUND(100.0 * COUNT(*) FILTER (WHERE outcome='win') / COUNT(*), 1),
       ROUND(AVG(estimated_pnl_100_shares_usd)::numeric, 2)
  FROM rejected;
```

(`mef gate-audit` does this comparison in pure Python with sample-
size discipline — prefer the CLI for routine use.)

### Issue-type frequency on rejects

```sql
SELECT llm_gate_issue_type, COUNT(*)
  FROM mef.candidate
 WHERE llm_gate_decision = 'reject'
 GROUP BY 1
 ORDER BY 2 DESC;
```

A skewed distribution suggests the prompt could be tightened on the
dominant category.

### Real outcome vs paper outcome for the same rec

```sql
SELECT s.rec_uid, s.outcome AS real_outcome, p.outcome AS paper_outcome,
       s.estimated_pnl_100_shares_usd AS real_est_pnl,
       p.estimated_pnl_100_shares_usd AS paper_pnl,
       s.realized_pnl_per_day
  FROM mef.score s
  JOIN mef.paper_score p USING (rec_uid)
 ORDER BY s.created_at DESC
 LIMIT 20;
```

Once enough rows accrue, look for systematic gaps between `real_outcome`
and `paper_outcome` — that's how you find out whether the synthetic
entry-at-close-of-run-day proxy actually tracks reality.

### P&L curve for one rec (in SQL — `mef show` is usually easier)

```sql
SELECT as_of_date, last_price, market_value,
       unrealized_pnl_usd, unrealized_pnl_pct,
       is_close_day, price_source
  FROM mef.recommendation_pnl_daily
 WHERE rec_uid = 'R-000032'
 ORDER BY as_of_date;
```

---

## Sample-size discipline

- `MIN_SAMPLE_FOR_SIGNAL = 20` (in `gate_audit.py`)
- Below that, `mef gate-audit` withholds the headline diff and prints
  the warning *"Sample insufficient: need ~20+ settled outcomes per side."*
- Realistic timing: at the configured `max_new_ideas_per_run = 5` and
  most recs deferring until `time_exit` (~3 weeks out by default),
  expect signal-grade samples roughly **6-8 weeks after first run**.
- Don't tune the prompt or the conviction threshold off pre-signal
  data. Pattern-match temptation is high; the noise floor is higher.

---

## Telemetry mirror

The `ow.mef_run` row for each daily run carries scalar counts that
mirror the audit-table activity (so Grafana dashboards don't need to
join into MEFDB):

| Column           | Meaning                                               |
|------------------|-------------------------------------------------------|
| `gate_approved`  | LLM decisions: count of `approve`                     |
| `gate_review`    | LLM decisions: count of `review`                      |
| `gate_rejected`  | LLM decisions: count of `reject`                      |
| `gate_unavailable`| LLM decisions: count of `unavailable` (gate down)    |
| `scored`         | New `mef.score` rows written this run                 |
| `shadow_scored`  | New `mef.shadow_score` rows written                   |
| `shadow_deferred`| Rejected candidates still waiting on `time_exit`      |
| `paper_scored`   | New `mef.paper_score` rows written                    |
| `paper_deferred` | Emitted recs still waiting on `time_exit`             |

(The pnl_daily writes don't have dedicated columns — they fire as
`pnl_snapshot` events on `ow.mef_event`.)

---

## Reference

- Real scoring: `src/mef/scoring.py`
- Shadow scoring: `src/mef/shadow_scoring.py`
- Paper scoring: `src/mef/paper_scoring.py`
- Daily P&L tracking: `src/mef/pnl_tracking.py`
- Gate audit aggregator: `src/mef/gate_audit.py`
- Audit CLI: `src/mef/commands/gate_audit.py`
- Schema migrations:
  - `sql/mefdb/003_shadow_score.sql`
  - `sql/mefdb/004_paper_score.sql`
  - `sql/mefdb/007_recommendation_pnl_daily.sql`
  - `sql/mefdb/008_score_realized_pnl.sql`
- Operations workflow: `mef_operations.md`
- LLM gate design: `mef_llm_gate.md`
