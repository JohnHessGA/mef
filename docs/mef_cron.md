# MEF Cron Setup

Two scheduled runs per trading day deliver MEF's daily emails.

## Entries

```
CRON_TZ=America/New_York

0  7 * * 1-5 cd /home/johnh/repos/mef && /home/johnh/repos/mef/venv/bin/mef run --when premarket  >> /mnt/aftdata/logs/mef/cron.log 2>&1
30 17 * * 1-5 cd /home/johnh/repos/mef && /home/johnh/repos/mef/venv/bin/mef run --when postmarket >> /mnt/aftdata/logs/mef/cron.log 2>&1
```

| Time (ET) | Days  | Command                       | Email intent                          |
|-----------|-------|-------------------------------|---------------------------------------|
| 07:00     | Mon–Fri | `mef run --when premarket`    | Trades for today after 10:00 ET        |
| 17:30     | Mon–Fri | `mef run --when postmarket`   | Trades for the next trading day        |

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
  `email_sent_at`, counts, `notes`)
- one row to `mef.llm_trace` for the gate call
- whatever `mef.candidate` / `mef.recommendation` / `mef.score` rows the
  pipeline produces

So even if the cron log rotates away, the database carries the durable
audit trail.

## Manual control

- **Skip the email but exercise the pipeline:** `mef run --when premarket --dry-run`
- **Render an email body without sending or persisting:** _(milestone 11 — `mef report --when ...`; not yet wired)_
- **Stop scheduled runs temporarily:** `crontab -r` (removes all entries — backup first), or comment out the two MEF lines and `crontab -e` again.

## Sanity check before installing

Run a single dry-run interactively, watch for any errors:

```bash
cd /home/johnh/repos/mef
venv/bin/mef run --when premarket --dry-run
```

Then run a real send once you've confirmed the dry-run output:

```bash
venv/bin/mef run --when premarket
```

Check the recipient's inbox for "MEF pre-market report — YYYY-MM-DD …".
