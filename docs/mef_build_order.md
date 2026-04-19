# MEF Build Order

Version: 2026-04-19

Living checklist of MEF build milestones. Mirrors `docs/README_mef.md`
§"Build Order" and `docs/mef_design_spec.md` §20; updated as milestones
land so any future reader can see where we are without grepping commits.

| Status  | # | Milestone                         | Key deliverables                                                                                                                                                         |
|---------|--:|-----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| ✅ done | 1 | Repo + database setup             | `~/repos/mef/` skeleton, MEFDB + `mef_user`, `sql/mefdb/001_schema_and_core_tables.sql` (12 tables), `mef status`, `mef init-db`                                         |
| ✅ done | 2 | Universe load                     | `mef.universe_stock` (305) and `mef.universe_etf` (15); idempotent loader from the `notes/` markdown files; `mef universe show` + `mef universe load`                    |
| ✅ done | 3 | Skeleton daily run                | `mef run --when {premarket\|postmarket}`, `daily_run` row, rendered email body, UID generator, per-run email layout                                                      |
| ✅ done | 4 | Evidence pull + ranker v0         | `mef.evidence` reads `mart.stock_equity_daily` + `mart.stock_etf_daily`; `mef.ranker` writes `candidate` rows and promotes survivors to `recommendation` state `proposed` |
| ✅ done | 5 | LLM gate                          | Claude-CLI integration (`mef.llm_trace`), approve/reject prompt, `mef.candidate.llm_gate_decision` + `llm_gate_reason` audit trail, fallback on LLM failure               |
| ✅ done | 6 | Position tracking                 | `mef import-positions <csv>`, sha256-deduped `mef.import_batch`, per-position `position_snapshot`, auto-activation of proposed recs when a matching holding appears       |
| ✅ done | 7 | Recommendation lifecycle commands | `mef dismiss`, `mef recommendations`, `mef show`, auto-expiration at entry window end, auto-close-on-disappearance with win/loss/timeout classification from last known price |
| ✅ done | 8 | Scoring                           | `mef score`, `mef.score` rows, estimated 100-share P&L, SPY + sector-ETF benchmark comparisons, refined outcome classification, plus `mef rejections` audit command       |
| ✅ done | 9 | Email delivery                    | Direct SMTP via `smtplib` (uses MDC's `notifications.yaml` for credentials, MEF's own recipients), `--dry-run` flag for preview, two-entry cron template at `cron/mef.cron`, install docs at `docs/mef_cron.md`. **Not** via notify.py — that script forces its own subject/body wrapper which would mangle MEF's two-section daily report. |
| ⏳ next | 10 | Overwatch telemetry              | `ow.mef_run` + `ow.mef_event` tables, fail-silent writes, MEF dashboards in Grafana                                                                                      |
|         | 11 | Tuning + polish                   | Evidence-weight tuning based on scoring history, LLM prompt iteration, richer email formatting, optional `mef.benchmark_snapshot` cache                                  |

Items past #11 (web UI, DAS integration, RSE integration, long-option scoring, broader evidence families) remain explicitly out of scope for v1 — see `docs/README_mef.md` §"Hard Boundaries".

## Status notes

- **Threshold + cap** currently default to `conviction_threshold=0.5`, `max_new_ideas_per_run=5` in `config/mef.yaml` (gitignored). Threshold lowered 0.6→0.5 alongside the LLM gate so more candidates compete for the top-5 presented to the user.
- **Coverage** at last verification: 305/305 stocks and 15/15 ETFs present in `mart.stock_equity_daily` / `mart.stock_etf_daily` as of 2026-04-17.
- **First real run** (DR-000003): 320 symbols evaluated, 158 non-no_edge candidates, 5 emitted (STX, GEV, GLW, KLAC, LITE).

Update this table whenever a milestone flips status.
