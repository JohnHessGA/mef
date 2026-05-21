# MEF Core Pullback Radar

Version: 2026-05-21 (naming alignment)
Status: v1 operational — DB-backed watchlist, deterministic engine, rendered in `mef status`
Owner: MEF (Investing Track 4 — Capital Appreciation)
Filename note: this file is `docs/mef_core_pullback_watchlist.md` for
filename continuity. The doc itself is the canonical reference for
**Core Pullback Radar** (previously called **Job 2** / **Core Pullback
Watchlist** / **Growth Pullback Radar**).

---

## Purpose

Core Pullback Radar is one of MEF's two functions, alongside the **Growth
Opportunity Finder** (previously called "Job 1"). It is part of MEF's
mandate as Investing Track 4 — Capital Appreciation.

It monitors selected ETFs and stocks every day and raises visibility when a meaningful pullback may create a practical buying opportunity.

This is a **growth pullback radar**, not a "forever hold only" list and not a normal top-N screener. It is designed to help the user notice moments like a sharp SPY pullback near the end of March followed by an attractive early-April entry window.

The key question:

> Has this asset pulled back enough to be interesting, while still looking healthy enough that the pullback may be an opportunity rather than a breakdown?

---

## Relationship to Existing MEF

The MEF **Growth Opportunity Finder** produces capital-appreciation
ideas using deterministic engines, selection, and an LLM review gate.

Core Pullback Radar is separate.

| MEF function | Purpose | Selection style |
|---|---|---|
| Growth Opportunity Finder | Find buyable new ideas today (or "wait for entry" candidates) | Ranker/engine driven |
| Core Pullback Radar | Monitor selected assets for pullback buy zones | Standing configured watchlist |

Core Pullback Radar symbols do not need to win a daily top-N competition.
They are monitored every run because the user wants visibility when they
pull back.

---

## Design Principles

1. **Deterministic first.** Pullback status and buy levels are calculated in Python.
2. **No LLM in v1 decisions.** The LLM does not decide status, visibility, or levels.
3. **Visibility, not pressure.** The output should raise attention, not imply automatic buying.
4. **Good asset does not equal good entry.** Excellent assets can be too extended.
5. **Large pullback does not equal buy.** Broken charts should be labeled as wait/review.
6. **Tier-aware thresholds.** SPY and INTC should not be judged by the same rules.
7. **Quiet is normal.** Most symbols should usually have no notable pullback.
8. **No broad-market expansion in v1.** Use the configured 10 ETF + 50 stock universe.

---

## Universe

### ETFs — 10

These are Tier 1 core market / growth ETFs.

| Symbol | Role |
|---|---|
| SPY | S&P 500 core market |
| QQQ | Nasdaq/growth core |
| VTI | Total U.S. market |
| ONEQ | Nasdaq composite exposure |
| IWM | Small-cap / risk-on recovery |
| SCHG | Large-cap growth |
| VUG | Growth ETF |
| XLK | Technology sector |
| SMH | Semiconductors |
| SCHD | Dividend / quality anchor |

### Stocks — 50

#### Tier 2 — Elite compounders / dominant growth leaders

These are high-priority growth assets where MEF should aggressively watch for attractive pullbacks but avoid chasing extended prices.

| Symbol | Rationale |
|---|---|
| NVDA | AI / accelerated computing leader |
| MSFT | Cloud, AI, enterprise software |
| GOOGL | Search, cloud, AI, YouTube |
| AMZN | Cloud, retail, logistics, ads |
| META | Ads, AI, platforms |
| AAPL | Ecosystem and cash generation |
| AVGO | AI infrastructure, semis, software |
| LLY | Obesity, diabetes, pharma growth |
| COST | Quality compounder / defensive growth |
| NFLX | Media platform and pricing power |
| ORCL | Cloud infrastructure / enterprise AI angle |
| AMD | AI / semiconductor challenger |

#### Tier 3 — Quality growth / durable leaders

These are strong businesses or strong market-position names where pullbacks may be attractive, but MEF should require clean entry quality.

