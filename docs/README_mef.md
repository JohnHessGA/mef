# MEF — Muse Engine Forecaster

Version: 2026-05-21 draft (naming alignment)
Track: **Investing Track 4 — Capital Appreciation**
Status: Built and running daily; Growth Opportunity Finder v2 direction drafted; Core Pullback Radar v1 operational
Database: MEFDB — Muse Engine Forecaster Database
Repo/tool name: `mef`

---

> **Terminology note (2026-05-21).** What this doc used to call "Job 1" is
> now **Growth Opportunity Finder**. What used to be "Job 2" / "Core
> Pullback Watchlist" / "Growth Pullback Radar" is now **Core Pullback
> Radar**. The underlying code, modules, and database tables still use
> the old names (e.g. `mef.core_pullback_watchlist`) — those are tracked
> for a later rename pass but are not load-bearing on this rename.
> See `~/repos/mef/CLAUDE.md` for the canonical naming.

---

## Companion docs

This file is the high-level product and operating spec for MEF. Use the deeper docs for implementation details:

- [`mef_core_pullback_watchlist.md`](mef_core_pullback_watchlist.md) — Core Pullback Radar: deterministic DB-backed pullback monitor.
- [`mef_design_spec.md`](mef_design_spec.md) — technical architecture, schema, pipeline internals.
- [`mef_cia_future_overlay.md`](mef_cia_future_overlay.md) — future CIA congressional/insider/institutional signal overlay.

Earlier supporting docs (layered gating, LLM gate philosophy, operations
notes, audit model, cron) live under `docs/bu20260520/` while the new
spec set is being authored. Treat the code as the source of truth in the
meantime; the historical text remains for context only.

---

## Purpose

MEF serves **Investing Track 4 — Capital Appreciation.** It is a daily
advisory tool for identifying growth opportunities and maintaining
disciplined entry plans for selected high-potential assets.

MEF has two functions:

1. **Growth Opportunity Finder** — surface a small number of stocks or ETFs that appear poised for upside and are attractive enough to consider buying now or very near now. Where the setup is good but current price is poor, classify as **wait for entry** instead of forcing the idea into Actionable.
2. **Core Pullback Radar** — continuously monitor selected ETFs and stocks for meaningful pullbacks and raise visibility when they approach practical buy zones.

MEF is advisory only. It never places trades, sends broker instructions, or treats any recommendation as automatic. The primary user surface is the `mef` CLI, especially `mef status`.

---

## What MEF is not

MEF is **not** the covered-call or cash-secured-put recommendation engine.
Options-income workflows belong to **CCW** (`~/repos/ccw/`). New MEF
work should not extend MEF into income-track decisioning — route that to
CCW. Defensive stop-loss work on existing holdings belongs to **IRA
Guard**; plain-English ad-hoc market research belongs to **RSE**.

---

## Why MEF Exists

AFT already has several focused tools:

- **MDC / UDC** — collect and curate market data.
- **RSE** — answer user-initiated research questions.
- **IRA Guard** — protect and monitor existing holdings.
- **CCW** — covered-call and cash-secured-put income planning.
- **CIA** — congressional, insider, institutional, and whale activity leads.

MEF fills the proactive **capital-appreciation** gap:

- It looks for new growth opportunities.
- It monitors prior MEF recommendations.
- It tracks whether emitted ideas worked.
- It provides daily visibility into pullbacks on high-interest growth assets.

The key v2 correction is this:

> MEF should not confuse a strong asset with an attractive entry.

