# MEF — Muse Engine Forecaster

Version: 2026-05-20 draft
Status: Built and running daily; v2 pullback-watchlist design drafted
Database: MEFDB — Muse Engine Forecaster Database
Repo/tool name: `mef`

---

## Companion docs

This file is the high-level product and operating spec for MEF. Use the deeper docs for implementation details:

- [`mef_core_pullback_watchlist.md`](mef_core_pullback_watchlist.md) — MEF Job 2: deterministic growth pullback radar / buy-zone visibility.
- [`mef_design_spec.md`](mef_design_spec.md) — technical architecture, schema, pipeline internals.
- [`mef_layered_gating.md`](mef_layered_gating.md) — current deterministic gate model for the existing idea engine.
- [`mef_llm_gate.md`](mef_llm_gate.md) — LLM gate philosophy and boundaries for the existing candidate-review flow.
- [`mef_operations.md`](mef_operations.md) — day-to-day CLI operations.
- [`mef_audit_model.md`](mef_audit_model.md) — recommendation, paper, shadow, and outcome scoring.
- [`mef_cron.md`](mef_cron.md) — cron setup and operating notes.
- [`mef_cia_future_overlay.md`](mef_cia_future_overlay.md) — future CIA congressional/insider/institutional signal overlay.

---

## Purpose

MEF is a daily advisory tool for identifying buyable growth opportunities and maintaining disciplined entry plans for selected high-potential assets.

MEF has two primary jobs:

1. **Opportunistic Growth Ideas** — surface a small number of stocks or ETFs that appear poised for upside and are attractive enough to consider buying now or very near now.
2. **Core Pullback Watchlist / Growth Pullback Radar** — continuously monitor selected ETFs and stocks for meaningful pullbacks and raise visibility when they approach practical buy zones.

MEF is advisory only. It never places trades, sends broker instructions, or treats any recommendation as automatic. The primary user surface is the `mef` CLI, especially `mef status`.

---

## Why MEF Exists

AFT already has several focused tools:

- **MDC / UDC** — collect and curate market data.
- **RSE** — answer user-initiated research questions.
- **IRA Guard** — protect and monitor existing holdings.
- **CCW** — covered-call and cash-secured-put income planning.
- **CIA** — congressional, insider, institutional, and whale activity leads.

MEF fills the proactive investing-ideas gap:

- It looks for new opportunities.
- It monitors prior MEF recommendations.
- It tracks whether emitted ideas worked.
- It provides daily visibility into pullbacks on high-interest growth assets.

The key v2 correction is this:

> MEF should not confuse a strong asset with an attractive entry.

A stock or ETF can be excellent and still be too extended to buy today. In that case, MEF should classify it as a watch or pullback candidate rather than forcing it into Actionable Stock Ideas.

---

## Design Attitude

- **Deterministic first.** Core investment-status decisions should be made in Python from auditable data.
- **No forced trades.** "No new buys today" is a valid and healthy output.
- **Entry-aware.** MEF should care not only whether a stock is good, but whether today's price offers acceptable risk/reward.
- **Separate jobs, separate logic.** Opportunistic ranking and standing pullback monitoring are related but not the same thing.
- **LLM as optional context, not control.** The LLM may help review or explain some outputs, but it should not create symbols, alter buy levels, or override deterministic pullback status.
- **Keep the CLI simple.** Prefer a small number of useful commands and human-readable output.
- **Document as we build.** MEF docs should stay aligned with code changes.

---

## Job 1 — Opportunistic Growth Ideas

This is the existing MEF idea engine, with a v2 goal reset.

### Goal

Find stocks or ETFs that appear poised for upside and are attractive enough to consider buying now or very near now.

### Desired output categories

- **Actionable Stock Ideas** — candidates that are reasonably buyable now or close to now.
- **Watch for Entry** — good assets or setups where current price is not attractive.
- **Held for Review** — interesting but borderline or incomplete candidates.
- **Not Actionable Today** — weak, conflicted, event-blocked, extended, or poor risk/reward candidates.
- **No approved new ideas today** — valid result.

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
9. Approved ideas render as New Ideas / Actionable Stock Ideas.
10. Review items render in a watch/review section.
11. Rejected items stay audit-only.

### v2 direction