| Symbol | Rationale |
|---|---|
| JPM | Best-in-class financial |
| BRK.B | Quality compounder |
| UNH | Healthcare recovery / managed-care leader |
| ISRG | Med-tech quality growth |
| ADBE | Software / AI transition |
| INTU | Quality software compounder |
| ASML | Semiconductor equipment |
| TSM | Foundry / AI semiconductor supply chain |
| CRM | Enterprise software |
| NOW | Workflow software quality growth |
| PANW | Cybersecurity platform |
| CRWD | Cybersecurity growth |
| UBER | Platform growth / profitability story |
| SHOP | Commerce software growth |
| LIN | Industrial quality compounder |

#### Tier 4 — Volatile growth / special situations

These can be useful pullback opportunities, but MEF should demand deeper discounts and better stabilization before raising buy visibility.

| Symbol | Rationale |
|---|---|
| TSLA | High-beta growth / autonomy / energy |
| INTC | Turnaround / semiconductors / foundry story |
| PLTR | AI software momentum |
| ARM | Semiconductor architecture |
| MU | Memory cycle / AI infrastructure |
| SNOW | Data cloud growth |
| DDOG | Observability / cloud software |
| NET | Edge/cloud network software |
| MDB | Database software |
| RBLX | High-beta platform growth |
| COIN | Crypto infrastructure / high beta |
| HOOD | Brokerage / fintech / high beta |
| SOFI | Fintech / banking growth |
| SMCI | AI server infrastructure / high volatility |
| DELL | AI servers / enterprise hardware |
| APP | Ad-tech / AI software growth |
| ANET | Networking / AI data center |
| VRT | Power/cooling infrastructure for AI data centers |
| CAVA | Consumer growth / restaurant expansion |
| CELH | Consumer growth / beverage |
| TTD | Ad-tech platform |
| ENPH | Solar / energy special situation |
| NVO | Obesity / diabetes pharma growth |

---

## Status Vocabulary

### Internal status values

| Status | Meaning |
|---|---|
| `NO_PULLBACK` | No meaningful pullback yet. |
| `PULLBACK_FORMING` | Pullback is becoming interesting but not yet in the preferred buy zone. |
| `BUY_ZONE_ACTIVE` | Pullback has reached a practical starter or better buy zone and trend health is acceptable. |
| `DEEP_PULLBACK_OPPORTUNITY` | Pullback is large enough to be unusually interesting, assuming thesis/trend has not broken. |
| `FALLING_KNIFE_WAIT` | Pullback is large, but stabilization is not good enough yet. |
| `THESIS_BROKEN_REVIEW` | Pullback may reflect serious damage; review before considering buys. |

### Human display labels

| Internal | Display |
|---|---|
| `NO_PULLBACK` | No meaningful pullback yet |
| `PULLBACK_FORMING` | Pullback forming |
| `BUY_ZONE_ACTIVE` | Buy zone active |
| `DEEP_PULLBACK_OPPORTUNITY` | Deep pullback opportunity |
| `FALLING_KNIFE_WAIT` | Falling knife — wait |
| `THESIS_BROKEN_REVIEW` | Thesis/risk changed — review before buying |

---

## Evidence Families

Core Pullback Radar should use evidence already available in SHDB where possible.

### Pullback from recent highs

Measure current price versus:

- 20-day high
- 63-day high
- 126-day high, if available
- 252-day high

Key outputs:

- `drawdown_20d`
- `drawdown_63d`
- `drawdown_252d`

### Trend health

A pullback is useful only if the long-term setup is not broken.

Useful indicators:

- close versus SMA20 / SMA50 / SMA200
- SMA50 slope
- SMA200 slope
- 63-day return
- 126-day return
- 252-day return
- relative strength versus SPY / QQQ where available

### Stabilization

Avoid alerting as buyable while the stock is still in freefall.

Useful indicators:

- 5-day return not severely negative
- RSI reset but not panic-broken
- MACD histogram improving or less negative
- ATR/volatility not exploding without stabilization
- price reclaiming or holding a moving average / support level
- downtrend decelerating

### Volatility / ATR

Use ATR and realized volatility to avoid one-size-fits-all pullback levels.

A 5% pullback in SPY is not the same as a 5% pullback in TSLA or COIN.

### Risk/reward

Estimate whether buying near the proposed level gives acceptable upside versus downside.

