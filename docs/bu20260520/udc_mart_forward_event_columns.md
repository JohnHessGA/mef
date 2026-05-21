# UDC Mart Enhancement — Forward-Event Columns on `mart.stock_equity_daily`

**Status:** Scope narrowed 2026-04-22 after mart inspection
**Driver:** CCW v1 (covered-call event blackout) — `~/repos/ccw/docs/README.ccw.md`
**Secondary beneficiary:** MEF — existing `hazard_penalty_earnings_prox` logic can simplify further

---

## Current state (2026-04-22)

`mart.stock_equity_daily` **already has** forward-earnings columns:
- `next_earnings_date` (date) — present
- `days_to_next_earnings` (smallint) — present

It also has **backward-looking** dividend columns:
- `last_ex_div_date` (date)
- `days_since_last_ex_div` (smallint)
- `dividend_frequency` (smallint) — could derive next ex-div from this + last date if needed

**Remaining gap: no forward ex-dividend column.** That's the only part of the original proposal still outstanding.

---

## Revised proposal (ex-dividend only)

Add two columns to `mart.stock_equity_daily`:

| Column | Type | Semantics |
|---|---|---|
| `next_ex_div_date` | date | Next scheduled ex-dividend date on or after `bar_date` |
| `days_to_next_ex_div` | smallint | `(next_ex_div_date - bar_date)::int`; NULL if unknown |

Data source: `stock_dividend_events_1d` (Layer 1 — confirm exact table name in UDC inventory).

Implementation pattern: LATERAL forward-only join on `(symbol, ex_dividend_date >= bar_date ORDER BY ex_dividend_date ASC LIMIT 1)`. Same shape as the valuation LATERAL as-of joins already in the equity mart.

---

## Why MEF cares (earnings — already actionable)

MEF's `hazard_penalty_earnings_prox` logic can already read `days_to_next_earnings` directly from the equity mart (as of the mart inspection on 2026-04-22). If it still joins `earnings_calendar` on every run, that's a simplification opportunity — one column lookup, no join.

## Why MEF cares (ex-div — new signal when column ships)

Ex-dividend proximity is a **new** signal for MEF — not currently used — but worth considering as a hazard factor. Dividend capture trades and early assignment risk on short ITM calls create short-term price action around ex-div dates. Deferred for MEF; **required for CCW milestone 7**.

---

## Cross-tool dependencies created

| Tool | Need | Priority |
|---|---|---|
| CCW milestone 7 | Hard dependency — 14-day ex-div blackout cannot ship without `next_ex_div_date` / `days_to_next_ex_div` | **required** |
| MEF | (a) earnings — already actionable from existing columns; simplification opportunity. (b) ex-div hazard — new signal available once column ships | optional |
| DAS | No immediate need but might use later for event-aware stop guidance | optional |

CCW sequencing plan: CCW scaffolding (milestones 0-6) proceeds in parallel with UDC work. The ex-div UDC enhancement must ship **before** CCW milestone 7. Tracking in `~/repos/ccw/docs/ccw_build_order.md`.

---

## Suggested UDC implementation steps

1. Add a new builder or extend `src/udc/builders/shdb/equity_derived.py` with a LATERAL as-of-forward join against `earnings_calendar` for each `(symbol, bar_date)` row.
2. Add a matching LATERAL as-of-forward join against `stock_dividend_events_1d`.
3. Update `mart_stock_equity_daily` (and `mart_stock_etf_daily`) to SELECT the four new columns.
4. Migration: `ALTER TABLE mart.stock_equity_daily ADD COLUMN IF NOT EXISTS ...` (idempotent per UDC convention).
5. Full mart rebuild (`udc harvest --rebuild-mart`) to populate historical rows.
6. Update `~/repos/udc/docs/mart-layer-guide.md` column table to document the four additions.
7. Announce in `~/repos/notes/conventions.md` or appropriate notes file.

Expected incremental harvest cost: small. LATERAL forward-lookups are cheap since `earnings_calendar` and `stock_dividend_events_1d` are indexed on `(symbol, event_date)`.

---

## Coverage caveats

- **Earnings calendar coverage:** FMP provides forward earnings dates for most liquid US names; expect some NULL on small-caps, foreign listings, and names with pending reschedules.
- **Ex-dividend coverage:** strong for dividend payers; NULL is the correct value for non-dividend stocks.
- **History:** forward-looking columns are only meaningful from the point in time where the upstream calendar was populated. Expect partial coverage on older `bar_date` rows.

These are fine — CCW and MEF both tolerate NULL (treat as "no event known, not blocked"), and both annotate rather than substitute.

---

## Why not do it in each tool separately?

We discussed two paths (see CCW design conversation 2026-04-22):
- **Path A:** each tool joins the calendar tables directly in its own queries
- **Path B:** UDC adds the columns to the mart; all consumers read them

Path B wins for three reasons:
1. One authoritative definition of "next earnings / ex-div" across all tools
2. Simpler recurring scoring SQL (fewer joins per run, faster daily cron)
3. Matches the mart's design goal: single row per `(symbol, bar_date)` is the AI/LLM and engine front door

The one-time UDC cost (one enhancement, one rebuild) is small; the ongoing simplification is permanent.
