# MEF Cron Setup

Two scheduled runs per trading day refresh MEF's recommendations in MEFDB and
send a daily email.

## Entries (canonical form)

```
CRON_TZ=America/New_York

0  7 * * 1-5  /home/johnh/repos/mef/scripts/cron_run.sh premarket-run   >> /mnt/aftdata/logs/mef/cron.log 2>&1
45 17 * * 1-5 /home/johnh/repos/mef/scripts/cron_run.sh postmarket-run  >> /mnt/aftdata/logs/mef/cron.log 2>&1
```

| Time (ET) | Days    | Command            | Outcome |
|-----------|---------|--------------------|--------------------------------------|
| 07:00     | Mon–Fri | `premarket-run`    | Refreshes MEFDB. Email sent.         |
| 17:45     | Mon–Fri | `postmarket-run`   | Refreshes MEFDB. Email sent.         |

`premarket-run` and `postmarket-run` are sugar for `mef run --when X
--send-email` — each subcommand sets both `when` and `send_email=True`.
Plain `mef run` does not send unless `--send-email` is passed; its
`--when` flag is informational and the runtime does not branch on it.

`scripts/cron_run.sh` is pure plumbing (sets working dir, activates the
venv, `exec`s `mef "$@"`) and matches the AFT-wide cron convention
(see `~/repos/CLAUDE.md` → Scheduling).

### History note: `email_sent_at` NULL gap (2026-05-07 onward)

`mef.daily_run.email_sent_at` is NULL on every run since DR-000065
(2026-05-07 07:00). This is **not** a runtime gate — it's two separate
causes layered together:

1. DR-000065 itself was a `mef run --when premarket` cron line that
   pre-dated commit `c97d5e0`, which introduced the `premarket-run` /
   `postmarket-run` subcommands. The default for plain `mef run` had
   been flipped to opt-in `--send-email` in `6a5011a` (2026-05-06), so
   that run correctly skipped email.
2. The cron line was later updated to `premarket-run` (would have
   emailed), but **the entire app-stream cron block was paused around
   2026-05-18 for perf-work and has not been restored**. The handful
   of rows DR-000066–069 are manual ad-hoc invocations, not cron.

When cron is restored from `cron/mef.cron`, both `premarket-run` and
`postmarket-run` will populate `email_sent_at` on each fire.

## Install

```bash
crontab -e
# paste the lines from cron/mef.cron, save and quit
crontab -l | grep mef
```

Confirm `CRON_TZ` is `America/New_York`. If it isn't, the times above
will fire in UTC (or your shell's locale) instead.

## Logs

Each invocation appends to `/mnt/aftdata/logs/mef/cron.log`. Rotate via
`logrotate` if it grows.

`mef run` itself also writes:

- one row to `mef.daily_run` (`status`, `started_at`, `ended_at`,
  `email_sent_at` (NULL when email send is off), counts, `notes`)
- one row to `mef.llm_trace` for the gate call
- whatever `mef.candidate` / `mef.recommendation` / `mef.score` rows the
  pipeline produces

So even if the cron log rotates away, the database carries the durable
audit trail.

## Manual control

- **Run the pipeline interactively (no email):** `mef run`
- **Run the pipeline and ship the email:** `mef run --send-email`
- **View the latest result without re-running:** `mef status`
- **Stop scheduled runs temporarily:** comment out the two MEF lines in
  `crontab -e`. Avoid `crontab -r` — that removes every cron entry.

## Sanity check before installing

```bash
cd /home/johnh/repos/mef
.venv/bin/mef run                  # writes to MEFDB, no email
.venv/bin/mef status               # show what it produced
```

Watch for any errors in the run output. To verify SMTP delivery once,
run:

```bash
.venv/bin/mef run --send-email
```

Check the recipient's inbox for "MEF post-market report — YYYY-MM-DD …".