Possible fields:

- upside to recent high
- downside to breakdown level
- target reference price
- stop/reference risk level
- risk/reward ratio

### Event caution

Where available:

- earnings proximity for individual stocks,
- macro events for ETFs and high-beta names,
- major known calendar risk from existing SHDB event sources.

Event caution should not automatically suppress every alert, but the display should make risk clear.

---

## Pullback Thresholds

These are starting points, not permanent constants.

| Asset type | Visibility starts | Buy zone / stronger alert | Deep alert |
|---|---:|---:|---:|
| Tier 1 broad ETF, e.g. SPY/VTI | 3–4% | 5–7% | 8–12% |
| Tier 1 growth ETF, e.g. QQQ/SMH/XLK | 4–5% | 7–10% | 12–15% |
| Tier 2 elite compounder | 5–7% | 8–12% | 15%+ |
| Tier 3 quality growth | 7–10% | 10–15% | 18%+ |
| Tier 4 volatile/special situation | 10–15% | 15–22% | 25%+ |

The implementation should prefer config-driven thresholds by tier and asset class.

---

## Suggested Buy Levels

Core Pullback Radar should provide zones, not one magic price.

Suggested levels:

- `starter_buy_level`
- `better_buy_level`
- `deep_buy_level`

Possible calculation inputs:

- recent high minus tier pullback percentage,
- SMA50 / SMA100 / SMA200,
- ATR-adjusted distance,
- recent support zone,
- prior consolidation/basing area where available.

Example conceptual formula:

```text
starter = blend_or_select(
    recent_high_63d * (1 - starter_pullback_pct),
    sma50,
    close - 1.5 * atr14
)

better = blend_or_select(
    recent_high_63d * (1 - stronger_pullback_pct),
    sma100_or_sma200,
    close - 2.5 * atr14
)

deep = blend_or_select(
    recent_high_252d * (1 - deep_pullback_pct),
    sma200,
    close - 3.5 * atr14
)
```

The first implementation can keep this simpler, but it should preserve the idea that levels are volatility- and tier-aware.

---

## Decision Model

A simple v1 decision tree:

```text
For each symbol in the configured pullback watchlist:

1. Load evidence.
2. Assign tier and asset type.
3. Calculate drawdown from recent highs.
4. Calculate suggested buy levels.
5. Check trend health.
6. Check stabilization.
7. Check event caution.
8. Estimate risk/reward.
9. Assign status.
10. Render notable statuses.
```

### Example status logic

```text
IF trend_health = broken:
    status = THESIS_BROKEN_REVIEW

ELSE IF pullback >= deep_threshold AND stabilization_ok:
    status = DEEP_PULLBACK_OPPORTUNITY

ELSE IF pullback >= buy_zone_threshold AND stabilization_ok AND risk_reward_ok:
    status = BUY_ZONE_ACTIVE

ELSE IF pullback >= visibility_threshold AND NOT stabilization_ok:
    status = FALLING_KNIFE_WAIT

ELSE IF pullback >= visibility_threshold:
    status = PULLBACK_FORMING

ELSE:
    status = NO_PULLBACK
```

Tier 4 should require stronger stabilization and risk/reward than Tier 1 or Tier 2.

---

## Output Design

The default `mef status` should show only notable pullback items and a quiet count.

Example:

```text
CORE PULLBACK WATCHLIST
=======================

BUY ZONE ACTIVE
  SPY   $xxx.xx  starter $yyy  better $zzz
        Pulled back 6.4% from recent high; long-term trend intact.

  MSFT  $xxx.xx  starter $yyy  better $zzz
        Pullback reached starter zone; stabilization acceptable.

PULLBACK FORMING
  QQQ   $xxx.xx  starter $yyy
        Pullback underway; still above preferred buy zone.

FALLING KNIFE — WAIT
  INTC  $xx.xx
        Pullback is large, but trend health/stabilization is not acceptable yet.

QUIET
  56 watchlist symbols have no meaningful pullback today.
```

Do not display all 60 symbols every day unless a future details command asks for it.

---

## LLM Boundary

The LLM is not used in Core Pullback Radar v1.

Specifically, the LLM must not:

