# MEF Operations Guide

Version: 2026-04-20
Status: Living document — update when behavior or commands change.

How to use MEF day-to-day. The build specs (`README_mef.md`,
`mef_design_spec.md`) describe what the system is; this doc describes
what to do with it once it's running.

---

## The daily rhythm

MEF runs itself twice each weekday via cron (see `mef_cron.md`):

| Run        | Cron time | Intent                                  |
|------------|-----------|-----------------------------------------|
| Pre-market | 07:00 ET  | Trades for **today, after 10:00 AM ET** |
| Post-market| 17:30 ET  | Trades for the **next trading day**     |

You will receive an email after each scheduled run. The email has two
idea sections: "New ideas" for LLM-approved (and unavailable-fallback)
picks that are safe to auto-ship, and "Held for review" for LLM-review
-tagged picks that need human judgment — each shown with the LLM's
one-sentence reason so you can decide whether to act manually.
Rejected ideas do not appear in the email; they're MEFDB-only and
surface via `mef rejections`. See [Held for review](#held-for-review)
below.

A typical email looks like:

```
MEF pre-market report
=====================

Run:      DR-000025 (premarket, completed 07:00 EDT)
Date:     2026-04-21
Intent:   trades for today (after 10:00 ET)
Universe: 305 stocks, 15 ETFs

Summary
-------
Final MEF list: 3 symbols (2 high, 1 medium)
Cross-engine confirmations: 1
Single-engine ideas: 2
Held for LLM review: 2

📅 Upcoming high-impact US macro events:
   - 2026-04-21  Retail Sales MoM (Mar)
   - 2026-04-22  Fed Press Conference

New ideas (3):
  1. TGT ($127.84) · high — value_quality — buy_shares  [engine: value]
     Rec ID:          R-000072
     Plan:            Buy under $129, sell near $141, cut at $115. Hold up to 56 days.
     Buy near:        $126.56-$129.12
     Sell below:      $115.06
     Sell above:      $140.62
     Suggested hold:  through 2026-06-16
     Per 100 shares:  potential +$1,278.00 · risk $1,278.00 · R:R 1.00:1
     Reasoning:       Value-quality setup with strong metrics across all
                      timeframes; low vol; balanced risk/reward.
  2. JCI ($139.46) · high — bullish — buy_shares  [engine: trend]  📅 earnings in 16d
     Rec ID:          R-000073
     Plan:            Buy under $141, sell near $151, cut at $130. Hold up to 30 days.
     Buy near:        $138.05-$140.87
     ...
  3. PSX ($156.37) · medium — oversold_bouncing — buy_shares  [engine: mean-rev]
     Rec ID:          R-000074
     Plan:            Buy under $158, sell near $169, cut at $145. Hold up to 30 days.
     Buy near:        $154.81-$157.93
     ...

Held for review (2) — LLM flagged these for human attention, not auto-ship:
  1. AEP ($133.66) · high — bullish — buy_shares  [engines: trend+value]
     Rec ID:          R-000075
     Plan:            Wait for a dip to $132, then buy. Sell near $142, cut at $122. Hold up to 26 days.
     Buy near:        $129.68-$132.30  ⏳ wait for pullback (currently ~$133.66)
     Price check:     moved +1.0% since close (live ~$133.66)
     Sell below:      $121.90
     Sell above:      $141.68
     Suggested hold:  through 2026-05-17
     Per 100 shares:  potential +$802.00 · risk $1,176.00 · R:R 0.68:1
     Reasoning:       Pullback setup is mechanically coherent, but tight
                      R:R with flat MACD appears fragile.
  ...

Engine views (raw per-engine top picks):
  Trend top 3:
    1. JCI    conv=0.89  bullish
    2. TJX    conv=0.82  bullish
    3. ACGL   conv=0.80  bullish
  Mean-rev top 3:
    1. PSX    conv=0.65  oversold_bouncing
    2. SYY    conv=0.61  oversold_bouncing
    3. TMUS   conv=0.61  oversold_bouncing
  Value top 3:
    1. TGT    conv=0.71  value_quality
    2. MRK    conv=0.70  value_quality
    3. PFE    conv=0.70  value_quality

CLI: mef show <rec-id> · mef dismiss <rec-id> · mef status
```

`No new trades today` is a valid and **healthy** output. The threshold
is set conservatively on purpose. If you go a week or two without an
email-eligible idea, that's the system working as designed, not a
failure (see `CLAUDE.md` core principle #7).

---

## CLI quick reference

Most-frequent first.

| Command                                  | When to use it                                                                                  |
|------------------------------------------|-------------------------------------------------------------------------------------------------|
| `mef status`                             | Quick check: DBs reachable, latest run, latest mart bar date                                    |
| `mef recommendations [--state X]`        | List recommendations by lifecycle state (see [Reading recommendations](#reading-recommendations)) |
| `mef show <rec-uid>`                     | Full detail on one rec — gate decision, paper-score outcome, P&L curve                          |
| `mef report --when premarket`            | Re-render the most recent pre-market email body without sending                                 |
| `mef rejections`                         | Audit table of every LLM-rejected candidate (with reason + issue_type)                          |
| `mef dismiss <rec-uid> [--note "..."]`   | Mark a `proposed` rec as not-going-to-implement                                                 |
| `mef tag <rec-uid> --provenance ...`     | Override the inferred provenance on an active rec (see [Provenance](#provenance))               |
| `mef link-trade <rec-uid> --qty ...`     | Record an actual buy/sell on a scored rec (see [Linking real trades](#linking-real-trades))     |
| `mef gate-audit`                         | Side-by-side outcome distribution of LLM approve / review / reject / unavailable                |
| `mef score`                              | Force-refresh scoring + paper + shadow scores (cron does this automatically)                    |
| `mef import-positions <fidelity.csv>`    | Ingest a Fidelity Portfolio Positions CSV (auto-activates matching `proposed` recs)             |
| `mef run --when premarket --dry-run`     | Run the full pipeline but skip sending the email — preview tomorrow's email tonight             |
| `mef universe [load]`                    | Show or reload the 305+15 universe from the `notes/` files                                      |
| `mef init-db`                            | Apply MEFDB + Overwatch migrations (idempotent; safe to re-run)                                 |

`mef --help` is authoritative if any command drifts from this table.

---

## Reading recommendations

A recommendation moves through a lifecycle. The most common states:

| State           | Meaning                                                                          |
|-----------------|----------------------------------------------------------------------------------|
| `proposed`      | Just emitted by a recent run. Waiting to be acted on, dismissed, or to expire.   |
| `active`        | A matching position appeared in your latest Fidelity import. MEF is tracking it. |
| `dismissed`     | You explicitly said "not implementing this" via `mef dismiss`.                   |
| `expired`       | The entry window closed without a matching position appearing.                   |
| `closed_win`    | Closed at or above target.                                                       |
| `closed_loss`   | Closed at or below stop.                                                         |
| `closed_timeout`| Closed at the time-exit date with neither stop nor target hit.                   |

To list:

```bash
mef recommendations                        # default: open states (proposed + active)
mef recommendations --state proposed       # everything held for review (incl. LLM-review-tagged)
mef recommendations --state active         # what MEF is currently tracking
mef recommendations --all                  # include closed/expired/dismissed
mef recommendations --symbol KLAC          # filter by symbol
mef recommendations --since 2026-04-01     # filter by date
```

For full detail on one rec:

```bash
mef show R-000032
```

`mef show` surfaces (when populated):

- Plan: posture, expression, entry zone, stop, target, time-exit, conviction
- **LLM gate**: decision (approve / review / reject / unavailable), `issue_type`, free-text reason, ship reasoning
- **Provenance**: `mef_attributed` / `pre_existing` / `independent` (set by activator or `mef tag`)
- Matched holding (when active or closed)
- **Paper-trade outcome**: synthetic forward-walked outcome using close-of-run-day entry. Populates after `time_exit` elapses.
- **Realized scoring**: actual outcome with both estimated and `REAL` blocks. The `REAL` block populates when you run `mef link-trade`.
- **Daily P&L curve**: one row per day for the holding period, with `←CLOSE` tag on the final row.

---

## Held for review

Per the LLM gate's 3-way disposition (see `mef_llm_gate.md`):

- **`approve`** → ships in the email's "New ideas" section
- **`review`** → ships in the email's separate **"Held for review"** section with the LLM's one-sentence reason so you can decide whether to act manually. Also saved as a `proposed` recommendation.
- **`reject`** → not saved as a recommendation; lives only on `mef.candidate` for audit

To see review-flagged ideas from the latest run:

```bash
mef recommendations --state proposed
```

Then for any one that interests you:

```bash
mef show R-000032
```

You'll see `decision: review` and the LLM's `issue_type` (most often
`risk_shape`, `volatility_mismatch`, or `posture_mismatch`) plus a
one-sentence reason. From there:

- If you decide to act on it anyway, you simply buy it. The next CSV
  import will auto-activate it the same way it would for an approved
  rec — provenance will be inferred from your purchase timing.
- If you agree with the LLM's caution, leave it; it'll auto-expire
  when its entry window closes (typically ~3 weeks).
- If you want to actively kill it: `mef dismiss R-000032 --note "agree, too extended"`.

---

## Provenance

When MEF flips a `proposed` rec to `active` because a matching
position appeared in your CSV, it stamps **how** that match happened:

| Provenance       | Meaning                                                                       |
|------------------|-------------------------------------------------------------------------------|
| `mef_attributed` | Symbol wasn't in your positions before this rec; appeared during entry window. Strongest case that MEF actually drove the trade. |
| `pre_existing`   | Symbol was already in your positions before MEF proposed it. MEF can't take credit for a trade you'd already made. |
| `independent`    | Position appeared after the entry window closed, or otherwise out-of-band. Ambiguous; default-leans-not-MEF. |

The activator infers this from `min(as_of_date)` of the symbol in
`mef.position_snapshot` history relative to the rec's `created_at` and
`entry_window_end`. If it gets it wrong (e.g., you owned it for years,
sold last week, then re-bought independently), override with:

```bash
mef tag R-000032 --provenance independent
```

Why this matters: `mef gate-audit` and any future P&L roll-ups can
report MEF-attributed outcomes separately from ambient ones, so MEF
doesn't accidentally claim credit for trades you'd have made anyway.

---

## Linking real trades

The `estimated_pnl_100_shares_usd` column in `mef.score` is a
**synthetic** stand-in: (exit_price − entry_price) × 100 shares. Real
position sizing varies, so the headline number won't match your actual
P&L until you link the real trade.

Once a recommendation closes (state `closed_win` / `closed_loss` /
`closed_timeout`) and `mef.score` has a row, link your actual fills:

```bash
mef link-trade R-000032 \
  --qty 50 \
  --buy-price 1525.00 --buy-date 2026-04-21 \
  --sell-price 1670.00 --sell-date 2026-05-05
```

Sell fields are optional — link the buy when you fill it; come back
with the sell when you exit. Re-running the command on the same
`rec_uid` overwrites the prior values (idempotent).

The headline metric this populates is **`realized_pnl_per_day`**:

```
realized_pnl_per_day = realized_pnl_usd / max(1, days_between(buy, sell))
```

That metric directly maps to "max profit in shortest amount of time."

Until PHDB has Fidelity transaction history wired up, this is the
manual bridge. Plan to spend ~30 seconds linking each real trade as
you make it.

---

## The audit cadence

Most days, do nothing — read the email, act or don't, move on.

Every **week or two**, run:

```bash
mef gate-audit
```

This compares LLM-approved outcomes against LLM-rejected outcomes
using the same forward-walk methodology. Until each side has ~20
settled outcomes the report withholds the headline diff (sample
discipline). Expect this to take 2-3 months of daily runs to become
meaningful.

Every **month** (when paper/realized samples accumulate), spot-check:

```bash
mef recommendations --all --since 2026-04-01     # what shipped
mef rejections --since 2026-04-01                # what was rejected (with issue_type)
```

Look for patterns: are the LLM's `risk_shape` rejections actually
underperforming? Is one `issue_type` over-represented (a sign the
prompt could be tightened)?

Every **quarter** (parked until ~3 months of data exists, milestone 17):

- Universe review — flag underperforming symbols for removal, propose
  additions from SHDB symbols meeting liquidity/cap criteria. Manual
  edit to the `notes/focus-universe-us-stocks-final.md` file; rerun
  `mef universe load`.

---

## When things go wrong

### The email didn't arrive

1. Check the cron log:
   ```bash
   tail -200 /mnt/aftdata/logs/mef/cron.log
   ```
2. Check Overwatch for the run row:
   ```bash
   PGPASSWORD=mef_local_2026 psql -h localhost -U mef_user -d overwatch \
     -c "SELECT * FROM ow.mef_run ORDER BY started_at DESC LIMIT 5;"
   ```
3. Re-render the body for the run that should have sent:
   ```bash
   mef report --when premarket
   ```

### The email banner says "data is stale"

UDC's daily harvest probably failed. Check:

```bash
udc status
```

If the latest mart bar is old, fix UDC first. MEF will resume
normal operation on the next scheduled run after fresh data lands. If
the staleness is severe (>7 calendar days by default), MEF aborts the
run and emails a `[STALE DATA]` warning instead of producing ideas.

### LLM gate was unavailable

The email will say *"LLM gate was unavailable for this run — ideas
below were not reviewed."* Each affected rec will be tagged
`Not reviewed by LLM (gate unavailable).` Fall-back behavior is
**ship anyway** so an Anthropic outage doesn't silence MEF entirely.
The `mef.llm_trace` row carries the underlying error.

### Too many "review" / too few "approve"

Run-to-run variance from the LLM is normal — same prompt + same inputs
can produce different dispositions on consecutive calls. Watch for ~5
runs before concluding the calibration is wrong. If review/approve
ratios are persistently lopsided after that, iterate the prompt
(`src/mef/llm/prompts.py`) — see `mef_llm_gate.md` for guidance.

---

## Configuration locations

| Path                         | What's there                                          | Gitignored? |
|------------------------------|-------------------------------------------------------|-------------|
| `config/mef.yaml`            | Cadence, ranker thresholds, freshness, LLM, email     | yes         |
| `config/postgres.yaml`       | DB credentials for `mefdb`, `shdb`, `overwatch`       | yes         |
| `~/repos/mdc/config/notifications.yaml` | SMTP credentials (read by `email_send.py`) | yes (in MDC) |
| `cron/mef.cron`              | Cron template (install via `crontab -e`)              | no          |
| `notes/focus-universe-us-stocks-final.md` | Source-of-truth for the 305 stocks       | no          |
| `notes/core-us-etfs-daily-final.md`       | Source-of-truth for the 15 ETFs          | no          |
| `/mnt/aftdata/logs/mef/`     | Daily cron logs                                       | n/a         |
| `/mnt/aftdata/mef/`          | Generated artifacts root (currently unused)           | n/a         |

---

## Where to dig deeper

| Topic                                | Doc                          |
|--------------------------------------|------------------------------|
| What MEF is and why                  | `README_mef.md`              |
| Architecture, schema, pipeline       | `mef_design_spec.md`         |
| Milestone history + what's next      | `mef_build_order.md`         |
| LLM gate prompt + 3-way disposition  | `mef_llm_gate.md`            |
| Scoring + audit data model           | `mef_audit_model.md`         |
| Cron install + scheduling            | `mef_cron.md`                |
| Working notes for code assistants    | `CLAUDE.md`                  |
