# Core US ETFs — Daily Tradable Shortlist (20 Symbols)

> **Documentation only.** Operational universe data lives in MEFDB
> (`mef.universe_etf`), seeded by SQL migrations in `sql/mefdb/`. No
> runtime or loader code reads this file. Edits here update the human
> rationale only — to change what MEF actually scores, edit MEFDB.

Version: 2026-05-05 (expanded from 15 → 20: added VUG, SCHG, SPYG, QUAL under Style/Factor; ONEQ under Broad Market)

This is a daily-use set of core US ETF list. It is designed for a forecasting tool that values **tradability, liquidity, and clear role definition** over maximum coverage.

Source basis:

- The 30-symbol source had already removed international ETFs, bonds, crypto ETFs, metals, non-equity commodities, leveraged/UltraShort products, and near-duplicates. 

## Selection Goal

Keep a **small, highly tradable ETF set** that still covers:

- broad market direction
- growth vs. value tilt
- size exposure
- major sector rotation
- one high-liquidity industry ETF
- one defensive sector for risk-off periods

## Daily Shortlist (20)

### Broad Market (4)

- **SPY** — S&P 500 benchmark; primary broad-market reference
- **QQQ** — large-cap growth / Nasdaq leadership
- **VTI** — total market exposure
- **ONEQ** — Nasdaq Composite (broader Nasdaq read than QQQ)

### Size (1)

- **IWM** — small-cap risk appetite / cyclicality read

### Style / Factor (7)

- **IWD** — large-cap value
- **IWF** — large-cap growth
- **SCHD** — dividend / quality-income tilt
- **VUG** — Vanguard large-cap growth
- **SCHG** — Schwab large-cap growth
- **SPYG** — SPDR S&P 500 growth
- **QUAL** — MSCI USA quality factor

### Core Sector ETFs (7)

- **XLK** — technology
- **XLF** — financials
- **XLV** — health care
- **XLE** — energy
- **XLI** — industrials
- **XLY** — consumer discretionary
- **XLP** — consumer staples (defensive)

### Industry ETF (1)

- **SMH** — semiconductors; high-importance industry group with strong trading relevance

## Why these 20 made the cut

These ETFs were favored because they are generally among the most practical instruments for a daily recommendation engine:

- broad recognition and heavy usage
- typically strong liquidity
- clearer options relevance for conservative strategies when needed
- good coverage of market leadership, sector rotation, and defensive posture
- less redundancy than the larger 30-symbol list

## ## Recommended use

Use these 20 as the **daily scoring universe** for ETFs.

Note: VUG / SCHG / SPYG / IWF heavily overlap as large-cap growth proxies; the ranker does not dedupe correlated ETFs, so on growth-led days expect multiple correlated emissions.


