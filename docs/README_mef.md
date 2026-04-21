# MEF — Muse Engine Forecaster

Version: 2026-04-20
Status: Built and running daily — see `mef_build_order.md` for milestone status
Database: MEFDB — Muse Engine Forecaster Database
Repo/tool name: `mef`

---

## Companion docs

This file is the high-level build spec — what MEF is, why it exists, and the v1 scope. Most readers want one of:

- **[`mef_operations.md`](mef_operations.md)** — how to use MEF day-to-day (the email, the CLI, the audit cadence). Start here if you're operating the tool.
- **[`mef_design_spec.md`](mef_design_spec.md)** — architectural design, full schema, pipeline internals.
- **[`mef_build_order.md`](mef_build_order.md)** — living milestone tracker; current state of every feature.
- **[`mef_llm_gate.md`](mef_llm_gate.md)** — LLM gate philosophy, 3-way disposition vocabulary, prompt iteration guide.
- **[`mef_audit_model.md`](mef_audit_model.md)** — the four scoring tables (real / shadow / paper / daily-pnl) and which question each answers.
- **[`mef_cron.md`](mef_cron.md)** — cron install steps.

---

## Purpose

MEF is a **daily forecasting and recommendation tool** over a fixed, curated universe of **305 US stocks and 15 core US ETFs** (320 symbols total). It looks at that focused pool every trading day, weighs a mix of evidence, and returns a small number of high-conviction ideas — each with a practical entry plan and an exit/invalidation plan — or explicitly says *no new trades today*.

MEF also tracks the user's real holdings and every recommendation MEF has ever made, updating their status each run until they are filled, dismissed, expired, or closed. Each closed recommendation is scored win / loss / timeout with an estimated P&L for 100 shares.

MEF is **advisory only**. It never trades. It sends two emails a day and provides a CLI. That's the whole user surface for v1.

---

## Why MEF Exists

AFT already has:

- **MDC / UDC** — collection and curation (Bronze → Silver)
- **RSE** — Gold-layer ad-hoc inquiry ("answer my question")
- **IRA Guard** — defensive monitoring of existing holdings ("protect what I own")
- **DAS** — planned derived-analytics layer (metrics, indicators, signals)

MEF fills the **"give me ideas for today"** gap:

- **vs. RSE** — RSE is reactive and question-driven. MEF is scheduled and proactive.
- **vs. IRA Guard** — IRA Guard defends existing positions. MEF proposes new ones and updates active recommendations.
- **vs. DAS** — DAS is broader and more ambitious. **MEF is intentionally a smaller, more agile first version** of what DAS may eventually cover — narrower universe, tighter scope, fewer evidence families — so it can ship before DAS is reasonably finishable. If DAS later produces signals MEF can use, we integrate; until then MEF reads SHDB directly.

The tool is built to ship fast, run every day, and improve from its own scoring history.

---

## Design Attitude

