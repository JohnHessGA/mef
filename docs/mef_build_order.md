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
| ⏳ next | 5 | LLM review                        | Claude-CLI integration (`mef.llm_trace`), prompt template, batched per-run review of emitted survivors, context + concern fields on each recommendation                  |
|         | 6 | Position tracking                 | `mef import-positions <csv>`, `position_snapshot`, `import_batch`, auto-activation of proposed recs when a matching holding appears                                      |
|         | 7 | Recommendation lifecycle commands | `mef dismiss`, `mef recommendations`, `mef show`, auto-expiration at entry window end, auto-close on holdings disappearance                                              |
|         | 8 | Scoring                           | `mef score`, `mef.score` rows, win/loss/timeout classification, estimated 100-share P&L, SPY + sector-ETF benchmark comparisons                                          |
|         | 9 | Email delivery                    | `notify.py --source MEF`, two scheduled cron entries (pre-market + post-market), real send path with rendered email                                                      |
|         | 10 | Overwatch telemetry              | `ow.mef_run` + `ow.mef_event` tables, fail-silent writes, MEF dashboards in Grafana                                                                                      |
|         | 11 | Tuning + polish                   | Evidence-weight tuning based on scoring history, LLM prompt iteration, richer email formatting, optional `mef.benchmark_snapshot` cache                                  |

Items past #11 (web UI, DAS integration, RSE integration, long-option scoring, broader evidence families) remain explicitly out of scope for v1 — see `docs/README_mef.md` §"Hard Boundaries".

## Status notes

- **Threshold + cap** currently default to `conviction_threshold=0.5`, `max_new_ideas_per_run=5` in `config/mef.yaml` (gitignored). Threshold lowered 0.6→0.5 alongside the LLM gate so more candidates compete for the top-5 presented to the user.
- **Coverage** at last verification: 305/305 stocks and 15/15 ETFs present in `mart.stock_equity_daily` / `mart.stock_etf_daily` as of 2026-04-17.
- **First real run** (DR-000003): 320 symbols evaluated, 158 non-no_edge candidates, 5 emitted (STX, GEV, GLW, KLAC, LITE).

Update this table whenever a milestone flips status.
