# MEF TODOs

Forward-looking cleanups and small refactors. Not blocking the daily loop.
Add new items at the top; keep each entry small and self-contained.

---

## Replace `_fetch_earnings_context` with mart column

**Added:** 2026-04-22
**Trigger:** CCW has been live in production for several days and
`mart.stock_equity_daily.next_earnings_date` has proven stable.
**Reference:** `notes/udc_mart_forward_event_columns.md`

UDC migration 039 added `next_earnings_date` and `days_to_next_earnings`
to `mart.stock_equity_daily` (and the ETF mart). Once CCW is consuming
those columns reliably, MEF can drop its own per-run join.

Scope (~30 lines in `src/mef/evidence.py`):

- Remove `_UPCOMING_EARNINGS_SQL` and `_fetch_earnings_context`.
- Remove the stitch loop currently at lines ~298-300 that writes
  `next_earnings_date` onto each stock row.
- Add `next_earnings_date` to the SELECT list in `_EQUITY_SQL` so the
  value flows directly off the mart row.
- `src/mef/eligibility.py` is untouched — it already keys on
  `row["next_earnings_date"]`.

Pre-flight sanity check before deleting anything:

```sql
SELECT
  COUNT(*)                                              AS rows,
  COUNT(*) FILTER (WHERE next_earnings_date IS NOT NULL) AS with_earn
FROM mart.stock_equity_daily
WHERE bar_date = (SELECT MAX(bar_date) FROM mart.stock_equity_daily);
```

Compare `with_earn` against the count from
`shdb.earnings_calendar_upcoming` for the same bar. They should agree.

**Do not** add ex-dividend proximity at the same time. Forward ex-div is
not yet shipped on UDC's side (deferred pending FMP `dividends_calendar`
MDC work). The bridge columns (`last_ex_div_date`, `dividend_frequency`)
exist but stay unused until a concrete MEF need surfaces.
