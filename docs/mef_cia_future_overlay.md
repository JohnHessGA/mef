# MEF Future Overlay — CIA Signals

Version: 2026-05-20 draft
Status: Future enhancement note
Owner: MEF / CIA integration boundary

---

## Purpose

This document records a future MEF enhancement: using CIA signals as a support/caution overlay for MEF opportunities.

CIA — Congressional-Insider Alerts — is an AFT advisory stream that surfaces investigation leads from congressional, insider, institutional, whale, and similar actor activity.

MEF should eventually be able to display CIA context when it is relevant to a MEF opportunity, especially a Core Pullback Radar alert.

---

## Current Decision

CIA is **not** part of the initial MEF Core Pullback Radar implementation.

The first implementation of Core Pullback Radar (previously called Job 2) is deterministic and relies on market data, pullback size, trend health, stabilization, risk/reward, and event caution.

CIA should be parked as a future overlay because:

1. The pullback engine should be useful on its own.
2. CIA should not become a magic buy/sell signal.
3. CIA lead synthesis and scoring should mature before MEF depends on it.
4. MEF decisions must remain auditable and repeatable.

---

## Design Rule

CIA data may support, caution, or explain a MEF opportunity, but it must not independently create a buy recommendation or override deterministic pullback/trend logic.

---

## Allowed Future Uses

CIA may eventually add context such as:

- supportive congressional activity,
- supportive insider activity,
- caution from sell-side insider or congressional activity,
- actor-edge score,
- lead strength,
- source freshness,
- age of signal,
- whether signal agrees or conflicts with MEF pullback status.

Examples:

```text
MSFT — Buy zone active
CIA context: supportive insider/congressional activity detected.
```

```text
TSLA — Pullback forming
CIA context: recent sell-side actor activity; treat as caution, not veto.
```

```text
INTC — Falling knife / wait
CIA context: no fresh supportive CIA lead.
```

---

## Disallowed Uses

CIA must not:

- create a MEF buy recommendation by itself,
- override deterministic pullback status,
- change buy levels,
- upgrade `FALLING_KNIFE_WAIT` to `BUY_ZONE_ACTIVE`,
- suppress a valid alert without transparent display,
- silently introduce actors or signals into ranking math,
- force trades because a public figure or insider bought shares.

---

## Potential MEF Fields

Possible future MEF overlay fields:

```text
cia_buy_support: none / weak / moderate / strong
cia_sell_warning: none / weak / moderate / strong
cia_lead_strength
cia_actor_edge_grade
cia_sources: congress / insider / institution / whale
cia_event_age_days
cia_source_freshness: fresh / stale / empty / failed
cia_summary
```

These should be display or secondary-score fields, not primary decision fields.

---

## Possible Scoring Effect

If MEF eventually uses CIA quantitatively, the effect should be small.

Suggested guardrails:

| CIA context | Possible MEF effect |
|---|---|
| Fresh strong buy lead | Small visibility boost or positive note |
| Moderate buy lead | Context note only |
| Fresh sell lead on Tier 1 ETF | Caution note only |
| Fresh sell lead on Tier 2 stock | Caution note / human review |
| Fresh sell lead on Tier 4 stock | Stronger caution; may require stabilization/review |
| Stale lead | Ignore or show in details only |

For the Growth Opportunity Finder (was Job 1), a future bonus/penalty should be small, such as +/-0.02 to +/-0.05, and never enough to turn a poor setup into an actionable idea.

For Core Pullback Radar (was Job 2), CIA should not change deterministic buy levels.

---

## Integration Timing

Do not integrate CIA into MEF until:

1. Core Pullback Radar deterministic output is working and trusted.
2. CIA lead synthesis is implemented.
3. CIA scoring/actor-edge fields are stable enough to consume.
4. CIA source freshness is reliable enough to display.
5. MEF has a clear display pattern for support/caution overlays.

---

## Suggested Future Architecture

Potential future module:

```text
src/mef/context_overlays/cia_overlay.py
```

Responsibilities:

1. Read CIA leads or summaries.
2. Match CIA context by symbol.
3. Filter by freshness and lead strength.
4. Produce a small overlay object.
5. Attach overlay to MEF-rendered output.
6. Never change the deterministic pullback status or buy levels.

Potential output object:

```python
@dataclass
class CiaOverlay:
    symbol: str
    buy_support: str
    sell_warning: str
    lead_strength: Decimal | None
    actor_edge_grade: str | None
    sources: list[str]
    event_age_days: int | None
    freshness: str
    summary: str
```

---

## Display Philosophy

CIA context should be brief.

Good:

```text
CIA context: supportive insider activity detected; use as confirmation only.
```

Good:

```text
CIA context: sell-side actor activity present; review before acting.
```

Bad:

```text
CIA says buy.
```

Bad:

```text
Congress bought this, so MEF recommends it.
```

CIA is supporting evidence, not command authority.

---

## Relationship to LLM Sentiment Review

CIA and future LLM sentiment review are different overlays.

| Overlay | Source | Role |
|---|---|---|
| CIA overlay | Structured actor-activity data | Support/caution context |
| LLM sentiment review | News/sentiment/qualitative summaries, if added later | Plain-English context annotation |

Neither should control deterministic pullback status in v1.

---

## Documentation Note

If this overlay is implemented later, update:

- `README_mef.md`
- `mef_core_pullback_watchlist.md`
- `mef_design_spec.md`
- CIA docs if MEF requires a new CIA output view or export
- tests documenting that CIA cannot override deterministic MEF status

