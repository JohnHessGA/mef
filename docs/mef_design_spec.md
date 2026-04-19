# MEF Design Spec

Version: 2026-04-19
Companion doc: `docs/README_mef.md` (build specification, scope, UX)

This document is the **technical** view of MEF: components, data model, pipeline, scoring, LLM policy, and MEFDB schema. The README is the source of truth for scope and user experience; this spec is the source of truth for architecture.

---

## 1. Goals and Non-Goals

### Goals

- Produce two daily emails (pre-market, post-market) containing high-conviction new ideas and up-to-date guidance on active recommendations + tracked positions.
- Track every recommendation MEF has ever emitted through a small, auditable lifecycle.
- Score closed recommendations against a consistent win / loss / timeout rule plus an estimated 100-share P&L.
- Ship the daily loop end-to-end as quickly as possible, even if v1's ranker is shallow and the LLM prompt is unrefined.
- Stay well below the complexity of DAS. MEF is deliberately a narrower, faster-to-ship tool.

### Non-goals (v1)

- Broad-market screening.
- DAS integration.
- RSE integration.
- Backtesting.
- Broker integration, live trade automation, execution logic.
- Non-equity asset classes.
- A web UI (may come later).
- Any notification channel beyond the two scheduled emails.

---

## 2. Architecture

MEF is a **top-level application stream**, peer to IRA Guard, consuming the AFT foundation.

```
  SHDB ──────────────────┐
  (curated market data)  │
                         ▼
  Fidelity Positions ──► MEF ──► MEFDB (mef.*)
  CSV (daily)            │         │
                         ▼         ▼
                   Claude CLI   Overwatch (ow.mef_run / ow.mef_event)
                   (LLM review)    │
                         │         ▼
                         ▼      MDC notify.py ──► 2 daily emails
```

Reads:
- **SHDB** — primary data source for all evidence.
- **Fidelity Positions CSV** — user's real holdings (same file format as IRA Guard).

Writes:
- **MEFDB** — all MEF state.
- **Overwatch** — telemetry (fail-silent).

Calls:
- **Claude CLI** (`claude -p`) for the LLM review step (pluggable — see §11).
- **MDC notify.py** for the two daily emails.

MEF writes nothing back to SHDB, RSDB, PHDB, DASDB, or MASD.

---

## 3. Components

Conceptual modules (concrete module layout lives with the code):

| Component | Responsibility |
|---|---|
| `config` | Load `config/mef.yaml` + `config/postgres.yaml`, expose typed settings |
| `db` | MEFDB connection pool, migrations, repositories |
| `universe` | Load/sync universe from notes files; expose in-memory universe object |
| `shdb_reader` | Read-only SHDB queries for every evidence family |
| `import` | Ingest Fidelity Positions CSV → `position_snapshot` + `import_batch` |
| `evidence` | Compute per-symbol features from SHDB data |
| `ranker` | Deterministic scoring + directional posture + draft entry/exit plans |
| `llm` | Pluggable LLM client (Claude CLI default), prompt assembly, `llm_trace` logging |
| `recommendations` | Lifecycle state machine, active-position inference, dismissal, expiration, close detection |
| `scoring` | Compute win/loss/timeout + estimated 100-share P&L + benchmark comparisons |
| `email` | Render pre-market / post-market email bodies; hand to `notify.py` |
| `cli` | argparse entry points for every `mef` subcommand |
| `telemetry` | Fail-silent writes to `ow.mef_run` / `ow.mef_event` |

Composition over inheritance; no base-class hierarchies. Evidence, LLM provider, and notification sender are all swappable via config.

---

## 4. Data Sources

### 4.1 SHDB

Every evidence family in v1 must resolve to SHDB tables that already exist. Initial mapping:

