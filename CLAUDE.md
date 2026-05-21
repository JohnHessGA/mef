# CLAUDE.md

Working instructions for code assistants in the MEF repo.

For MEF's place in AFT (alongside MDC, UDC, RSE, DAS, IRA Guard, Overwatch), see `~/repos/CLAUDE.md` and `~/repos/notes/` — those are the system-wide references.

## Status

- **Introduced:** 2026-04-19 — first top-level *forecasting/recommendation* application stream in AFT, peer to IRA Guard.
- **Operational since 2026-04-20:** ranker, layered gating, LLM gate, lifecycle, paper/shadow scoring, two-email-per-day rendering. MEFDB populated; cron-driven premarket + postmarket runs.
- **Current focus (2026-05-20→):** major rewrite. The pre-rewrite doc set has been snapshotted into `docs/bu20260520/` and a fresh doc set is being authored under `docs/`. Code is intact and continues to run; spec/policy text is in flight.

## Authoritative design docs

> ⚠ **Doc set is being rewritten (started 2026-05-20).** The previous spec
> set (README_mef, mef_design_spec, mef_layered_gating, mef_price_check,
> mef_audit_model, mef_build_order, mef_cron, mef_llm_gate, mef_operations,
> mef_out_of_scope, plus the legacy `notes/` files) was snapshotted into
> `docs/bu20260520/` as historical reference and is **no longer
> authoritative**. New docs land directly in `docs/` (the `notes/` folder
> was removed — do not re-create it).
>
> Until the new spec lands, treat the code as the source of truth and use
> `docs/bu20260520/` only to recover historical intent. Do **not** edit
> files in `docs/bu20260520/` in place — write fresh docs under `docs/`.

## Hard boundaries (don't cross)

These are load-bearing. Stop and ask before crossing any of them.

1. **Fixed 305+20 universe.** No broad-market screening, no dynamic universe expansion in v1. (Operator-curated bumps — like the 2026-05-05 15→20 ETF expansion adding VUG/SCHG/SPYG/QUAL/ONEQ — are allowed; automated/screen-driven expansion is not. Current membership lives in `mef.universe_stock` / `mef.universe_etf`; the pre-rewrite universe lists are archived under `docs/bu20260520/`.)
2. **No DAS dependency.** DAS does not yet exist; MEF reads SHDB directly. Revisit when DAS is real.
3. **No RSE dependency in v1.** Revisit once RSDB has useful outputs.
4. **No backtesting.** Historical strategy simulation belongs elsewhere (same boundary RSE enforces).
5. **Advisory only.** No broker integration, no automated trade placement.
6. **Only two notifications per trading day.** The pre-market email and the post-market email. No SMS, no per-event pings, no extra channels.
7. **Ranker decides emission; LLM reviews.** The deterministic ranker alone decides whether to emit ideas and how many. The LLM adds color and flags concerns but does not generate candidates or change entry/exit prices.
8. **Lightweight over comprehensive.** If a design choice ships the daily loop sooner at the cost of near-term elegance, ship. This is intentionally a smaller tool than DAS.

## Core engineering principles

