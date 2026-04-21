# MEF Price Check

Post-emission, live-price sanity check. **Informational only.** The
ranker is deterministic-first: engines score stocks from multi-week
SHDB history, and a 1-day move doesn't change that judgment. Live
pricing answers a different question — "is the entry zone in this
email still valid right now?" — which matters to the user but not to
the scoring.

Source: `src/mef/price_check.py`.

## When it runs

After the LLM gate, before email rendering, on the ~5–10 emitted ideas
only. Does not touch the 305+15 universe or the engine scorers.

Runs in the normal daily-run path. Skipped in the stale-data abort
path (no ideas to check).

## What it does

1. Dedup the symbols emitted this run.
2. One batch call to yfinance for 1-minute bars with `prepost=True`.
3. For each symbol: take the latest non-null close from that series.
4. Compare to the SHDB close used at scoring time.
5. Classify the delta into a tier + optional note.

## What it **does not** do

- Does not change `conviction_score`, `raw_conviction`, `posture`, or
  the draft plan's entry zone / stop / target / time_exit.
- Does not block email delivery — yfinance errors fail-silent; per-
  symbol entries return with tier `unavailable` and note `None`.
- Does not call yfinance for rejected candidates, no_edge rows, or
  anything that wasn't emitted.

## Tier table

| Tier          | Trigger                                    | Email behavior |
|---------------|--------------------------------------------|----------------|
| `none`        | \|delta\| < `info_threshold_pct` (1% default) | Silent — no line rendered |
| `info`        | `info_threshold_pct` ≤ \|delta\| < `warn_threshold_pct` | "Price check: moved +X.Y% since close (live ~\$NNN.NN)" |
| `warn`        | \|delta\| ≥ `warn_threshold_pct` (3% default) | "Price check: ⚠ moved +X.Y% since close (live ~\$NNN.NN) — entry zone may need refresh" |
| `unavailable` | Fetch error or no data for this symbol     | Silent (no line) |

## Session tagging

The bar timestamp is used to tag `source_session`:

| Session   | ET window          |
|-----------|--------------------|
| `regular` | 09:30 – 16:00      |
| `pre`     | 04:00 – 09:30      |
| `post`    | 16:00 – 20:00      |
| `closed`  | anything else      |

Most useful on the **07:00 premarket run**, when pre-market prints can
reflect real overnight news. The postmarket 17:30 run typically just
confirms today's close is still the reference.

## Overwatch telemetry

Two events land on `ow.mef_event` when relevant:

- `price_check_fetch_failed` (severity=warning) — yfinance raised
- `price_check_stale` (severity=warning) — at least one idea hit the
  warn tier this run, with the symbol list in the message

## Config

`config/mef.yaml :: ranker.price_check` (gitignored — defaults below):

```yaml
ranker:
  price_check:
    enabled: true
    info_threshold_pct: 0.01
    warn_threshold_pct: 0.03
```

Set `enabled: false` to skip the yfinance call entirely — useful for
offline testing or network-isolated environments.

## Why not check every symbol up front

- 320 extra quote fetches per run vs. ~5
- Adds an external API to the critical path of every run
- Mixes live pricing into scoring — the engines are deliberately
  deterministic-first over curated SHDB data, and introducing a
  separate upstream dataset would muddy that story

The engines answer *which* stocks are interesting. The price check
answers *whether the plan we're emailing is still live*. Different
jobs, different scope.