| Evidence family | SHDB source |
|---|---|
| Price + volume behavior | `shdb.stock_price_1d`, `shdb.mart.stock_equity_daily`, `shdb.mart.stock_etf_daily` |
| Returns | `shdb.stock_returns_1d` |
| Momentum, trend, volatility | `shdb.stock_technicals_1d` |
| Options context | `shdb.options_snapshot_1d`, `shdb.mart.stock_options_underlying_daily`, `shdb.mart.stock_options_contract_daily` |
| Symbol reference | `shdb.symbol_master` |
| Benchmark-relative | SPY + sector ETF rows in the same price/returns/technicals tables |
| Earnings proximity | whichever SHDB earnings-calendar table is present (confirm during implementation) |

If any evidence family in the MEF overview doc does not have SHDB coverage (e.g., congressional trading, whale activity, certain sentiment overlays), it is **deferred**, not stubbed. The design spec's evidence list equals what is actually wired.

### 4.2 Fidelity Positions CSV

Same file the user already downloads for IRA Guard. MEF accepts an arbitrary path via `mef import-positions <csv>` and writes an `import_batch` + a set of `position_snapshot` rows. No sharing of PHDB tables in v1 — MEF maintains its own copy (simpler than a cross-database read; can be revisited).

### 4.3 Benchmarks

`SPY` + the seven sector ETFs (XLK/XLF/XLV/XLE/XLI/XLY/XLP) are already in the 15-ETF universe. All benchmark series are **joined from SHDB at read time**. If this causes a measurable slowdown, we cache a narrow `mef.benchmark_snapshot` daily; do not build the cache up front.

---

## 5. Daily Run Pipeline

```
mef run --when {premarket|postmarket}

  0. Acquire run lock (PID file + ow.mef_lock row, fail-fast on stale lock)
  1. Open daily_run row (status=running, when, intent)
  2. Load universe from mef.universe_stock + mef.universe_etf
  3. For each symbol, pull evidence from SHDB (parallelize; see §12)
  4. Compute features + directional posture → one candidate row per symbol
  5. Rank candidates; select top-N per side subject to thresholds
  6. Draft entry/exit/invalidation plan for each survivor
  7. LLM final review over survivors (Claude CLI, logged to llm_trace)
  8. Finalize new-ideas list (can be empty)
  9. Re-evaluate active recommendations + tracked positions:
       - re-score evidence for each
       - check invalidation / time-exit / target triggers
       - write recommendation_update rows for changes
       - transition lifecycle states where warranted
 10. Persist all outputs; close daily_run (status=ok|failed, timings)
 11. Render email body (new ideas + active updates + scoring footer)
 12. Hand off to notify.py --source MEF
 13. Write ow.mef_run success/failure; release lock
```

Pre-market and post-market runs share the pipeline; the only difference is the `intent` label on `daily_run` (`today_after_10am` vs `next_trading_day`) and whichever is the freshest available market data at run time. Cron schedule (tentative, America/New_York):

- **Pre-market:** ~07:00 ET, Mon–Fri
- **Post-market:** ~17:30 ET, Mon–Fri

Both times finalized during implementation; they must sit after the daily SHDB refresh that feeds them.

---

## 6. Evidence & Ranker

### 6.1 v1 evidence set (small on purpose)

- 20 / 50 / 200-day price trend posture
- Short-term momentum (5 / 20-day return)
- Volatility regime (rolling std / ATR-style)
- Volume vs. 20-day average
- SPY-relative 20 / 60-day performance
- Sector-ETF-relative 20 / 60-day performance
- Options presence / rough liquidity (used as a go/no-go for option-income expressions)
- Earnings-within-N-days flag (suppresses or caveats ideas with near-term event risk)

Additional families from the overview doc (seasonality, news sentiment, documented strategy models, congressional / whale activity) are **deferred** until the SHDB-backed mapping is clear.

### 6.2 Ranker

- Deterministic, per-symbol scorer returning:
  - directional posture: `bullish` / `bearish_caution` / `range_bound` / `no_edge`
  - a scalar conviction score
  - a proposed expression (buy shares, covered call, cash-secured put, etc.)
  - draft entry zone, stop / invalidation level, target, time-exit horizon