Job 1 should become more entry-aware. It should penalize or demote assets that are already extended, even if their trend is strong.

Future work should add an actionability or entry-quality layer so that:

- strong but stretched names move to Watch for Entry,
- current buy ideas require acceptable entry quality,
- poor risk/reward names do not ship as actionable,
- MEF can return zero actionable ideas without apology.

---

## Job 2 — Core Pullback Watchlist / Growth Pullback Radar

Job 2 is new.

### Goal

Monitor selected ETFs and stocks every day and raise visibility when a meaningful pullback may create a practical buying opportunity.

This is not a normal top-N ranker. It is a standing monitor.

### Core idea

MEF should answer:

> Has this asset pulled back enough to be interesting, while still looking healthy enough that the pullback may be an opportunity rather than a breakdown?

### v1 behavior

The v1 Core Pullback Watchlist should be deterministic and written in Python.

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

The starting Job 2 universe is:

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

See `mef_core_pullback_watchlist.md` for the canonical Job 2 design.

---

## LLM Role

The LLM is not involved in Core Pullback Watchlist v1.

For the existing Job 1 candidate-review flow, the LLM remains a conservative reviewer. It can approve, hold for review, reject, or be unavailable. It should not generate candidates or change prices, conviction, posture, stops, targets, or time exits.

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

1. **Actionable Stock Ideas** — buyable now / near now.
2. **Watch for Entry** — good ideas where entry is not attractive yet.
3. **Core Pullback Watchlist** — notable pullback statuses from the configured 10 ETF + 50 stock Job 2 universe.
4. **Active Recommendations & Tracked Positions** — current lifecycle/guidance view.
5. **Operational notes** — stale data, run health, LLM gate availability when relevant.

The default report should not dump all 60 Job 2 symbols every day. It should surface notable items and summarize quiet counts.

Example:

```text
CORE PULLBACK WATCHLIST
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
| `mef` | Print help |
| `mef status` | Main investing report |
| `mef run` | Execute pipeline; no email by default |
| `mef run --send-email` | Execute pipeline and send optional email |
| `mef health` | Operator dashboard |
| `mef universe` | Display current MEF universes |

Avoid adding many flags. For Job 2, prefer showing a useful default in `mef status` before creating new subcommands.

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

Job 2 should reuse SHDB evidence where possible. If a required field is missing, the deterministic status should degrade gracefully and explain the missing data rather than guessing.

---

## Persistence

Current MEF persistence lives in MEFDB under schema `mef`.

The existing tables track daily runs, candidates, recommendations, recommendation updates, scores, paper scores, shadow scores, LLM traces, command logs, and related state.

Job 2 may initially be computed at runtime for `mef status`. If persistence is added, it should be small and audit-oriented, such as:

- one pullback snapshot per run and symbol,
- status,
- buy levels,
- key measurements,
- reasons,
- visibility flag.

Do not create heavy schema until the runtime output proves useful.

---

## Output Principles

MEF output should be human-readable and decision-support oriented.

Preferred language:

- "Buy zone active"
- "Pullback forming"
- "Wait for stabilization"
- "No approved new ideas today"
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
4. No broad-market uncontrolled screening for Job 2 v1.
5. No LLM in Core Pullback Watchlist v1 decisions.
6. CIA is future context only, not a current dependency.
7. Do not force daily ideas.
8. Do not treat an all-time high as automatically actionable.
9. Do not treat a large pullback as automatically buyable.
10. Keep documentation aligned with behavior.

---

## Build Direction

Recommended sequence:

1. Finalize docs for the Job 2 pullback watchlist.
2. Add config-driven Job 2 universe.
3. Implement deterministic pullback-status calculator.
4. Render notable pullback statuses in `mef status`.
5. Add tests for tiers, thresholds, statuses, and quiet/no-alert behavior.
6. Evaluate daily output before adding persistence.
7. Later consider LLM sentiment/context and CIA overlay.

---

## Legacy / Current-State Notes

MEF v1 shipped quickly as a deterministic ranker plus LLM-reviewed recommendation stream. That remains useful, but the v2 design recognizes a major limitation: strong-trend scoring can accidentally reward assets that have already moved too far.

The v2 correction is not to discard MEF. It is to make MEF more entry-aware and to add a separate pullback radar for assets where the user wants disciplined visibility during selloffs.

