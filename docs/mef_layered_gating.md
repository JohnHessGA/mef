# MEF Layered Gating

Canonical reference for how MEF decides whether a symbol becomes an
emitted recommendation. As of 2026-04-21 the ranker is split into three
explicit layers. This doc is the single source of truth — when the
design spec and this doc disagree, this doc wins.

## The three layers

```
Universe symbol
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│ Layer A — Eligibility (mef.eligibility)                 │
│   "Should MEF consider this symbol today?"              │
│   - universe membership (enforced upstream in evidence) │
│   - data presence (row exists, close not null)          │
│   - earnings blackout (per-engine window)               │
└─────────────────────────────────────────────────────────┘
   │ pass
   ▼
┌─────────────────────────────────────────────────────────┐
│ Layer C — Engine thesis (mef.ranker :: _score_*)        │
│   "Does this engine see its setup here?"                │
│   Produces raw_conviction + posture from pure signals.  │
│   Value engine owns the FCF hard veto (thesis-level).   │
│   Trend keeps soft PE / earnings-yield penalties.       │
│   If raw_conviction < 0.40 → posture = no_edge, stop.   │
└─────────────────────────────────────────────────────────┘
   │ emittable posture
   ▼
┌─────────────────────────────────────────────────────────┐
│ Layer B — Hazard overlay (mef.hazard_overlay)           │
│   "Is today's environment risky enough to reduce        │
│    act-today conviction?"                               │
│   Families: macro, earnings_proximity.                  │
│   final_conviction = max(0, raw - hazard_total)         │
└─────────────────────────────────────────────────────────┘
   │
   ▼
Emission gate (final_conviction >= conviction_threshold)
   │
   ├── selected_pre_llm=True  → per-engine top-N → merge_for_llm → LLM gate
   └── suppressed_by_hazard=True (raw>=threshold, final<threshold, overlay>0)
                                → persisted, shadow-scored
```

The engine scorers know nothing about macro events or earnings
blackouts — those concerns live in Layers A and B. This separation is
what lets audit queries distinguish a weak thesis from a real thesis
silenced by today's tape.

## Layer A — Eligibility

Layer A is intentionally narrow. It only rejects symbols that are
untrustworthy or outside MEF policy. It does **not** judge trade
quality, and it does **not** account for environmental risk.

### Current rules

| Rule                              | Scope              | Notes                                    |
|-----------------------------------|--------------------|------------------------------------------|
| Universe membership               | All engines        | Enforced in `evidence._fetch_universe_symbols` |
| Data presence (row + close)       | All engines        | Missing evidence → `no_edge` + fail      |
| Earnings blackout — 5 calendar d  | `trend`            | `next_earnings_date` ≤ 5d from bar_date |
| Earnings blackout — 10 calendar d | `mean_reversion`   | Same, 10d window                         |
| Earnings blackout — 10 calendar d | `value`            | Same, 10d window                         |

Windows are per-engine because the pre-layering scorers used these
exact values. Phase 1 preserved them verbatim so we could ship the
structural split without a behavioral change to Layer A.

### Reserved for future Layer A rules

Liquidity floors and hard distress / restructuring flags belong in
Layer A conceptually, but MEF's universe is already curated so those
rules have no current failures to guard against. They are reserved —
not implemented — until a concrete case arrives.

## Layer B — Hazard overlay

Layer B is **penalty-only**. It never vetoes a thesis. It only reduces
the conviction MEF acts on *today*. If the hazard lifts tomorrow, the
same thesis resurfaces without re-running Layer C.

### Families (Phase 2)

#### macro

High-impact US macro release today or tomorrow.

```
penalty = base_event[event_type] × symbol_multiplier × engine_multiplier
```

Only the four `base_event` values are tunable. `symbol_multiplier` and
`engine_multiplier` are **derived** from existing data and must not be
treated as free parameters.

**Tunable (config: `ranker.hazard_overlay.macro.base`)**

| Event                 | Base |
|-----------------------|-----:|
| FOMC / Fed decision   | 0.07 |
| CPI / Core CPI        | 0.06 |
| PCE / Core PCE        | 0.06 |
| Nonfarm Payrolls      | 0.05 |
| Other high-impact     | 0.03 |

"Other" includes GDP, ISM, Retail Sales, Durable Goods, PPI, Consumer
Confidence. Anything not explicitly listed falls through to `other`
(not to zero) — keeps the `other` bucket from becoming a silent
no-op.

**Derived — symbol sensitivity (config: `ranker.hazard_overlay.macro.symbol_multipliers`)**

| Bucket           | Multiplier | Members                                          |
|------------------|-----------:|--------------------------------------------------|
| `broad_index`    |       1.25 | SPY, QQQ, IWM, DIA                               |
| `rate_sensitive` |       1.15 | XLF, XLU, XLRE; Financial Services / Utilities / Real Estate sectors; homebuilder industries |
| `defensive`      |       0.85 | XLP, XLV; Consumer Defensive / Healthcare sectors |
| `default`        |       1.00 | Everything else                                   |

**Derived — engine sensitivity (config: `ranker.hazard_overlay.macro.engine_multipliers`)**

| Engine           | Horizon | Multiplier |
|------------------|--------:|-----------:|
| `trend`          |     30d |       1.00 |
| `mean_reversion` |     30d |       1.00 |
| `value`          |     60d |       0.60 |

Value's 60-day horizon absorbs 1-day macro shocks; a short-term
disruption matters less to a patient thesis.