A stock or ETF can be excellent and still be too extended to buy today.
In that case, MEF should classify it as **wait for entry** (good setup,
the entry hasn't formed yet) or as a pullback candidate, rather than
forcing it into Actionable Stock Ideas. "No buyable ideas today" is a
valid and healthy output.

---

## Design Attitude

- **Deterministic first.** Core investment-status decisions should be made in Python from auditable data.
- **No forced trades.** "No buyable ideas today" is a valid and healthy output.
- **Entry-aware.** MEF should care not only whether a stock is good, but whether today's price offers acceptable risk/reward. "Wait for entry" is a first-class concept.
- **Deterministic plan quality can override LLM approval.** The LLM is optional context; it does not own actionability. A weak plan stays out of Actionable even when the LLM approves.
- **Separate functions, separate logic.** Growth Opportunity Finder (opportunistic ranking) and Core Pullback Radar (standing pullback monitoring) are related but not the same thing.
- **LLM as optional context, not control.** The LLM may help review or explain some outputs, but it should not create symbols, alter buy levels, or override deterministic pullback status.
- **Keep the CLI simple.** Prefer a small number of useful commands and human-readable output.
- **Document as we build.** MEF docs should stay aligned with code changes.

---

## Growth Opportunity Finder

This is the existing MEF idea engine (previously called "Job 1" or
"Opportunistic Growth Ideas"), with a v2 goal reset.

### Goal

Find stocks or ETFs that appear poised for upside and decide whether the
setup is worth acting on now. When the setup is good but the entry is
not, route to **wait for entry** rather than forcing the idea into
Actionable.

### Desired output categories

- **Actionable Stock Ideas** — candidates that are reasonably **buyable now** or close to now.
- **Watch / Wait for Entry** — good assets or setups where current price is not attractive; a better entry would make the plan acceptable.
- **Watch / Not Actionable** (held for review, poor entry quality, etc.) — interesting but borderline or incomplete candidates; also any LLM-approved candidate the deterministic plan-quality check demoted.
- **Not Actionable Today** — weak, conflicted, event-blocked, extended, or poor risk/reward candidates.
- **No buyable ideas today** — valid result.

### Current flow

The current v1 pipeline is:

1. Load the fixed MEF stock and ETF universe.
2. Pull SHDB evidence.
3. Apply Layer A eligibility.
4. Score with deterministic engines:
   - trend
   - mean reversion
   - value
5. Apply Layer B hazard overlay.
6. Select per-engine top-N candidates.
7. Deduplicate candidates for LLM review.
8. LLM gate returns approve / review / reject / unavailable.
9. Entry Quality Overlay (deterministic) may demote LLM-approved candidates with weak plans.
10. Surviving approved + good-plan ideas render as Actionable Stock Ideas.
11. Demoted, review, and unavailable items render in Watch / Not Actionable.
12. Rejected items stay audit-only.

### v2 direction (research complete; implementation pending)

Growth Opportunity Finder should become more **plan-quality-aware**:

- Identify setup family at scoring time.
- Construct a chart-structure-aware plan (swing-low stops, prior-high targets, volatility-aware bands) rather than a fixed-percentage skeleton.
- Classify each plan as **buyable now / wait for entry / no compelling plan**.
- **Deterministic plan quality can override LLM approval.** A weak plan does not ship as Actionable even when the LLM says approve.
- **Model B (structural plan construction)** is the leading future candidate based on the plan-construction model comparison; see `scripts/research/mef_plan_geometry_compare.py` and `/mnt/aftdata/rse/data/mef_plan_geometry/summary.md`. **Not yet implemented.**
- MEF can return zero actionable ideas without apology.

---

## Core Pullback Radar

Previously called "Job 2" or "Core Pullback Watchlist". The function is
unchanged; only the name aligns with the wider track terminology.

### Goal

Monitor selected ETFs and stocks every day and raise visibility when a meaningful pullback may create a practical buying opportunity.

This is not a normal top-N ranker. It is a standing monitor.

### Core idea

MEF should answer:

> Has this asset pulled back enough to be interesting, while still looking healthy enough that the pullback may be an opportunity rather than a breakdown?

### v1 behavior

The v1 Core Pullback Radar is deterministic, written in Python, and DB-backed.

It should not use the LLM in the buy-zone calculation, pullback status, or visibility decision.

It should calculate:

- current price,
- pullback from recent highs,
- trend health,
- stabilization,
- volatility-adjusted buy levels,
- risk/reward back to recent highs,
- event or macro caution where available,
- display status.

### Status vocabulary

Internal status values:

- `NO_PULLBACK`
- `PULLBACK_FORMING`
- `BUY_ZONE_ACTIVE`
- `DEEP_PULLBACK_OPPORTUNITY`
- `FALLING_KNIFE_WAIT`
- `THESIS_BROKEN_REVIEW`

Human labels:

- No meaningful pullback yet
- Pullback forming
- Buy zone active
- Deep pullback opportunity
- Falling knife — wait
- Thesis/risk changed — review before buying

### Watchlist universe

Operational symbol lists live in MEFDB (`mef.core_pullback_watchlist`,
seeded by `sql/mefdb/013_core_pullback_watchlist.sql`). The list below
is the human-readable summary of that table:

**ETFs — 10**

- SPY
- QQQ
- VTI
- ONEQ
- IWM
- SCHG
- VUG
- XLK
- SMH
- SCHD

**Stocks — 50**

- NVDA
- MSFT
- GOOGL
- AMZN
- META
- AAPL
- AVGO
- LLY
- COST
- NFLX
- ORCL
- AMD
- JPM
- BRK.B
- UNH
- ISRG
- ADBE
- INTU
- ASML
- TSM
- CRM
- NOW
- PANW
- CRWD
- UBER
- SHOP
- LIN
- TSLA
- INTC
- PLTR
- ARM
- MU
- SNOW
- DDOG
- NET
- MDB
- RBLX
- COIN
- HOOD
- SOFI
- SMCI
- DELL
- APP
- ANET
- VRT
- CAVA
- CELH
- TTD
- ENPH
- NVO

### Tier handling

The watchlist should preserve tier context because not all symbols deserve the same standard.

- **Tier 1 — Core market / growth ETFs**
- **Tier 2 — Elite compounders / dominant growth leaders**
- **Tier 3 — Quality growth / durable leaders**
- **Tier 4 — Volatile growth / special situations**

Tier 4 symbols can still be attractive after pullbacks, but they should require deeper discounts and better stabilization than ETFs or elite compounders.

See `mef_core_pullback_watchlist.md` for the canonical Core Pullback Radar design.

---

## LLM Role

The LLM is not involved in Core Pullback Radar v1.

For the Growth Opportunity Finder candidate-review flow, the LLM remains
a conservative reviewer. It can approve, hold for review, reject, or be
unavailable. It must not generate candidates, change prices, or alter
conviction / posture / stops / targets / time exits. Crucially, **LLM
approval does not by itself put a candidate into Actionable Stock Ideas**
— the deterministic Entry Quality Overlay (and any future plan-quality
check) can demote an LLM-approved candidate to Watch / Not Actionable
when the plan geometry is weak.

Future LLM use may include sentiment or qualitative context, but only as an annotation layer. It must not:

- create symbols,
- alter buy levels,
- override deterministic pullback status,
- upgrade a weak pullback into a buy,
- silently suppress a deterministic alert.

---

## CIA Future Overlay

CIA tracks congressional, insider, institutional, and whale activity as advisory leads.

MEF may eventually use CIA as a support/caution overlay, for example:

- supportive CIA buy lead on a symbol already in a MEF buy zone,
- caution note when CIA shows meaningful sell-side activity,
- actor-edge context for symbols already surfaced by MEF.

CIA should not be a primary MEF buy engine. CIA data may support, caution, or explain a MEF opportunity, but it must not independently create a buy recommendation or override deterministic pullback/trend logic.

See `mef_cia_future_overlay.md`.

---

## User Experience

The main user surface is:

```bash
mef status
```

The status report should eventually show:

1. **Actionable Stock Ideas** — buyable now / near now (Growth Opportunity Finder).
2. **Watch / Wait for Entry** — good ideas where entry is not attractive yet (Growth Opportunity Finder).
3. **Watch / Not Actionable** — other held / poor-plan / unreviewed candidates.
4. **Core Pullback Radar** — notable pullback statuses from the configured 10 ETF + 50 stock watchlist.
5. **Active Recommendations & Tracked Positions** — current lifecycle/guidance view.
6. **Operational notes** — stale data, run health, LLM gate availability when relevant.

The default report should not dump all 60 Core Pullback Radar symbols every day. It should surface notable items and summarize quiet counts.

Example:

```text
CORE PULLBACK RADAR
Buy zone active:
  SPY — starter buy zone active; long-term trend intact
  MSFT — pullback has reached starter visibility level

Pullback forming:
  QQQ — approaching starter visibility level
  NVDA — meaningful pullback underway, still above preferred entry

Falling knife / wait:
  INTC — pullback large enough to notice, but stabilization not confirmed

Quiet:
  52 symbols with no meaningful pullback today
```

---

## CLI Surface

The active CLI surface should remain small:

| Command | Purpose |
|---|---|
| `mef` | Defaults to `mef status` |
| `mef status` | Main investing report |
| `mef run` | Execute pipeline; no email by default |
| `mef run --send-email` | Execute pipeline and send the daily email |
| `mef health` | Operator dashboard |
| `mef universe` | Display current Growth Opportunity Finder universe (read-only) |
| `mef init-db` | Apply MEFDB and Overwatch migrations (idempotent) |

MEF has a **single run behavior**. Scheduling decides when a run fires;
the tool does not branch on whether it was nominally premarket or
postmarket. The cron aliases `premarket-run` / `postmarket-run` still
exist as deprecated compatibility wrappers that print a deprecation
notice and dispatch to the same code path as `mef run --send-email`.

Avoid adding many flags. For Core Pullback Radar, prefer showing a useful default in `mef status` before creating new subcommands.

A future detail view may be useful, but should be added only if the default report becomes too crowded.

---

## Data Sources

MEF reads SHDB for market data and event data. Representative evidence families include:

- price and volume,
- returns,
- technicals,
- moving averages,
- RSI,
- MACD,
- realized volatility,
- ATR,
- drawdown/current position versus recent highs,
- benchmark-relative strength,
- sector context,
- earnings calendar,
- macro event context.

Core Pullback Radar should reuse SHDB evidence where possible. If a required field is missing, the deterministic status should degrade gracefully and explain the missing data rather than guessing.

---

## Persistence

All MEF persistence lives in MEFDB under schema `mef`.

This includes both reference data and computed state:

- **Reference data** (operator-curated, seeded by SQL migrations):
  - `mef.universe_stock`, `mef.universe_etf` — the Growth Opportunity Finder 305+20 universe
  - `mef.core_pullback_tier`, `mef.core_pullback_watchlist` — the Core Pullback Radar tier reference and 10+50 watchlist (added 2026-05-20)
- **Computed state** (written by runs):
  - `mef.daily_run`, `mef.candidate`, `mef.recommendation`, `mef.recommendation_update`
  - `mef.score`, `mef.shadow_score`, `mef.paper_score`
  - `mef.llm_trace`, `mef.command_log`
  - `mef.core_pullback_snapshot` — one row per run per pullback-watchlist symbol (empty until the engine lands)

**Rule:** operational symbol lists (universes, watchlists) live in MEFDB.
Config YAML holds settings only. Documentation files in `docs/` explain
the lists but never feed them into the tool. The legacy markdown-loader
path was removed 2026-05-20.

If pullback persistence proves overkill in practice, the
`core_pullback_snapshot` table can be left mostly empty (or dropped in a
future migration) without affecting the Growth Opportunity Finder. The
watchlist and tier tables are required because the engine reads from
them every run.

---

## Output Principles

MEF output should be human-readable and decision-support oriented.

Preferred language:

- "Buy zone active"
- "Pullback forming"
- "Wait for entry"
- "Wait for stabilization"
- "No buyable ideas today"
- "Strong asset, poor entry"
- "Visibility raised"

Avoid language that sounds like certainty:

- "Guaranteed rebound"
- "Must buy"
- "Perfect entry"
- "Bottom is in"

MEF should raise visibility, not create pressure.

---

## Hard Boundaries

1. Advisory only.
2. No trade execution.
3. No broker integration.
4. MEF is **not** the covered-call / cash-secured-put recommendation engine — those belong to CCW.
5. No broad-market uncontrolled screening for Core Pullback Radar v1.
6. No LLM in Core Pullback Radar v1 decisions.
7. CIA is future context only, not a current dependency.
8. Do not force daily ideas. "No buyable ideas today" is a healthy outcome.
9. Do not treat an all-time high as automatically actionable.
10. Do not treat a large pullback as automatically buyable.
11. Operational symbol lists live in MEFDB — never in markdown / docs / notes / YAML.
12. Keep documentation aligned with behavior.

---

## Build Direction

Core Pullback Radar v1 is built and rendered in `mef status` (DB-backed
watchlist, deterministic statuses, notable subset + quiet count). Future
sequencing:

1. ~~Finalize docs for Core Pullback Radar.~~ Done.
2. ~~Migrate watchlist + tier metadata into MEFDB.~~ Done (mig 013).
3. ~~Implement deterministic pullback-status calculator.~~ Done.
4. ~~Render notable pullback statuses in `mef status`.~~ Done.
5. ~~Tests for tiers, thresholds, statuses, and quiet/no-alert behavior.~~ Done.
6. **Next: Growth Opportunity Finder v2 plan-construction work** — Model B (structural swing-low / prior-high) per `scripts/research/mef_plan_geometry_compare.py`; add `wait_for_entry` routing. Not yet implemented.
7. Later consider LLM sentiment/context and CIA overlay.

---

## Legacy / Current-State Notes

MEF v1 shipped quickly as a deterministic ranker plus LLM-reviewed recommendation stream. That remains useful, but the v2 design recognizes a major limitation: strong-trend scoring can accidentally reward assets that have already moved too far, and the legacy fixed-percentage plan builder mechanically produces ~1.5 R/R regardless of the symbol.

The v2 correction is not to discard MEF. It is to (1) make the Growth Opportunity Finder more plan-quality-aware (structural plan construction, "wait for entry" as a first-class concept, deterministic plan quality can override LLM approval), and (2) keep the Core Pullback Radar as a separate standing monitor for assets where the user wants disciplined visibility during selloffs.

