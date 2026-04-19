# MEF — Muse Engine Forecaster

Version: 2026-04-19
Status: Initial build specification
Database: MEFDB — Muse Engine Forecaster Database
Repo/tool name: `mef`

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
- LLM final-review pass (Claude CLI) over the deterministic ranker's top candidates
- **Active-position tracking:**
  - Infer user's actual holdings from daily Fidelity Positions CSV ingest (same pattern as IRA Guard)
  - Track every MEF recommendation through its lifecycle (see §"Recommendation Lifecycle")
- **Two daily emails** (via MDC's `notify.py --source MEF`) containing current status and recommendations — no other notifications
- CLI for operator use (run, status, list recommendations, mark dismissed, inspect, score)
- Scoring: win / loss / timeout per closed recommendation, with estimated $ P&L for 100 shares
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

Minimal surface (detail in `docs/mef_cli.md`, to be written alongside initial implementation):

| Command | Purpose |
|---|---|
| `mef run --when {premarket\|postmarket}` | Execute one scheduled run (entry point for cron) |
| `mef status` | Environment, data freshness, last run, active recs, tracked positions |
| `mef recommendations [--active\|--all\|--since <date>]` | List recommendations with lifecycle state |
| `mef show <rec-id>` | Full detail on a recommendation (evidence, plan, history) |
| `mef dismiss <rec-id>` | Mark a proposed recommendation as not-implemented |
| `mef import-positions <csv>` | Ingest a Fidelity Portfolio Positions CSV |
| `mef score` | Re-evaluate closed recommendations and update scoring |
| `mef universe` | Show current stock + ETF universe (and filter criteria) |
| `mef report --when {premarket\|postmarket}` | Regenerate and preview the email report without sending |

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
1. Load universe (305 + 15 from MEFDB)
2. Pull evidence from SHDB for the full universe
3. Compute per-symbol features and a directional posture
4. Deterministic ranker produces candidate list with draft entry/exit plans
5. LLM final review (Claude CLI) — sanity-check top candidates, add color,
   flag any that don't make sense
6. Finalize new-ideas list (may be empty → "no new trades today")
7. Re-evaluate every active recommendation and tracked position
   (thesis status, exit / invalidation checks, lifecycle transitions)
8. Persist: daily_run, candidates, recommendations, updates, llm_trace
9. Generate and send the email (notify.py --source MEF)
10. Write telemetry to ow.mef_run / ow.mef_event
```

Step 7 is important: the daily re-evaluation is not separate from idea generation — it's part of every run.

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

Later, once IRA Guard/PHDB data is integrated, MEF can replace the 100-share estimate with the user's **actual** realized dollar change. That's a v2 concern.

---

## LLM Role

MEF uses **Claude CLI (`claude -p`)** for the final-review step. The integration is built so **another LLM can be substituted later** (pluggable provider in the config).

What the LLM does:

- Reviews the deterministic ranker's top candidates and any active-position changes
- Adds context and color (market backdrop, recent news relevance, conflict between signals, caveats)
- Flags candidates whose plan doesn't make sense given the LLM's broader knowledge
- Produces the short reasoning summary for each idea that appears in the email

What the LLM does **not** do:

- Generate candidates from scratch (the ranker does that)
- Decide whether "no new trades today" is the right answer (the ranker's thresholds decide that)
- Modify entry/exit prices (deterministic plan wins)

Every LLM call is logged to `mef.llm_trace` with prompt, response, model, elapsed time, and linkage to the owning `daily_run` and candidate. The prompt itself will be iterated on; v1 ships with a plain-English prompt asking the LLM, *"Given these candidates and this supporting evidence, do our assumptions and plans make sense? Flag anything that looks wrong, add context a thoughtful analyst would add."*

---

## Output

**Two emails per trading day** (pre-market and post-market), sent via MDC's `notify.py --source MEF`. Both emails always send — there is no "quiet when nothing changes" behavior. A weak-evidence day produces a short email that says so. Aside from these two scheduled emails, MEF sends **no other notifications** — no SMS, no per-event alerts, no failure pages. Operational failures surface via Overwatch and cron logs.

Email body sections:

- Header: run timestamp, intent (today-after-10 / next-trading-day), universe health
- **New ideas** (or "No new trades today")
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

Conceptual v1 tables (full column-level schema in `docs/mef_design_spec.md` §"MEFDB Schema"):

| Table | Purpose |
|---|---|
| `mef.universe_stock` | The 305 stocks currently in universe |
| `mef.universe_etf` | The 15 ETFs currently in universe |
| `mef.daily_run` | One row per scheduled run (intent, status, timings) |
| `mef.candidate` | Per-run, per-symbol features + directional posture + score |
| `mef.recommendation` | Emitted recommendations with entry/exit plans and lifecycle state |
| `mef.recommendation_update` | Per-run updates to active recommendations (thesis-status transitions, revised levels) |
| `mef.position_snapshot` | User's holdings imported from Fidelity CSV |
| `mef.import_batch` | One row per CSV import |
| `mef.benchmark_snapshot` | Cached SPY / sector-ETF values used in scoring (joined from SHDB) |
| `mef.score` | Closed-recommendation outcomes and estimated P&L |
| `mef.llm_trace` | Every LLM call: prompt, response, model, timing, linkage |
| `mef.command_log` | CLI invocations for auditability |

Overwatch telemetry (in the existing `overwatch` database):

- `ow.mef_run` — one row per completed/failed run
- `ow.mef_event` — discrete events (info / warning / error)

UID prefixes (to be confirmed during implementation): `DR-` daily_run, `C-` candidate, `R-` recommendation, `I-` import_batch, `P-` position_snapshot, `S-` score, `L-` llm_trace.

---

## Build Order

Sequenced so the daily loop is runnable as early as possible; depth follows shape.

- **Repo & database setup** — `~/repos/mef/` skeleton (Python 3.12, src layout, `pyproject.toml`, venv, config), MEFDB + `mef_user`, minimal schema migration, `mef status` command
- **Universe load** — `mef universe load` syncs `universe_stock` / `universe_etf` from the notes files; `mef universe` shows current state
- **Skeleton daily run** — `mef run --when {premarket|postmarket}` executes end-to-end with a dummy ranker that always emits "no new trades today," writes a `daily_run` row, and sends the email. Establishes cron, telemetry, email plumbing before real scoring.
- **Evidence & ranker v0** — simple deterministic ranker using a small evidence set (trend + momentum + volatility + SPY-relative) producing ranked candidates with draft plans
- **LLM review** — Claude CLI integration, `llm_trace` logging, prompt template, review pass over top candidates
- **Position tracking** — `mef import-positions`, `position_snapshot`, `import_batch`, inference of `active` recommendations from holdings
- **Recommendation lifecycle** — `mef dismiss`, auto-expiration, auto-close detection, `mef show`, `mef recommendations`
- **Scoring** — `mef score`, `score` table, benchmark comparisons
- **Email polish** — real two-section email body with new ideas + active-position updates
- **Iterate** — evidence families, ranker weights, LLM prompt, email formatting

The list continues past this milestone; items above are the path to a **working, usable-for-testing daily loop**.

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