1. **Ship the daily loop first.** Resist adding evidence families, schema columns, or UI niceties before the end-to-end loop works. (Historical "minimum-viable loop" notes lived in `docs/mef_design_spec.md` §20 — now `docs/bu20260520/mef_design_spec.md` §20 — pending re-statement in the new doc set.)
2. **Deterministic first, LLM second.** Direct SQL, pandas, pure Python before Claude CLI. Use the LLM only where the design spec says (final review, reasoning text).
3. **Fail-silent telemetry.** Overwatch writes must never block a run or an email.
4. **Rebuild-safe runs + idempotent imports.** MEFDB tables (`recommendation`, `score`, `daily_run`, etc.) are ours and **rebuild-safe** — re-running a builder over the same source window must produce the same derived rows with no duplicates or drift, but the rows themselves are not sacred (drop-and-rebuild from MEF universe + SHDB is fine). Lifecycle transitions are deterministic from inputs. CSV position imports sit at the *boundary* with external data, so file-level dedup (sha256) is genuinely **idempotent** — re-importing the same CSV is a no-op. Don't conflate: idempotency belongs at boundaries, rebuild-safety belongs to derived tables.
5. **Conventional commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`. Matches AFT-wide convention.
6. **Composition over inheritance.** Evidence families, LLM providers, and notification senders are plug-in points, not subclass hierarchies.
7. **The conviction threshold rises with confidence; it never falls to fill the email.** A week — or several weeks in a row — of "No new trades today" is a healthy outcome of a selective system, not a failure of one. The threshold (`config/mef.yaml :: ranker.conviction_threshold`) was lowered from 0.6 → 0.5 once on 2026-04-19 to widen the per-engine candidate pool that reaches the LLM gate, and that one-time move is the limit. From here, the threshold goes UP as scoring history shows what conviction levels actually predict wins — eventually toward 0.7-0.8. If a quiet week creates pressure to lower it again, that pressure is the symptom we are guarding against. Tune confidence measures and the LLM approve bar, not the threshold.

## Environment

- **Python:** 3.12, src layout, editable install via `pyproject.toml` (`pip install -e .`). Runtime deps: `psycopg2-binary`, `pyyaml`, `yfinance` (used by `mef.price_check` for post-emission live quotes).
- **Virtual env:** `~/repos/mef/.venv/` (created with `python3 -m venv .venv`)
- **Host:** WSL2 Ubuntu 24.04 (`codex`) on Windows 11 (`hal64`)
- **Databases:** PostgreSQL 18.3 + TimescaleDB 2.26.4 on `localhost:5432` (upgraded from PG 16 on 2026-05-07; PG 16 retained as stopped rollback copy on :5499)
  - `mefdb` — MEF's own database (schema `mef`, owner `mef_user`) — created and in active use
  - `shdb` — primary data source (read-only, same PG instance)
  - `overwatch` — telemetry (fail-silent writes)
- **Secrets:** `config/postgres.secrets.yaml` (gitignored) with `mefdb`, `shdb`, `overwatch` sections. No env-var fallback for passwords. See `~/repos/notes/secrets-conventions.md`.
- **Application config:** `config/mef.yaml` (gitignored).
- **Data root:** `/mnt/aftdata/` (native ext4 VHDX). MEF generated artifacts (if any) live under `/mnt/aftdata/mef/`.
- **Logs:** `/mnt/aftdata/logs/mef/`.

## CLI surface (target)

| Command | Purpose |
|---|---|
| `mef premarket-run` / `mef postmarket-run` | Execute one scheduled run with email enabled (cron entry points). Sugar for `mef run --when X --send-email`. |
| `mef run [--when {premarket\|postmarket}] [--send-email]` | Run the pipeline manually. `--when` is informational only; the runtime does not branch on it. |
| `mef status` | Environment, DB connectivity, data freshness, last run summary |
| `mef init-db` | Apply MEFDB migrations (idempotent) |
| `mef universe [load]` | Show universe; `load` syncs `mef.universe_stock` / `mef.universe_etf` from the operator-curated universe definitions |
| `mef recommendations [...]` | List recommendations by lifecycle state |
| `mef show <rec-id>` | Detail on a recommendation |
| `mef dismiss <rec-id>` | Mark a proposed recommendation as not-implemented |
| `mef import-positions <csv>` | Ingest a Fidelity Portfolio Positions CSV |
| `mef score` | Re-evaluate closed recommendations and refresh scoring |
| `mef report --when {premarket\|postmarket}` | Render the email body without sending (deprecated; emits a deprecation notice). |

All commands above are implemented as of 2026-04-20.

## MEFDB (schema `mef`)

The v1 tables (pre-rewrite list — re-confirm against migrations and the new spec once it lands; historical narrative in `docs/bu20260520/mef_design_spec.md` §11):

`universe_stock`, `universe_etf`, `daily_run`, `candidate`, `recommendation`,
`recommendation_update`, `import_batch`, `position_snapshot`,
`benchmark_snapshot`, `score`, `shadow_score`, `paper_score`,
`llm_trace`, `command_log`.

UID prefixes: `DR-` daily_run, `C-` candidate, `R-` recommendation, `I-` import_batch, `P-` position_snapshot, `S-` score, `L-` llm_trace.

`mef.candidate` carries the layered-gating decomposition as of migration
011: `raw_conviction`, `hazard_penalty_total`, `hazard_penalty_macro`,
`hazard_penalty_earnings_prox`, `hazard_event_type`, `hazard_flags`,
`selected_pre_llm`, `suppressed_by_hazard`, `eligibility_pass`,
`eligibility_fail_reasons`. `conviction_score` holds the final
(post-overlay) value — selectors compare against it.

Start minimal; add columns only when a concrete caller needs them. (Once the new spec replaces `docs/bu20260520/mef_design_spec.md`, treat it as the read-first reference for DDL or repository code.)

## Build order (historical — pre-rewrite)

The original 10-step build order (`docs/bu20260520/README_mef.md` §"Build Order" + `docs/bu20260520/mef_build_order.md`) carried the v1 system from empty repo through scoring + email polish, and all ten steps shipped. A fresh build order for the major rewrite will land in `docs/` when the new spec does.

1. **Repo & database setup** — repo skeleton, MEFDB + `mef_user`, minimal schema migration, `mef status`
2. **Universe load** — `mef universe load`
3. **Skeleton daily run** — `mef run` executes end-to-end with a dummy ranker, writes `daily_run`, sends email
4. **Evidence & ranker v0** — small deterministic evidence set, simple ranker
5. **LLM review** — Claude CLI integration, `llm_trace`, prompt template
6. **Position tracking** — `mef import-positions`, inference of `active` from holdings
7. **Recommendation lifecycle** — dismiss / expire / auto-close
8. **Scoring** — win/loss/timeout + 100-share P&L + benchmark comparison
9. **Email polish** — real two-section body
10. **Iterate**

## Workflow

- **Verify before commit.** Run `mef --help` and `mef status` (on a real scratch DB) to confirm changes work end-to-end. Don't jump from editing to commit+push — confirm first.
- **Don't regress working features.** Run existing tests plus a representative CLI command.
- **Run the test suite.** `pytest -q` should be fast. Add a test when adding new pure-function logic worth protecting from regression.
- **Prefer editing existing files.** Build up modules per the spec's layout. Don't scatter new files.

## LLM use

(Historical policy from `docs/bu20260520/mef_design_spec.md` §10 — re-statement pending in the new doc set.)

- **Good uses:** final review over ranker candidates, reasoning-summary text in emails, flagging plans that look inconsistent with broader context.
- **Avoid:** generating candidates from scratch, changing entry/exit prices, replacing deterministic ranker thresholds.

Every LLM call is logged to `mef.llm_trace`. Failures do not fail the run — MEF continues with a placeholder reasoning field, and the candidate is presented as "Algorithmic candidates not fully reviewed" rather than as an approved actionable idea.

## Telemetry

Writes to the `overwatch` database (tables created when needed):

- `ow.mef_run` — one row per `mef run` completion/failure
- `ow.mef_event` — discrete events (info/warning/error)

Fail-silent.

## Notifications

Route via MDC's `notify.py --source MEF`. **Only** the two scheduled daily emails — no other notifications.

## Legacy context

MEF has no predecessor inside AFT. It borrows patterns from IRA Guard (CSV ingest, advisory-only), RSE (docs structure, LLM-trace logging, telemetry), and MDC/UDC (CLI shape, config/secrets, src layout). It does **not** inherit from the retired XPM tool — reference RSE going forward.

## Where to dig deeper

| Topic | Location |
|---|---|
| Pre-rewrite build spec (historical) | `docs/bu20260520/README_mef.md` |
| Pre-rewrite design spec (historical) | `docs/bu20260520/mef_design_spec.md` |
| Pre-rewrite layered gating (historical) | `docs/bu20260520/mef_layered_gating.md` |
| New doc set (in-progress, 2026-05-20→) | `docs/` (excluding `bu20260520/`) |
| System-wide conventions | `~/repos/notes/conventions.md` |
| Database catalog | `~/repos/notes/databases.md` |
| AFT architecture overview | `~/repos/CLAUDE.md` |