- Sort by conviction within each directional posture.
- Apply a **global minimum conviction threshold**; everything below is `no_edge` and ineligible to be emitted.
- Cap emitted new ideas per run (target 3–5).
- "No new trades today" is the honest, expected output on weak days.

The ranker's rules and weights will iterate. The important property is that the ranker alone decides **whether** to emit and how many; the LLM step only reviews what the ranker proposed.

---

## 7. Recommendation Lifecycle

### 7.1 State machine

```
     proposed ─────► active ────► closed_win
        │              │      ╲─► closed_loss
        │              │      ╲─► closed_timeout
        │              │
        │              └────► closed_timeout  (time-exit reached unfilled inside a scale-in)
        │
        ├─► expired      (entry window closed, never filled)
        └─► dismissed    (CLI: mef dismiss)
```

### 7.2 Transitions

| From | To | Trigger |
|---|---|---|
| *(new)* | `proposed` | Emitted by a run |
| `proposed` | `active` | Next `position_snapshot` shows user holds the symbol consistent with the proposed entry |
| `proposed` | `expired` | Entry window end-date < today AND no import has shown the position |
| `proposed` | `dismissed` | `mef dismiss <rec-id>` |
| `active` | `closed_win` / `closed_loss` / `closed_timeout` | See §8 |

Transitions are computed at **every run** (and also at every `mef import-positions`). The state machine is idempotent — running twice produces the same state.

### 7.3 Active-position inference rules

- Match is symbol-level plus a quantity/cost sanity check vs. the proposed entry price. Tunable tolerances (e.g., `quantity >= 50` of proposed size, `entry price within 5% of proposed zone`) live in config.
- A proposed recommendation matches **the first** consistent holdings row that appears after emission.
- If a symbol is already held at proposal time, MEF treats it as an "already held" flag on the recommendation (no auto-activation), so the user isn't surprised by instant activation.

### 7.4 Scoping note on "mine" vs. MEF's tracked set

"Active positions" = symbols MEF has an open recommendation on **and** symbols present in the latest Fidelity import. The two sets can overlap or not:

- Rec emitted + holding shows up → `active` (tracked in both senses)
- Holding exists with no MEF rec → reported in the email as an "other held" position, with read-only status context; MEF does not propose on it unless a new-idea conviction passes the threshold
- Rec emitted, no holding, window passes → `expired`

---

## 8. Scoring

### 8.1 Outcome rule

- `closed_win` — realized round-trip profit at current sell. For short-option expressions (covered call, cash-secured put), option expired OTM → premium kept → win.
- `closed_loss` — realized round-trip loss at current sell, **including** "was up, is now down, sold." Paper gains that reverse before exit are losses.
- `closed_timeout` — time-based exit reached without hitting target or invalidation; realized at that day's close.

### 8.2 Estimated P&L

```
estimated_pnl_100_shares_usd = (exit_price - entry_price) * 100
```

(For short options, use realized premium equivalent; formula tracked separately and documented when that expression ships.)

### 8.3 Benchmark context

For each closed recommendation, record SPY + relevant sector ETF % return over the same calendar window. Do **not** use this to reclassify the outcome; it's supporting context.

### 8.4 Future: real P&L

Once we're comfortable, replace `estimated_pnl_100_shares_usd` with actual realized dollars derived from IRA Guard/PHDB holdings history. v1 stays on the 100-share estimate to avoid PHDB coupling.

---

## 9. Benchmarks

MEF reads benchmark series (SPY + sector ETFs) live from SHDB when computing:

- Evidence (SPY-relative, sector-relative performance)
- Per-closed-recommendation benchmark context

Caching lives in `mef.benchmark_snapshot` **only if** live joins prove too slow. Default path: direct SHDB joins.

---

## 10. LLM Policy

### 10.1 Provider

- **Default:** Claude CLI — invoked as `claude -p <prompt>` on the Claude Pro subscription.
- **Pluggable:** a `LLMProvider` interface with `generate(prompt) -> LLMResponse`. Config key `mef.llm.provider` selects which implementation. v1 ships `claude_cli`; a `anthropic_api` or other provider can be dropped in later without touching the ranker.