- decide pullback status,
- calculate buy levels,
- create symbols,
- upgrade a symbol into buyable status,
- suppress a deterministic alert,
- change thresholds,
- rewrite risk/reward conclusions.

A future LLM or qualitative review layer may summarize sentiment or context for symbols already raised by Python, but it must remain annotation-only.

---

## CIA Future Overlay

CIA may later provide context from congressional, insider, institutional, or whale activity.

CIA should be a support/caution overlay only.

Allowed future use:

- "CIA shows supportive insider/congressional activity."
- "CIA shows sell-side caution; review before buying."
- "CIA signal is stale; ignored."

Not allowed:

- CIA creates a MEF buy recommendation by itself.
- CIA overrides deterministic pullback status.
- CIA turns a broken chart into a buy.
- CIA suppresses a valid pullback alert without transparent display.

See `mef_cia_future_overlay.md`.

---

## Implementation Notes

Likely engine module:

```text
src/mef/core_pullback.py        (not yet implemented)
```

### Persistence model (already in place as of 2026-05-20)

Core Pullback Radar metadata lives in MEFDB. SQL migration
`sql/mefdb/013_core_pullback_watchlist.sql` creates three tables in the
`mef` schema:

| Table | Role |
|---|---|
| `mef.core_pullback_tier` | Tier reference: drawdown thresholds, display metadata, enabled flag. 5 rows. |
| `mef.core_pullback_watchlist` | The 10-ETF + 50-stock operational list; each row carries `symbol`, `asset_kind`, `tier_code`, `enabled`, `display_order`. |
| `mef.core_pullback_snapshot` | One row per run per symbol, written by the pullback engine when it lands. Empty until then. |

There is **no YAML watchlist file**, no markdown loader, and no config
key. To change the operational watchlist or tier thresholds, edit MEFDB
(directly, or by adding a new migration). The engine reads from these
tables every run.

This matches the AFT rule (per repo `CLAUDE.md`): runtime and loader
code must not read operational symbol lists from markdown, `docs/`, or
`notes/` — operational lists live in MEFDB. YAML is for settings only.

### Engine output object (when implemented)

```python
@dataclass
class PullbackSignal:
    symbol: str
    asset_kind: str
    tier: str
    status: str
    display_label: str
    close: Decimal
    drawdown_63d: Decimal | None
    drawdown_252d: Decimal | None
    starter_buy_level: Decimal | None
    better_buy_level: Decimal | None
    deep_buy_level: Decimal | None
    trend_health: str
    stabilization: str
    risk_reward: Decimal | None
    reasons: list[str]
    cautions: list[str]
```

Each computed signal becomes one `mef.core_pullback_snapshot` row (UID
prefix `PS-`, FK to `mef.daily_run(uid)` so a run's snapshots are
deletable as a unit).

---

## Testing Expectations

Minimum tests:

- universe loads 10 ETFs and 50 stocks,
- tier assignment is correct,
- SPY-type thresholds differ from TSLA/INTC-type thresholds,
- no meaningful pullback produces `NO_PULLBACK`,
- meaningful healthy pullback produces `BUY_ZONE_ACTIVE`,
- deep stable pullback produces `DEEP_PULLBACK_OPPORTUNITY`,
- large unstable selloff produces `FALLING_KNIFE_WAIT`,
- broken trend produces `THESIS_BROKEN_REVIEW`,
- quiet symbols are summarized rather than all rendered,
- LLM is not called by Core Pullback Radar.

---

## Build Sequence

Recommended sequence:

1. ~~Land this documentation.~~ Done.
2. ~~Add DB-backed watchlist (`mef.core_pullback_tier` + `mef.core_pullback_watchlist`).~~ Done (migration `013_core_pullback_watchlist.sql`, 2026-05-20).
3. Add evidence loader or reuse existing evidence bundle.
4. Implement status calculator in `src/mef/core_pullback.py`.
5. Persist results into `mef.core_pullback_snapshot` (table already exists).
6. Render notable section in `mef status`.
7. Add engine tests.
8. Run daily and review real output before tuning thresholds (edit the tier rows in MEFDB or add a follow-up migration).
9. Consider future LLM sentiment or CIA overlay only after deterministic behavior is trusted.

