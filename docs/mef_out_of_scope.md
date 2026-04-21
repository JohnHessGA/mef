# MEF Out-of-Scope

Version: 2026-04-21
Status: Living record of signals / data sources / features deliberately
*not* included in the current MEF ranker, with the rationale for each
decision. Kept here so future iteration doesn't relitigate the same
questions — or, when the reasoning no longer holds, revisits them
deliberately.

The principle behind this file: every signal considered and excluded
is a decision that has value on its own. Losing those decisions means
the next reviewer has to re-derive them from scratch.

---

## Event dates — deferred after 2026-04-21 event-date-awareness ship

The 2026-04-21 "event-date awareness" commit added earnings-proximity
gating and high-impact US macro-calendar overlay. The following related
date families were considered and explicitly not included.

### Ex-dividend dates

**Why excluded:**
- No forward-looking data source in MASD today. `massive_stocks_dividends`
  (Polygon) and `yahoo_stocks_dividends` both carry only historical
  declared dividends; upcoming ex-dates are absent.
- Adding a forward ex-date feed would require new MDC provider work
  (Polygon has a dividend-calendar endpoint MDC doesn't currently pull).

**Why the impact is modest:**
- Ex-dividend gaps are predictable: price drops by approximately the
  dividend amount on ex-date. For the 305-stock large-cap universe,
  typical yields are 0.5–4%, producing gaps of ≤4%.
- MEF's default stop width (7% below entry) comfortably absorbs a 4%
  ex-div gap for most setups.
- The risk is cosmetic (stop appears to tick without cause) rather
  than substantive (position actually breaks down).

**When to revisit:** if paper-scoring later shows a meaningful number
of close-to-stop instances whose proximate cause is an ex-dividend gap
rather than a real breakdown.

---

### FOMC meeting dates

**Why excluded (as a dedicated signal):**
- `masd.fed_policy_events` is present but stale — 12 rows total, zero
  upcoming. The MDC collector for this dataset appears broken.
- Rather than paper over the upstream issue, the better fix is in MDC.

**Why the impact is partially covered anyway:**
- `shdb.economic_calendar` (via the High-impact macro filter added
  2026-04-21) already captures "Fed Interest Rate Decision" and "Fed
  Press Conference" event rows from FMP. The 2026-04-29 FOMC meeting
  shows up in the bundle.
- So MEF's macro-event dampener *does* see FOMC indirectly.

**When to revisit:** after the MDC collector is fixed. FOMC deserves
its own treatment because it has different market mechanics than
routine CPI/NFP releases — rate-sensitive sectors (XLF, XLU, XLRE,
growth tech) behave differently around FOMC than around retail-sales
or inflation prints.

---

### News-volume z-score / sentiment overlays

**Why excluded:**
- MASD has five news sources (`finnhub_news`, `alphavantage_news`,
  `massive_news`, `gdelt_news`, `marketaux_news`), but coverage is
  uneven:
  - Finnhub: 87K articles but stale (last ingested 2026-02-15) —
    collector appears broken
  - Alphavantage: 48K rows, fresh through April — usable
  - Massive: 5K rows, fresh — low volume
  - GDELT: 334 rows total — too sparse
  - Marketaux: 291 rows — too sparse
- For the 305-stock universe, most individual names have very few
  articles per day. A "volume z-score" over sparse counts is
  statistically unstable and produces false signals.

**Why sentiment specifically is a bigger trap:**
- Sentiment polarity scoring (GDELT tone, Finnhub sentiment flags) is
  noisy, poorly attributed, and requires per-source calibration.
- Easy to overfit a ranker to sentiment signals that correlate weakly
  with outcomes.

**When to revisit:** if (a) the Finnhub news collector is fixed and
per-symbol coverage rises to "meaningful articles per symbol per day"
on most of the universe, AND (b) scoring history shows a gap that
news-volume could plausibly close.

---

### Options expiration (3rd Friday monthly, quarterly quad-witching)

**Why excluded:**
- No data needed — derivable from calendar.
- Impact on swing-trade horizons is subtle: gamma pinning near
  round-number strikes, gamma unwinds creating micro-volatility around
  expiry. Matters more for intraday and short-dated options trading
  than for 30-day target holding windows.

**When to revisit:** if MEF ever expands to cover options expressions
(covered calls, cash-secured puts) as primary emittable ideas rather
than just posture-derived expressions. For stock/ETF buys held ~30
days, the signal-to-work ratio is poor.

---

### Post-earnings-drift setups

**Why excluded (for now):**
- `next_earnings_date` is in the v1 evidence; `last_earnings_date`
  could easily be added with a single SQL change to the earnings pull.
- The ranker doesn't yet read `last_earnings_date` because the "post-
  earnings drift" setup is mechanically different from MEF's current
  trend-following scoring: it wants to catch initial gap + first-week
  continuation, which is a shorter-horizon play than MEF's 30-day
  frame.

**When to revisit:** if MEF adds a second scoring engine (the
"ensemble" idea in the broader iteration backlog) with a different
time horizon. Post-earnings drift is a natural fit for a short-horizon
engine.

---

## Signals considered and deferred before the event-date commit

From the broader iteration discussion (captured here so they don't
get forgotten):

### Ensemble of independent ranker engines

**Why deferred:**
- Non-trivial structural work (second scoring module, fusion logic,
  separate thresholds, expanded LLM prompt, per-engine telemetry).
- Premature without outcome data on the current ranker. We don't yet
  know the current engine's hit rate, so we can't measure whether a
  second engine adds signal or noise.

**When to revisit:** after ~30 closed scores land (~mid-to-late May
2026 based on the current paper-score deferral pipeline), when we can
assess whether the single-philosophy ranker has systematic blind spots
a second philosophy could fill.

### Falling-knife detection via SMA20 direction

**Why partially deferred:**
- The `return_5d < -1.5%` standalone brake (in the multi-timeframe
  consensus commit) catches the most obvious falling-knife cases.
- A fuller gate — requiring `sma_20_slope ≥ 0` OR `return_5d ≥ 0` on
  the `needs_pullback` path — wasn't shipped because it overlaps with
  rules already in place and could over-reject recovering stocks.

**When to revisit:** if paper-scoring shows the current 5d brake
misses cases like the 2026-04-20 TSLA pattern (pulled back -18% but
still making lower lows on the intraday tape).

### Range-bound-above-SMAs via bb_width

**Why partially deferred:**
- The `sma_20_slope + sma_50_slope` flat-threshold rule shipped
  2026-04-21 catches most chop cases.
- A `bb_width` percentile-based rule is more sensitive but requires
  rolling-history comparison (not in mart today) and adds complexity
  for marginal gain.

**When to revisit:** if the slope-based chop detector misses patterns
the user flags manually, or if a rolling bb-width percentile becomes
available cheaply.

---

## How to use this file

When a signal / data source / feature is **considered but not built**,
document it here with:
1. **Why excluded** — the substantive reason (data gap, overlap with
   existing rules, complexity vs. signal, timing).
2. **Why the impact is modest** or **partially covered** — so a future
   reviewer understands the severity of the omission.
3. **When to revisit** — concrete trigger conditions (new data, new
   observation, scoring history milestone).

This is not a TODO list. Items here are *decisions*, not tasks. If
something moves from "deferred" to "scheduled," it graduates to
`mef_build_order.md`.