### 10.2 Role

The LLM is used **only** at step 7 of the pipeline (final review) and step 11 (reasoning text in email).

Specifically the LLM:

- Reviews the deterministic ranker's emitted candidates + supporting evidence
- Provides a short color / context paragraph per survivor
- Flags any candidate whose plan looks inconsistent with broader market context (the flag is informational — a human-readable concern field stored on the recommendation)
- Produces the "short reasoning summary" that appears in the email

The LLM does **not**:

- Propose new candidates the ranker didn't
- Change entry / exit / invalidation prices
- Decide whether "no new trades today" is the right answer
- Run as part of active-position re-evaluation in v1 (may change later)

### 10.3 Prompt shape (v1 sketch)

The v1 prompt asks Claude, in plain English, whether MEF's assumptions and plans look reasonable given its broader knowledge, and requests a short context paragraph per candidate. The prompt will iterate; the first version is deliberately simple. The prompt template lives in `src/mef/llm/prompts.py` (path to be confirmed during implementation) and is versioned in git.

### 10.4 Logging

Every LLM call is logged to `mef.llm_trace`:

- `llm_uid` (L-…)
- `daily_run_uid`
- `candidate_uid` (nullable — for batch reviews)
- `provider` (e.g., `claude_cli`)
- `model` (captured from the provider's response metadata)
- `prompt_text`, `response_text`
- `elapsed_ms`
- `status` (`ok`, `error`, `timeout`)
- `error_text`

`llm_trace` is append-only. Cost/drift analysis runs off this table.

### 10.5 Failure handling

If the LLM call fails or times out, MEF proceeds with the ranker's output and fills `llm_review_color` with a "LLM review unavailable" placeholder. The run does not fail. The failure is recorded in `llm_trace` and surfaced as a warning in the email footer.

---

## 11. MEFDB Schema

PostgreSQL 16 on the shared `localhost:5432`. Database `mefdb`, schema `mef`, owner `mef_user`. Credentials in `config/postgres.yaml` (gitignored) with `mefdb` + `shdb` + `overwatch` sections.

**Table list (v1, conceptual).** Columns below list the load-bearing fields; exact column types, defaults, and indexes are finalized when DDL is written.

### `mef.universe_stock`

Holds the 305 stocks. Loaded from `notes/focus-universe-us-stocks-final.md` by `mef universe load`.

- `symbol` (PK)
- `company_name`
- `sector`, `industry`
- `avg_close_90d`, `avg_volume_90d`, `avg_dollar_volume_90d`
- `market_cap_usd`
- `options_expirations`, `total_open_interest`
- `last_refreshed_at`

### `mef.universe_etf`

The 15 ETFs.

- `symbol` (PK)
- `role` (e.g., `broad_market`, `size`, `style_value`, `style_growth`, `sector_tech`, `industry_semis`, …)
- `description`
- `last_refreshed_at`

### `mef.daily_run`

One row per scheduled run.

- `run_uid` (PK, prefix `DR-`)
- `when_kind` (`premarket` / `postmarket`)
- `intent` (`today_after_10am` / `next_trading_day`)
- `started_at`, `ended_at`
- `status` (`running` / `ok` / `failed` / `partial`)
- `symbols_evaluated`, `candidates_passed`, `recommendations_emitted`
- `email_sent_at` (nullable)
- `notes`
- `error_text`

### `mef.candidate`

One row per symbol per run.

- `candidate_uid` (PK, prefix `C-`)
- `run_uid` (FK)
- `symbol`
- `asset_kind` (`stock` / `etf`)
- `posture` (`bullish` / `bearish_caution` / `range_bound` / `no_edge`)
- `conviction_score`
- `feature_json` (all evidence values used)
- `proposed_expression` (nullable until a plan is drafted)
- `proposed_entry_zone`, `proposed_stop`, `proposed_target`, `proposed_time_exit`
- `emitted` (bool — whether this candidate became a recommendation)

### `mef.recommendation`

The user-visible output of the tool. Lifecycle lives here.

- `rec_uid` (PK, prefix `R-`)
- `run_uid` (emitting run)
- `candidate_uid` (source candidate)
- `symbol`, `asset_kind`
- `posture`
- `expression` (`buy_shares`, `buy_etf`, `covered_call`, `cash_secured_put`, `reduce`, `exit`, `hedge`, …)
- `entry_method`, `entry_window_end`
- `stop_level`, `invalidation_rule`
- `target_level`, `target_rule`
- `time_exit_date`
- `confidence`
- `reasoning_summary` (LLM-produced in v1)
- `llm_review_color`, `llm_review_concern`
- `state` (`proposed` / `active` / `dismissed` / `expired` / `closed_win` / `closed_loss` / `closed_timeout`)
- `state_changed_at`, `state_changed_by` (`run` / `import` / `cli`)
- `active_match_position_uid` (FK to `position_snapshot`, nullable)
- `created_at`, `updated_at`

### `mef.recommendation_update`

Per-run delta log for active recommendations and tracked positions.

- `update_uid` (PK)
- `rec_uid` (FK)
- `run_uid` (FK)
- `prior_state`, `new_state`
- `prior_stop`, `new_stop`, `prior_target`, `new_target`, `prior_time_exit`, `new_time_exit`
- `thesis_status` (`intact` / `weakening` / `broken`)
- `guidance` (`hold` / `reduce` / `exit` / `hedge` / `raise_stop` / `tighten_target` / `revise_entry` / …)
- `notes`
- `created_at`

### `mef.import_batch`

One row per Fidelity CSV import.

- `import_uid` (PK, prefix `I-`)
- `source_path`
- `file_hash`
- `as_of_date`
- `row_count`
- `status` (`ok` / `failed`)
- `error_text`
- `created_at`

### `mef.position_snapshot`

One row per position per import.

- `position_uid` (PK, prefix `P-`)
- `import_uid` (FK)
- `account`
- `symbol`
- `quantity`
- `cost_basis_total`, `cost_basis_per_share`
- `last_price`
- `market_value`
- `as_of_date`

### `mef.benchmark_snapshot`

Only populated if we end up caching (see §9).

- `date`
- `symbol` (SPY / XL\*)
- `close`, `return_1d`, `return_20d`, `return_60d`

### `mef.score`

One row per closed recommendation.

- `score_uid` (PK, prefix `S-`)
- `rec_uid` (FK, unique)
- `outcome` (`win` / `loss` / `timeout`)
- `entry_price`, `exit_price`, `entry_date`, `exit_date`
- `days_held`
- `estimated_pnl_100_shares_usd`
- `spy_return_same_window`, `sector_etf_symbol`, `sector_etf_return_same_window`
- `notes`
- `created_at`

### `mef.llm_trace`

Every LLM call.

- `llm_uid` (PK, prefix `L-`)
- `run_uid` (FK)
- `candidate_uid` (FK, nullable)
- `provider`, `model`
- `prompt_text`, `response_text`
- `elapsed_ms`
- `status`, `error_text`
- `created_at`

### `mef.command_log`

Every CLI invocation (for auditability; mirrors the pattern used in other AFT tools).

- `command_uid` (PK)
- `command` (full argv)
- `started_at`, `ended_at`
- `exit_status`
- `notes`

### Indexes (initial)

- `recommendation (state, symbol)`
- `recommendation (run_uid)`
- `candidate (run_uid, symbol)`
- `position_snapshot (symbol, as_of_date)`
- `llm_trace (run_uid, created_at)`
- `daily_run (started_at desc)`
- `score (rec_uid)` unique

Add targeted indexes only as query patterns surface. Do not pre-index.

---

## 12. Performance & Concurrency

- Symbol-level work in the daily run (evidence pull, feature compute) is **parallelized** with a small pool. The universe is 320 symbols; a sequential pass is acceptable for v1 but parallelization is the first optimization if a run is too slow.
- Only one run at a time — enforced by a PID file + `ow.mef_lock` row (same dual-lock pattern as MDC / UDC / IRA Guard). A stale lock is auto-cleared when the owning PID is dead.
- LLM calls are the slowest step. Start with a single batch LLM call over all survivors; split only if latency becomes a problem.

---

## 13. Output (Email Rendering)

Two emails per trading day. Rendered as plain text **plus** an HTML part (HTML is a nicety, not required for v1 if it's faster to ship text-only).

Email body layout:

```
Subject: MEF pre-market report — YYYY-MM-DD (today after 10:00 ET)

Header
  Run: DR-…, pre-market, completed HH:MM ET
  Universe: 305 stocks, 15 ETFs (N evaluated)
  SPY: …, broad posture: …

New ideas (K):
  1. SYMBOL — posture — expression
     Entry: …
     Stop / invalidation: …
     Target: …
     Time exit: …
     Confidence: …
     Reasoning: …  (from LLM)

 (or: "No new trades today.")

Active recommendations & tracked positions (M):
  SYMBOL (rec R-…)  state=active  thesis=intact
    guidance: hold
    stop: … (unchanged)
    target: … (unchanged)
  …

Scoring summary (last 30 days):
  wins: X, losses: Y, timeouts: Z, net est. P&L/100 shares: $…

Footer
  CLI: mef show R-<id>, mef dismiss R-<id>, mef status
  Run log: ow.mef_run DR-…
```

Subject line differs between runs (`pre-market` vs `post-market`). The "no new trades today" case still sends a complete email with an empty New-ideas section — MEF never skips a scheduled email.

Delivery: `notify.py --source MEF --to <configured-email>`. No SMS, no other channels.

---

## 14. Telemetry

Fail-silent writes to the `overwatch` database:

- `ow.mef_run` — one row per run: `run_uid`, `when_kind`, `intent`, `started_at`, `ended_at`, `status`, `symbols_evaluated`, `recommendations_emitted`, `email_sent`, `error_text`.
- `ow.mef_event` — discrete events: `event_uid`, `run_uid`, `severity` (`info` / `warning` / `error`), `code`, `message`, `created_at`.

Never block an email or a run because telemetry is down.

Dashboards:

- **MEF — Runs:** last runs, status, duration, ideas emitted, emails sent
- **MEF — Recommendations:** active count, win/loss/timeout over time, P&L histogram
- **MEF — LLM:** call volume, latency, failures (from `mef.llm_trace`)

Dashboards come after the first real runs exist; don't build them up front.

---

## 15. Repository Shape

```
~/repos/mef/
  .gitignore
  pyproject.toml              # editable install, Python 3.12
  README.md                    # short pointer to docs/
  CLAUDE.md                    # mirrors RSE pattern — working instructions for code assistants
  config/
    mef.yaml                   # cadence, thresholds, LLM provider, email recipients
    postgres.yaml              # gitignored — mefdb / shdb / overwatch credentials
  docs/
    README_mef.md              # this spec's companion (build specification)
    mef_design_spec.md         # this document
    mef_cli.md                 # written during implementation
    mef_mefdb_schema.md        # canonical DDL, written during implementation
  notes/
    muse-engine-forecaster-overview.md
    focus-universe-us-stocks-final.md
    core-us-etfs-daily-final.md
  src/
    mef/
      __init__.py
      cli.py
      config/
      db/
      universe/
      shdb_reader/
      import/
      evidence/
      ranker/
      llm/
      recommendations/
      scoring/
      email/
      telemetry/
  sql/
    migrations/                # forward-only DDL, numbered
  tests/
    unit/                      # pure-logic tests (ranker, lifecycle, scoring)
    integration/               # DB-backed tests against a scratch MEFDB
  venv/ | .venv/               # local, gitignored
```

Follows MDC / UDC / RSE / IRA Guard conventions. Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`).

---

## 16. Configuration

`config/mef.yaml` holds operational knobs; `config/postgres.yaml` holds credentials.

Representative `mef.yaml` structure (exact keys settled during implementation):

```yaml
cadence:
  premarket_cron: "0 7 * * 1-5"      # 07:00 ET Mon–Fri
  postmarket_cron: "30 17 * * 1-5"   # 17:30 ET Mon–Fri
  timezone: America/New_York

ranker:
  conviction_threshold: 0.6
  max_new_ideas_per_run: 5

llm:
  provider: claude_cli
  claude_cli:
    binary: claude
    model_hint: opus      # captured via response metadata
    timeout_seconds: 120
  fallback_on_error: proceed_without_llm

email:
  recipients:
    - john.hess.ga@gmail.com
  subject_prefix_premarket: "MEF pre-market report"
  subject_prefix_postmarket: "MEF post-market report"

position_matching:
  min_quantity_match: 50
  entry_price_tolerance_pct: 5.0

universe:
  stocks_notes_path: notes/focus-universe-us-stocks-final.md
  etfs_notes_path: notes/core-us-etfs-daily-final.md
```

---

## 17. Testing Priorities

Pure-logic tests first:

- Ranker: given a fixed feature set, expected posture and score
- Lifecycle: every valid state transition, idempotency of re-runs
- Active-position inference: varying overlap of holdings and proposed entries
- Scoring: win/loss/timeout classification and estimated-P&L math
- Email rendering: new-ideas list empty / single / many; active-position formatting
- Expiration: entry window past → `expired` exactly once

DB-backed tests against a scratch MEFDB:

- Universe load idempotency
- Full-pipeline smoke test with a tiny stub SHDB dataset
- Lock behavior (two concurrent runs contending)

Real CLI tests:

- `mef run --when premarket` end-to-end on a dev schema
- `mef dismiss` / `mef import-positions` / `mef show` against real rows

`pytest -q` runs fast; add tests for new pure logic as it lands.

---

## 18. Open Decisions (to settle during implementation)

- Exact SHDB earnings-calendar table (confirm during v1 build).
- Long-option outcome scoring when/if long-premium expressions become in-scope.
- Email format: plain-text only v1, or HTML v1?
- Whether `mef.benchmark_snapshot` is built up front or added only on performance grounds.
- Cron times for pre-market / post-market after checking MDC/UDC schedules to avoid contention.
- Whether to standardize the LLM prompt as a versioned file (`prompts/v1.txt`) or a Python constant.

Nothing in this list blocks the build; each resolves at the natural point in the build order.

---

## 19. Non-Standard Choices Worth Calling Out

- **MEF maintains its own `position_snapshot` rather than reading PHDB.** Chosen for independence from IRA Guard's DB; if the tools are ever merged or share an ingest step, this is an easy refactor.
- **LLM review produces the `reasoning_summary` that ships in the email.** If the LLM is unavailable, the recommendation still ships with the deterministic plan but a placeholder reasoning field.
- **"No new trades today" is a real email body.** MEF never suppresses an email just because nothing happened.
- **Short-option OTM expiration = win.** Stated explicitly because the raw design note is ambiguous on long vs. short options; v1 only emits short-option expressions, so this is consistent.
- **Scoring starts at 100-share P&L estimate.** Real P&L via PHDB is explicitly a v2 concern.

---

## 20. Minimum Path to "Working for Testing"

The smallest thing worth calling v1:

1. `mef status` returns.
2. `mef universe load` populates the 305+15.
3. `mef import-positions` ingests a real Fidelity CSV.
4. `mef run --when postmarket` runs end-to-end against SHDB with a crude ranker, produces zero-or-more recommendations, logs an LLM trace, and sends a real email.
5. `mef dismiss <rec-id>` works. Expiration and auto-activation work on the next run.
6. `mef score` runs over whatever has closed.
7. Two cron entries fire pre- and post-market on weekdays.

Everything else — prompt tuning, richer evidence, better email, DAS/RSE integration, web UI — is iteration on top of that base.
