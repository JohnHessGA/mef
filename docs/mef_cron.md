# MEF Cron Setup

Two scheduled runs per trading day refresh MEF's recommendations in MEFDB.

**As of 2026-05-06** the email path is **off by default** — cron writes
fresh `daily_run` / `candidate` / `recommendation` rows on every fire,
but does not send email. The operator's daily front door is `mef status`
(see `mef_operations.md`).

## Entries (current — back-compat form)

```
CRON_TZ=America/New_York

0  7 * * 1-5 cd /home/johnh/repos/mef && /home/johnh/repos/mef/venv/bin/mef run --when premarket  >> /mnt/aftdata/logs/mef/cron.log 2>&1
45 17 * * 1-5 cd /home/johnh/repos/mef && /home/johnh/repos/mef/venv/bin/mef run --when postmarket >> /mnt/aftdata/logs/mef/cron.log 2>&1
```

| Time (ET) | Days    | Command                       | Outcome |
|-----------|---------|-------------------------------|--------------------------------------|
| 07:00     | Mon–Fri | `mef run --when premarket`    | Refreshes MEFDB. **No email.**       |
| 17:45     | Mon–Fri | `mef run --when postmarket`   | Refreshes MEFDB. **No email.**       |

The `--when` flag is hidden in `mef --help` and accepted only for cron
back-compat. The runtime no longer treats premarket and postmarket
differently — `mef run` produces the best slate it can from current
data on either fire.

### Recommended next form (when cron is updated)

```
0  7 * * 1-5 cd /home/johnh/repos/mef && /home/johnh/repos/mef/venv/bin/mef run >> /mnt/aftdata/logs/mef/cron.log 2>&1
45 17 * * 1-5 cd /home/johnh/repos/mef && /home/johnh/repos/mef/venv/bin/mef run >> /mnt/aftdata/logs/mef/cron.log 2>&1
```

Both lines call the `mef` CLI directly. The only "wrapper" plumbing is
`cd` for working-directory consistency, the venv-relative binary path,
and `>> log 2>&1` for log redirection — matching the AFT-wide
convention (see `~/repos/CLAUDE.md` → Scheduling).

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
venv/bin/mef run                  # writes to MEFDB, no email
venv/bin/mef status               # show what it produced
```

Watch for any errors in the run output. To verify SMTP delivery once,
run:

```bash
venv/bin/mef run --send-email
```

Check the recipient's inbox for "MEF post-market report — YYYY-MM-DD …".