**Multiple events same window.** Take the MAX applicable penalty.
Never sum events within a family — that creates jumpy overlays on
FOMC days where CPI also prints.

#### earnings_proximity (trend only)

The 6–21 day earnings band used to be mixed soft penalties inside the
trend scorer. It is now a Layer B hazard. Mean-reversion and value
block 0–10d at Layer A, so they never enter this band.

**Tunable (config: `ranker.hazard_overlay.earnings_proximity.trend`)**

| Band       | Penalty |
|------------|--------:|
| 6–10 days  |    0.08 |
| 11–21 days |    0.03 |

### Combination rule

- **Within a family**: take the MAX applicable penalty. Events
  substitute for each other inside the same family.
- **Across families**: SUM. Macro and earnings-proximity measure
  different risks; they stack.
- **Cap**: total clamped at `hazard_overlay.cap` (default 0.10). A
  note is added when the cap binds so audit can identify capped runs.

## Raw vs final conviction

Two distinct conviction numbers, two distinct questions:

| Field              | Question                                                  | Gate that reads it |
|--------------------|-----------------------------------------------------------|--------------------|
| `raw_conviction`   | Does the engine see a thesis here?                        | `no_edge` (`< 0.40`) |
| `conviction_score` | Should MEF act on this today? (raw minus hazard overlay)  | emission (`>= 0.50`) |

The selectors (`select_per_engine`, `select_for_emission`,
`merge_for_llm`) all compare against `conviction_score`. `no_edge`
demotion happens inside the scorer on raw.

## Pre-LLM outcome classification

After the overlay is applied, each candidate gets classified via
`ranker.classify_outcomes`:

| Outcome                 | Condition                                                                                        |
|-------------------------|--------------------------------------------------------------------------------------------------|
| `selected_pre_llm`      | Emittable posture AND `conviction_score >= conviction_threshold`                                 |
| `suppressed_by_hazard`  | Emittable posture, `raw_conviction >= threshold`, `conviction_score < threshold`, AND `hazard_penalty_total > 0` |
| (neither)               | Everything else — `no_edge`, ineligible, or weak thesis where raw was already below threshold    |

Suppression is distinct from "weak thesis" by design: a candidate whose
raw was already below threshold is not counted as suppressed even if
an overlay applied. Only candidates where hazards actually changed the
outcome get the `suppressed_by_hazard` flag.

## Shadow scoring

Both LLM-rejected and hazard-suppressed candidates are shadow-scored
(`shadow_scoring.shadow_score_rejected`). The resulting row on
`mef.shadow_score` carries:

- `gate_decision = 'reject'` for LLM rejections
- `gate_decision = 'hazard_suppressed'` for Layer B suppressions

This is what lets us answer, later, whether the overlay was protecting
real money or just silencing winners.

## Persistence (`mef.candidate` v011)

New columns introduced by `sql/mefdb/011_layered_gating.sql`:

| Column                           | Type        | Meaning                                   |
|----------------------------------|-------------|-------------------------------------------|
| `raw_conviction`                 | NUMERIC     | Pre-overlay engine conviction             |
| `hazard_penalty_total`           | NUMERIC     | Applied (capped) hazard sum               |
| `hazard_penalty_macro`           | NUMERIC     | Macro component                           |
| `hazard_penalty_earnings_prox`   | NUMERIC     | Earnings-proximity component (trend only) |
| `hazard_event_type`              | TEXT        | Top-impact macro event (fomc/cpi/...)     |
| `hazard_flags`                   | TEXT[]      | Short tags like `macro:fomc`, `earn_prox:6-10d` |
| `selected_pre_llm`               | BOOLEAN     | Emission gate verdict                     |
| `suppressed_by_hazard`           | BOOLEAN     | Real thesis suppressed by Layer B         |
| `eligibility_pass`               | BOOLEAN     | Layer A verdict                           |
| `eligibility_fail_reasons`       | TEXT[]      | Layer A failure reasons                   |

`conviction_score` continues to be the number selectors compare
against — it now holds the *final* conviction (post-overlay).
`raw_conviction` is backfilled from `conviction_score` for rows that
predate the migration.

## Where FCF lives now

| Engine           | FCF treatment                                              |
|------------------|------------------------------------------------------------|
| `trend`          | No FCF veto. PE > 60 and `earnings_yield < 2%` keep their soft penalties in Layer C because they shape the trend thesis directly (overpriced ≠ strong continuation). |
| `mean_reversion` | No FCF check. A bounce thesis is technical, not fundamental. |
| `value`          | Negative FCF is a **hard veto** in Layer C. This is not a universal risk control — it is the value thesis itself (cheap + *durable* = cash generation). |

This distinction is what the layered refactor was mainly about. The
universal FCF veto was muting the distinct purpose of mean-rev and
trend; moving it into Layer C for value only restores the intended
per-engine character.

## Tuning discipline

Only the 4 macro base penalties (FOMC, CPI, PCE, NFP, "other") and the
2 earnings-proximity band values are tunable. Everything else is
derived from existing data and should not be tuned empirically:

- Symbol multipliers are sector / ETF-role lookups.
- Engine multipliers derive from engine holding horizon.
- The 0.40 `no_edge` floor and 0.50 emission threshold remain fixed.

Revise the tunables only when realized P&L evidence from
`mef.score` + `mef.shadow_score` strongly supports a move. Do not tune
against small samples — see CLAUDE.md principle 7 on why the threshold
only moves up.