- **Lightweight vs. DAS.** Prefer the smallest schema and thinnest evidence stack that still produces useful output. Add complexity only after we've run it daily for a while.
- **Fixed universe.** 305 stocks + 15 ETFs. No dynamic universe expansion in the near future.
- **SHDB-only data in v1.** No DAS inputs (DAS isn't built). No RSE inputs yet either (RSE is still standing up). Both are candidates for later versions.
- **Deterministic-first, LLM-reviewed.** A deterministic ranker produces the candidate list; Claude CLI reviews the top candidates as a final sanity check before publishing. The LLM adds context and color; it does not replace the ranker.
- **"No new trades today" is valid output.** Expected and healthy on weak-evidence days.
- **Ship, then iterate.** Goal is a working end-to-end daily run as fast as possible; refine evidence weights, LLM prompt, email format, and scoring in subsequent passes.

---

## Scope

### In scope (v1)

- Fixed universe: 305 US stocks + 15 core US ETFs (see `notes/focus-universe-us-stocks-final.md`, `notes/core-us-etfs-daily-final.md`)
- **Two scheduled runs per trading day:**
  - **Pre-market run** — recommendations intended to be traded **today after ~10:00 AM ET**
  - **Post-market run** — recommendations for the **next trading day**
- Evidence from SHDB only:
  - price / volume behavior
  - momentum / trend / relative strength
  - volatility behavior
  - options open interest context (where available)
  - benchmark-relative movement (SPY + sector ETFs from the 15-ETF list)
  - earnings proximity and documented calendar events (as available in SHDB)
- Directional posture per candidate: `bullish` / `bearish_caution` / `range_bound` / `no_edge`
- Trade expressions (v1): buy shares, buy ETF shares, covered call, cash-secured put, reduce / exit / hedge (existing positions), hold cash
- Per-recommendation plan: directional posture, expression, entry method, exit / invalidation, target holding window, confidence, short reasoning
- LLM final-review pass (Claude CLI) over the deterministic ranker's top candidates with a **3-way disposition** (`approve` / `review` / `reject`) and a server-validated `issue_type` taxonomy — see `mef_llm_gate.md`
- **Active-position tracking:**
  - Infer user's actual holdings from daily Fidelity Positions CSV ingest (same pattern as IRA Guard)
  - Track every MEF recommendation through its lifecycle (see §"Recommendation Lifecycle")
  - **Activation provenance** stamped at promote time (`mef_attributed` / `pre_existing` / `independent`) so future audits don't conflate ambient trades with MEF-driven ones
- **Two daily emails** sent via direct SMTP (`smtplib` reading SMTP credentials from MDC's `notifications.yaml`) — **not** via MDC's `notify.py`, which forces its own subject/body wrapper that would mangle MEF's report. Email shows LLM-approved (and unavailable-fallback) ideas as "New ideas"; LLM-review-tagged ideas appear in a separate "Held for review" section with the LLM's one-sentence reason visible so the user can decide whether to act manually. Rejected ideas remain MEFDB-only and surface via the CLI.
- **Data-freshness gate** — pipeline checks the latest mart bar age before ranking; warns above one threshold, aborts above another so MEF never ranks against silently-stale UDC data
- CLI for operator use: run, status, list/show/dismiss/tag recommendations, link real trades, gate-audit, rejections, score, init-db, universe — see `mef_operations.md` for the full quick reference
- **Four-table scoring corpus** (see `mef_audit_model.md`):
  - `mef.score` — real outcomes from trades you actually made (with optional realized P&L overlay via `mef link-trade`)
  - `mef.shadow_score` — forward-walked outcomes for every LLM-rejected candidate (makes the gate falsifiable)
  - `mef.paper_score` — forward-walked outcomes for every emitted rec (collapses validation horizon from months to weeks)
  - `mef.recommendation_pnl_daily` — day-by-day MTM curve for every active rec, with a clean close-day endpoint
- `mef gate-audit` command — side-by-side comparison of approve / review / reject / unavailable outcome distributions, with sample-size discipline
- Persistence of everything in MEFDB

### Explicitly out of scope (v1)

- Intraday / high-frequency trading
- Aggressive options speculation (long premium strategies as primary expression)
- Non-US assets
- Crypto (MEF is equity/ETF focused)
- Leveraged, inverse, or triple-leveraged ETFs
- Automatic trade execution or broker integration
- Backtesting (belongs in a future separate tool, per the same boundary RSE observes)
- Dynamic universe expansion / screening the broad market
- DAS-derived inputs (DAS does not yet exist; revisit when it does)
- RSE-produced inputs (RSE is still being built; revisit when knowledge artifacts are available)
- Web UI (may come later)
- Other notification channels (SMS, chat, push) — the two daily emails are the only outbound messages

---

## User Experience

The operator interacts with MEF through:

1. **Two scheduled emails per trading day** (cron-driven)
2. **A small CLI** for inspection and control

### Daily Emails

Each email has the same two-section layout described in `notes/muse-engine-forecaster-overview.md`:

**A. New ideas** — a short list, or explicit *"No new trades today."*
Each idea shows: symbol, stock-or-ETF, directional posture, preferred expression, entry method, exit / invalidation, target holding window, confidence, short reasoning.

**B. Existing position & recommendation updates** — for anything currently tracked:
thesis status, hold/reduce/exit/hedge guidance, revised entry/target/stop/review levels, relevant event/risk changes.

The two runs differ in intent:

| Run | Schedule | New ideas are meant for | Active-position review |
|---|---|---|---|
| Pre-market | before the US open | **today, after ~10:00 AM ET** | yes, using most recent close + pre-market context |
| Post-market | after the US close | **next trading day** | yes, using today's close |

Both emails are sent every trading day, whether or not there are new ideas. "No new trades today" is a legitimate email body.

### CLI

Full quick reference + day-to-day usage lives in **`mef_operations.md`**. Highlights:

| Command | Purpose |
|---|---|
| `mef run --when {premarket\|postmarket} [--dry-run]` | Execute one scheduled run (entry point for cron); `--dry-run` skips email send |
| `mef status` | Environment, data freshness, last run, DB connectivity |
| `mef recommendations [--state X\|--all\|--symbol\|--since <date>]` | List recommendations with lifecycle state |
| `mef show <rec-uid>` | Full detail (gate decision, issue_type, paper-score outcome, P&L curve, provenance) |
| `mef dismiss <rec-uid> [--note]` | Mark a proposed recommendation as not-implemented |
| `mef tag <rec-uid> --provenance ...` | Override inferred activation provenance |
| `mef link-trade <rec-uid> --qty --buy-price --buy-date [--sell-...]` | Record actual buy/sell on a scored rec |
| `mef rejections [--symbol\|--since\|--limit]` | Audit table of LLM-rejected candidates with reason + issue_type |
| `mef gate-audit` | Side-by-side outcome distribution of approve / review / reject / unavailable |
| `mef score` | Re-evaluate closed recs and refresh paper + shadow scoring |
| `mef import-positions <csv>` | Ingest a Fidelity Portfolio Positions CSV |
| `mef universe [load]` | Show or reload the 305+15 universe |
| `mef report --when {premarket\|postmarket} [--run UID]` | Regenerate the email body for a run from existing DB state, no SMTP |
| `mef init-db` | Apply MEFDB + Overwatch migrations (idempotent) |

---

## Universe

MEF operates over a **fixed** universe for the foreseeable future:

- **305 US stocks** — derived from the 782-symbol focus universe by successive liquidity / market-cap / options filters (≥$20 avg close, ≥300K avg share volume, ≥$50M avg dollar volume, market cap ≥$30B, ≥2 listed-options expirations, total OI ≥500). Source of truth: `notes/focus-universe-us-stocks-final.md`.
- **15 core US ETFs** — broad market (SPY, QQQ, VTI), size (IWM), style/factor (IWD, IWF, SCHD), sectors (XLK, XLF, XLV, XLE, XLI, XLY, XLP), industry (SMH). Source of truth: `notes/core-us-etfs-daily-final.md`.

The universe is stored in MEFDB tables (`mef.universe_stock`, `mef.universe_etf`) so MEF reads it from the database at runtime, not from the markdown notes. The notes remain the human-readable source; a small loader (`mef universe load`) syncs the tables from those files when the lists change. There is no automatic refresh in v1.

Benchmarks used in scoring and relative-strength evidence come from the ETF universe itself (SPY for broad market, the seven sector XL\* ETFs for sector-relative comparisons) — **joined from SHDB at read time**. If that introduces a performance hit we'll cache into MEFDB later.

---

## Evidence Sources (v1)

All evidence comes from **SHDB** tables. No DAS, no RSE, no external API calls at decision time (apart from the LLM review call).

Representative SHDB tables MEF reads:

- `shdb.stock_price_1d` / `shdb.mart.stock_equity_daily` — price, volume
- `shdb.stock_returns_1d` — return history
- `shdb.stock_technicals_1d` — momentum / trend / volatility features
- `shdb.options_snapshot_1d` / `shdb.mart.stock_options_underlying_daily` — options OI context
- `shdb.symbol_master` — reference
- Earnings / events tables as available
- SPY and sector ETF rows in the same price/return/technicals tables for benchmark-relative features

A full SHDB-table → evidence-family map lives in `docs/mef_design_spec.md`. If an evidence family needs data SHDB doesn't have, we **exclude that family from v1** and list it as a follow-up rather than stubbing around it.

---

## Daily Workflow

Each run executes the same pipeline; only the intent (today-after-10 vs. next-trading-day) and input freshness differ.

```
 1. Open mef.daily_run (status=running) + ow.mef_run telemetry row
 2. Lifecycle sweep — expire/auto-close any recs that aged out or
    disappeared from the latest position snapshot
 3. Load universe (305 + 15 from MEFDB)
 4. Pull evidence from SHDB for the full universe
 5. Data-freshness gate — abort run if the latest mart bar is too stale
 6. Deterministic ranker produces candidates with posture + conviction
    + draft entry/stop/target plans
 7. Select top-N (conviction_threshold + max_new_ideas_per_run cap)
 8. LLM gate (Claude CLI) — 3-way disposition (approve/review/reject)
    + issue_type per candidate. See mef_llm_gate.md
 9. Insert mef.recommendation rows for approve + review + unavailable
    (reject stays on mef.candidate only)
10. Daily P&L snapshot — one mef.recommendation_pnl_daily row per
    active rec, plus close-day rows for newly-closed recs
11. Score newly-closed recs (mef.score), shadow-score rejects
    (mef.shadow_score), paper-score every emitted rec (mef.paper_score)
12. Render and send the email (direct SMTP — see Output below).
    Email shows LLM-approved + unavailable ideas as "New ideas" and
    LLM-review-tagged ideas in a separate "Held for review" section
    (with the LLM's reason visible). Rejected ideas stay MEFDB-only.
13. Close mef.daily_run (status=ok) + complete ow.mef_run with counts
```

The lifecycle sweep + audit/scoring loops run on every scheduled run, not separately — daily re-evaluation is part of every cron firing.

---

## Recommendation Lifecycle

Every recommendation moves through a small state machine. Transitions are triggered by evidence from the daily run, Fidelity CSV imports, or explicit CLI actions.

```
                 (run emits)
   proposed ────────────────► active
     │                          │
     │ (entry window closed     │ (exit / invalidation /
     │  unfilled)               │  time-exit met)
     ▼                          ▼
   expired                    closed
     │                          │
     │ (CLI: mef dismiss)       ├──► closed_win
     ▼                          ├──► closed_loss
   dismissed                    └──► closed_timeout
```

- **proposed** — emitted by a run; user has not acknowledged it.
- **active** — MEF **infers** the position became real from the next Fidelity CSV import (the user's actual holdings now include the symbol at around the proposed size). This is automatic.
- **dismissed** — user explicitly ran `mef dismiss <rec-id>` saying "I'm not going to implement this."
- **expired** — the entry window passed without the user taking the position. Auto-set by the next run after the entry deadline.
- **closed_win / closed_loss / closed_timeout** — active recommendation has been exited:
  - **closed_win** — realized profit (round-trip profitable; for short-option expressions, option expired out of the money so the premium was kept)
  - **closed_loss** — realized loss (round-trip lost money, including the case where an open position was in profit at some point but was ultimately sold at a loss)
  - **closed_timeout** — time-based exit reached without hitting target or invalidation; scored at that day's close

> **Open question on options scoring:** the original note reads "win is profitable purchase and sale, or for options purchase and expires outside the money." For **long** options, OTM expiration is a loss (premium decays to zero); for **short** options (covered calls, cash-secured puts), OTM expiration is a win (premium kept). v1 will treat short-option OTM expiration as a win (matching MEF's conservative income-oriented options use). Long-option strategies are mostly out of scope in v1 anyway. If the user intended something different, adjust here.

### How MEF knows a position is real

MEF ingests the user's Fidelity Portfolio Positions CSV daily (same mechanism and file format as IRA Guard). If a proposed recommendation's symbol shows up in the user's holdings with a quantity/price consistent with the proposed entry, MEF promotes the recommendation to `active`. If the active position later disappears from the holdings, MEF treats it as exited at the most recent known quote and closes the recommendation. Cost basis comes from the CSV when present.

### Scoring

When a recommendation closes, MEF computes:

- **outcome:** `win` / `loss` / `timeout`
- **estimated_pnl_100_shares_usd:** realized price change × 100 shares (for options, realized premium or equivalent). This is an estimate; it ignores commissions, taxes, and the user's actual share count.
- **days_held:** calendar days from `active` (or `proposed` fill date when inferred) to close
- **benchmark_return_same_window:** SPY and the relevant sector ETF over the same calendar window, for context

For real per-account P&L, run **`mef link-trade <rec-uid> --qty --buy-price --buy-date [--sell-price --sell-date]`** to overlay your actual fills on the score row. That populates `realized_pnl_usd` and the headline `realized_pnl_per_day` metric (the "max profit in shortest time" answer). Until PHDB has Fidelity transaction history wired up for automatic linking, this is the manual bridge.

The full audit data model — `mef.score`, `mef.shadow_score`, `mef.paper_score`, `mef.recommendation_pnl_daily` — is documented in **`mef_audit_model.md`**.

### Activation provenance

When MEF flips a `proposed` rec to `active` because a matching position appeared in your CSV, it stamps **how** that match happened:

- `mef_attributed` — symbol wasn't in your positions before this rec; appeared during the entry window
- `pre_existing` — symbol was already in your positions before MEF proposed it
- `independent` — position appeared after the entry window, or otherwise out-of-band

The activator infers this from the symbol's earliest position-snapshot date. `mef tag <rec-uid> --provenance ...` overrides when the inference is wrong. This lets future audits report MEF-attributed outcomes separately from ambient ones the user would have made anyway.

---

## LLM Role

MEF uses **Claude CLI (`claude -p`)** for the final-review step. The integration is built so **another LLM can be substituted later** (pluggable provider in the config).

The LLM is a **gate**, not an idea generator. It returns a 3-way disposition per candidate:

- `approve` — safe to ship as-is. Becomes a recommendation, appears in the email as "New ideas".
- `review` — not safe to auto-ship. Becomes a recommendation, shown in the email under a separate **"Held for review"** section with the LLM's one-sentence reason so the user can decide whether to act manually. Also visible via `mef recommendations --state proposed`.
- `reject` — not shipped. Audit trail on `mef.candidate.llm_gate_decision/reason/issue_type`.

Each disposition carries an `issue_type` from a small enum (`mechanical`, `risk_shape`, `volatility_mismatch`, `posture_mismatch`, `asset_structure`, `options_structure`, `missing_context`, `none`) that's server-validated against a SQL CHECK constraint.

What the LLM does **not** do:

- Generate candidates from scratch (the ranker does that)
- Decide whether "no new trades today" is the right answer (the ranker's thresholds decide that)
- Modify entry/exit prices (deterministic plan wins)
- Browse, claim current news, or invent post-cutoff events

Every LLM call is logged to `mef.llm_trace` with prompt, response, model, elapsed time, and linkage to the owning `daily_run` and candidate. The prompt design philosophy, prompt source, and iteration guide live in **`mef_llm_gate.md`**.

If the LLM call fails, MEF ships the ideas anyway tagged `unavailable` ("Not reviewed by LLM") so an Anthropic outage doesn't silence the daily email.

---

## Output

**Two emails per trading day** (pre-market and post-market), sent via **direct SMTP** (`smtplib` reading SMTP credentials from MDC's `notifications.yaml`). MEF deliberately does **not** route through MDC's `notify.py`, which forces its own subject/body wrapper that would mangle the report. Both emails always send — there is no "quiet when nothing changes" behavior. A weak-evidence day produces a short email that says so. Aside from these two scheduled emails, MEF sends **no other notifications** — no SMS, no per-event alerts, no failure pages. Operational failures surface via Overwatch and cron logs.

The email shows LLM-approved (and unavailable-fallback) ideas as "New ideas" and LLM-review-tagged ideas in a separate "Held for review" section with the LLM's one-sentence reason visible. Rejected ideas stay MEFDB-only and are visible via `mef recommendations --state proposed` and `mef rejections`.

Email body sections:

- Header: run timestamp, intent (today-after-10 / next-trading-day), universe health
- Optional staleness banner (`⚠` warn / `⛔` abort) when the data-freshness gate trips
- **New ideas** (or "No new trades today") — each with R:R block per 100 shares + reasoning. Pullback-anchored entries carry a `⏳ wait for pullback (currently ~$X)` annotation on the entry-zone line.
- **Held for review** — LLM-review-tagged ideas with full setup + LLM's one-sentence reason, so the user can decide whether to act manually
- One-line footer noting how many additional ideas were rejected (review items are rendered explicitly above, not counted in the footer)
- **Active recommendations & tracked positions** — status, guidance, revised levels
- Footer: scoring summary (recent closes), links to CLI commands for detail

Full email templates and formatting decisions live in the design spec / implementation plan.

---

## Hard Boundaries

1. **Fixed 305+15 universe.** No broad-market screening.
2. **No DAS dependency in v1.** MEF reads SHDB directly.
3. **No RSE dependency in v1.** Revisit once RSDB has useful outputs.
4. **No backtesting.** Historical strategy simulation belongs elsewhere (same line RSE draws).
5. **Advisory only.** No broker integration, no automatic orders.
6. **No notifications beyond the two daily emails.** No SMS, no per-event pings.
7. **Light before heavy.** If a design choice lets us ship the daily loop sooner at the cost of near-term elegance, ship.
8. **`mef ask`-style LLM orchestration does not belong here.** MEF is a scheduled recommender, not an inquiry tool.

---

## Why the Universe Matters

The curated 305+15 is load-bearing. A fixed, thoughtful universe:

- keeps scoring comparable over time (same tradable set every day)
- eliminates cold-start problems for new symbols
- allows the LLM-review prompt to be tuned against a stable input distribution
- reduces compute per run
- resists the "chase a random ticker" failure mode

Universe changes should be rare and deliberate. When they happen, the change is an explicit commit updating the notes files and rerunning `mef universe load`.

---

## MEFDB (Overview)

New PostgreSQL database on the shared `localhost:5432` instance, following AFT conventions:

- **Database:** `mefdb`
- **Schema:** `mef`
- **Owner:** `mef_user` (credentials stored in `config/postgres.yaml`, gitignored, following MDC/UDC/RSE/IRA Guard pattern)

Tables (full column-level schema in `docs/mef_design_spec.md` §"MEFDB Schema"; audit-table relationships in `mef_audit_model.md`):

| Table | Purpose |
|---|---|
| `mef.universe_stock` | The 305 stocks currently in universe |
| `mef.universe_etf` | The 15 ETFs currently in universe |
| `mef.daily_run` | One row per scheduled run (intent, status, timings) |
| `mef.candidate` | Per-run, per-symbol features + posture + LLM gate decision/issue_type/reason |
| `mef.recommendation` | Emitted recommendations with entry/exit plans, lifecycle state, provenance |
| `mef.recommendation_update` | Per-run updates to active recommendations (thesis-status transitions, revised levels) |
| `mef.position_snapshot` | User's holdings imported from Fidelity CSV |
| `mef.import_batch` | One row per CSV import |
| `mef.benchmark_snapshot` | Cached SPY / sector-ETF values used in scoring (joined from SHDB) |
| `mef.score` | Closed-recommendation outcomes — synthetic estimate + optional realized-trade overlay |
| `mef.shadow_score` | Forward-walked outcomes for every LLM-rejected candidate (gate falsifiability) |
| `mef.paper_score` | Forward-walked outcomes for every emitted rec (validation horizon collapse) |
| `mef.recommendation_pnl_daily` | Day-by-day MTM P&L curve over the holding period |
| `mef.llm_trace` | Every LLM call: prompt, response, model, timing, linkage |
| `mef.command_log` | CLI invocations for auditability |

Overwatch telemetry (in the existing `overwatch` database):

- `ow.mef_run` — one row per completed/failed run with full counts (gate disposition, scoring, paper/shadow, P&L snapshot, email status)
- `ow.mef_event` — discrete events (info / warning / error), including data-staleness, gate-unavailable, lifecycle sweeps, paper/shadow scoring activity

UID prefixes: `DR-` daily_run, `C-` candidate, `R-` recommendation, `U-` recommendation_update, `I-` import_batch, `P-` position_snapshot, `S-` score, `SS-` shadow_score, `PS-` paper_score, `L-` llm_trace.

---

## Build Order

The canonical, living tracker is **`mef_build_order.md`** — that file shows current status of every milestone (✅ done / ⏳ next / 🅿 parked). As of 2026-04-21, milestones 1-15 are done (full daily loop, validation infrastructure, 3-way LLM gate, provenance, daily P&L tracking, report+show polish); milestone 16 (iteration) is in active progress with a block of ranker-tuning changes shipped on 2026-04-21 — see the 2026-04-21 status note in `mef_build_order.md` for the full commit list; milestone 17 (universe management) is parked until ~3 months of scoring data exist.

---

## Legacy Context

MEF has no predecessor inside AFT. It borrows patterns from:

- **IRA Guard** — Fidelity CSV ingest, advisory-only posture, notify.py pattern
- **RSE** — documentation structure, LLM-trace logging, Overwatch telemetry pattern, strict "no backtesting" boundary
- **MDC / UDC** — CLI shape, config/secrets pattern, conventional commits, src layout

It does **not** inherit from the retired XPM tool. References should be to RSE going forward.

---

## Where to Dig Deeper

| Topic | Location |
|---|---|
| Source design notes | `notes/muse-engine-forecaster-overview.md` |
| Stock universe (305) | `notes/focus-universe-us-stocks-final.md` |
| ETF universe (15) | `notes/core-us-etfs-daily-final.md` |
| Technical design | `docs/mef_design_spec.md` |
| System-wide conventions | `~/repos/notes/conventions.md` |
| Database catalog | `~/repos/notes/databases.md` |
| Peer applications | `~/repos/notes/iraguard.md`, `~/repos/notes/rse.md` |
