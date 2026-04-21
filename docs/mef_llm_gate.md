# MEF LLM Gate

Version: 2026-04-21
Status: Active design — update when the prompt or disposition vocabulary changes.

The LLM is a **gate**, not an idea generator. The deterministic ranker
decides what's a candidate; the LLM decides whether each candidate is
coherent enough to ship.

This doc captures the gate's philosophy, the v2 prompt structure, the
disposition vocabulary, the `issue_type` taxonomy, the validation
contract, and how to iterate on it.

---

## Why have a gate at all?

The deterministic ranker has no understanding of the world — it scores
features, applies thresholds, and emits the top N. That's enough for a
first pass but it doesn't catch:

- **Mechanical errors** (stop above entry, expression mismatched to posture)
- **Trade-shape weaknesses** (RR ratio that looks fine in isolation but is wrong for this kind of name)
- **Regime mismatches** (bullish setup in a sharply-down market)
- **Durable-knowledge red flags** (gap-prone biotechs, regime-sensitive small-caps)

A conservative LLM reviewer fills that gap **without generating new
ideas of its own**. The boundary is strict: the LLM never changes
prices, posture, conviction, or the ranker's plan. It only decides
whether to ship, hold, or kill the plan as-is.

The gate is also explicitly **falsifiable**. Every rejection is
shadow-scored against subsequent market data (see `mef_audit_model.md`
and `mef gate-audit`), so we can ask the question: "is this LLM
actually helping, or is it removing alpha?"

---

## The 3-way disposition

The gate returns one of:

| Decision      | Meaning                                                            | Effect                                                                 |
|---------------|--------------------------------------------------------------------|------------------------------------------------------------------------|
| `approve`     | Safe to ship as-is.                                                | Becomes a `mef.recommendation` row. **Appears in the email.**          |
| `review`      | Not safe to auto-ship, but not clearly wrong.                      | Becomes a `mef.recommendation` row. **Withheld from the email.** Visible via `mef recommendations --state proposed`. Auto-activates on a matching CSV import. |
| `reject`     | Malformed, structurally weak, or outside the system's comfort zone. | **Does not** become a recommendation. Audit trail lives on `mef.candidate.llm_gate_decision/reason/issue_type`. |
| `unavailable` | (Pseudo-disposition.) LLM call failed; this is a fallback only.    | Becomes a recommendation. **Appears in the email** with a "not reviewed by LLM" warning so an LLM outage doesn't silence MEF entirely. |

The earlier binary (approve/reject) collapsed the "borderline" case
into one or the other; the 3-way preserves it as its own thing. That
matters because borderline ideas are exactly where audit data is most
informative — comparing review-outcomes against approve and reject
distributions tells us whether the LLM's caution is calibrated.

---

## The `issue_type` taxonomy

Every disposition carries an `issue_type` so audits can cluster
decisions by reason class without reading free text.

| `issue_type`            | When to use it                                                                  |
|-------------------------|---------------------------------------------------------------------------------|
| `none`                  | Used on `approve` decisions; no specific concern.                               |
| `mechanical`            | Plan is internally inconsistent (stop above entry, time_exit missing, expression conflicts with posture). |
| `risk_shape`            | Downside too large vs. target; entry near a stretched move; setup too fragile for conservative advisory. |
| `volatility_mismatch`   | `vol_z` extreme for the holding window; recent realized vol unsuitable.         |
| `posture_mismatch`      | Bullish setup in clearly bearish broad-market context (or vice versa).          |
| `asset_structure`       | Sector/industry typically too gap-prone or too noisy for this style of plan.    |
| `options_structure`     | Reserved for future option candidates (currently unused — MEF v1 emits stocks/ETFs only). |
| `missing_context`       | Idea might be valid but essential context isn't visible to the LLM. **The conservative default** — used when the LLM lacks signal to decide. |

The full enum lives in `src/mef/llm/prompts.py :: ALLOWED_ISSUE_TYPES`
and is enforced by:

- A SQL CHECK constraint on `mef.candidate.llm_gate_issue_type`
  (migration `005_gate_review_disposition.sql`)
- Server-side coercion in `llm/gate.py :: _coerce_issue_type`:
  - Unknown value on an `approve` → `none` (most permissive)
  - Unknown value on a `review` or `reject` → `missing_context` (most conservative — flagged as audit-worthy)

---

## The prompt

Lives in `src/mef/llm/prompts.py :: GATE_PROMPT_TEMPLATE`.

Key structural choices:

1. **Strict review order** — mechanical → trade-shape → durable-knowledge → missing-context. Forces the LLM to fail on coherence before reasoning about context, which keeps rejections explainable.

2. **No browsing, no current news** — explicitly forbidden. The LLM judges only what's in the candidate block plus durable, non-current knowledge. Keeps the gate reproducible and prevents drift driven by what the LLM happens to "know" today.

3. **"Approve none" is a valid response** — the prompt explicitly says it's healthy for the gate to approve none on a weak day. Removes the implicit pressure to produce something.

4. **Borderline → review, never approve** — *"Do NOT approve maybe cases; use review or reject."* This rule is what gives the 3-way disposition its discriminating value.

5. **Options handling future-proofed** — the prompt has a section for option candidates already, but MEF v1 only emits stocks/ETFs so it never fires. When options arrive, no prompt change needed.

6. **Pullback-setup special rule** (added 2026-04-21) — each candidate line carries a `pullback_setup=true|false` flag. When true, the ranker has intentionally anchored the entry zone *below* the current close because the stock is at/near its recent peak. The prompt has a dedicated SPECIAL RULE section instructing the LLM to NOT flag the current-price-vs-entry-range gap as a `risk_shape` issue on pullback setups, and to compute risk/reward from the entry-zone midpoint rather than current close. Prevents a false-positive review verdict that surfaced the first time the pullback feature landed (AEP on 2026-04-20 run DR-000017).

7. **Multi-engine aware** (added 2026-04-21) — each candidate line shows per-engine conviction scores (`engines=[trend=0.82 value=0.71 ...]`). A new SPECIAL RULE FOR MULTI-ENGINE CANDIDATES section tells the LLM that engine agreement is signal and disagreement is context (not a rejection — each engine's best pick may legitimately not interest the others). Output schema adds a `synthesis` array — the LLM's ordered top-picks across all engines, bounded by `max_new_ideas`. Only symbols it approved are valid in synthesis; the parser drops any that disagree. Empty synthesis is valid ("no new trades today").

8. **JSON-only output** — strict output schema with `reviews` array and `synthesis` array (empty when the prompt is single-engine or when the LLM declines to synthesize).

The candidate block is rendered by `render_candidates_block()` and
includes the `candidate_id` (e.g. `C-002881`) so the LLM's response
can be matched back even if it reorders or drops symbols. The block
surfaces the full set of signals the ranker weighs: `pullback_setup`,
`days_to_earnings` (integer, days from bar_date to
`next_earnings_date`; `n/a` when no upcoming announcement is on file),
close, `return_5d` / `return_20d` / `return_63d` / `return_252d`,
RSI14, MACD histogram, SMA20 slope, `rv20/rv63` vol ratio,
`rs_vs_spy_63d`, `rs_vs_qqq_63d`, drawdown, `vol_z`, sector, and the
draft plan. Keeping the LLM's view aligned with the ranker's scoring
inputs stops the LLM from commenting on a strictly smaller feature
set than the one that actually produced the conviction score.

Note that ideas with `days_to_earnings ≤ 5` (or ≤ 10 on pullback
setups) never reach the gate — the ranker vetos them to `no_edge`
before emission. The LLM only sees `days_to_earnings` values on ideas
that cleared the hard veto, so a value of 12 or 18 is the expected
range when this field carries a number.

---

## What the gate is NOT allowed to do

These are hard rules in the prompt:

- ❌ Invent current news, earnings results, or post-cutoff events
- ❌ Browse or claim to have searched
- ❌ Change the entry price, posture, conviction, stop, target, or time-exit
- ❌ Suggest an alternative plan
- ❌ Approve a "maybe" case (must be `review` or `reject`)

If the LLM ignores these rules, the response parser still works
(unknown fields are dropped) but the issue_type coercion catches the
rest. If you see persistent rule violations in `mef.llm_trace`, that's
a signal to tighten the prompt wording.

---

## How calls are logged

Every gate call writes one row to `mef.llm_trace`:

| Column          | Contents                                                          |
|-----------------|-------------------------------------------------------------------|
| `uid`           | `L-NNNNNN`                                                         |
| `run_uid`       | The parent `daily_run`                                             |
| `provider`      | `claude-cli`                                                       |
| `model`         | Whatever Claude CLI reports                                        |
| `prompt_text`   | Full prompt sent (large)                                           |
| `response_text` | Full raw response (pre-parse)                                      |
| `elapsed_ms`    | Wall-clock duration                                                |
| `status`        | `ok` / `error` / `timeout`                                         |
| `error_text`    | Set when status != ok                                              |

Per-candidate dispositions are stamped on `mef.candidate`:

| Column                | Contents                                                  |
|-----------------------|-----------------------------------------------------------|
| `llm_gate_decision`   | `approve` / `review` / `reject` / `unavailable`           |
| `llm_gate_issue_type` | One of the 8 enum values                                  |
| `llm_gate_reason`     | One-sentence free text from the LLM                       |

To browse what the gate has been doing:

```bash
mef rejections --since 2026-04-01     # all rejects with reasons
mef recommendations --state proposed  # everything approved-or-reviewed and waiting
mef show R-NNNNNN                     # full per-rec detail incl. gate fields
```

---

## How to iterate the prompt

The prompt is the most-tunable surface in the gate. Iteration cycle:

1. **Edit `src/mef/llm/prompts.py`.** Whole prompt body is one Python string.

2. **Make sure the curly braces stay escaped.** The literal `{}` in the JSON example must remain `{{ }}` — the Python `.format()` call reads the rest as substitution slots (`{n_candidates}`, `{as_of_date}`, etc).

3. **Make sure `ALLOWED_ISSUE_TYPES` and the SQL CHECK constraint stay in sync** if you change the issue_type enum. The constraint name is `candidate_llm_gate_issue_type_chk` (in `005_gate_review_disposition.sql`) — adding or removing values requires a new migration.

4. **Test against today's run:**
   ```bash
   mef run --when premarket --dry-run
   ```
   This exercises the full pipeline without sending. Look at the
   summary line:
   ```
   gate: available=True approve=1 review=4 reject=0 unavailable=0
   ```

5. **Diff against prior runs.** Every prompt's full text is stored in `mef.llm_trace.prompt_text`, so you can correlate prompt changes with disposition shifts later.

6. **Watch the audit.** Once `mef gate-audit` has signal-grade samples (~20+ settled outcomes per side), it's the authoritative judge of whether a prompt change is helping. Until then, judge by output coherence.

### When to consider splitting the prompt

The current design is one prompt with a strict review order. The
alternative is **per-posture prompts** (one for `bullish`, one for
`bearish_caution`, etc.), each with posture-specific evaluation
criteria. That's more code and more maintenance — only worth it once
audit data shows the unified prompt is systematically wrong on one
posture and right on others.

---

## Reading the gate-audit output

```bash
mef gate-audit
```

Produces a 4-column table:

| Column        | Source                                      | Question it answers                       |
|---------------|---------------------------------------------|-------------------------------------------|
| Approved      | `mef.paper_score WHERE gate_decision='approve'`     | What does the LLM say "yes" to?    |
| Review        | `mef.paper_score WHERE gate_decision='review'`      | What does the LLM say "maybe" to?  |
| Rejected      | `mef.shadow_score` (rejects never get a rec)        | What does the LLM say "no" to?     |
| Unavailable   | `mef.paper_score WHERE gate_decision='unavailable'` | What ships when the gate is down?  |

Both sides use the **same forward-walk methodology** (close-of-run-day
entry, `classify_walk()` outcome rule), so the comparison is fair.

The headline diff (Approved minus Rejected) is **withheld** until both
sides cross `MIN_SAMPLE_FOR_SIGNAL = 20`. Below that the report says
"Sample insufficient" and prints the raw rows only.

What good outcomes look like once the sample matures:

- **Approved win rate > Rejected win rate** by a clear margin → gate is helping
- **Approved P&L/100sh > Rejected P&L/100sh** → gate is selecting better trades, not just safer-looking ones
- **Approved vs SPY > Rejected vs SPY** → gate's calls add value above the benchmark

If the comparison is roughly flat, the gate is adding cost (LLM
latency, occasional outages) without value — and we should either
tighten the prompt or revisit whether to keep it. If `Approved` and
`Review` look indistinguishable, the LLM is being too cautious and
we can promote `review` cases to `approve`. If `Review` looks like
`Reject`, the LLM is correctly catching weak cases via review.

---

## Reference

- Prompt source: `src/mef/llm/prompts.py`
- Gate orchestration: `src/mef/llm/gate.py`
- LLM client (Claude CLI subprocess): `src/mef/llm/client.py`
- Migration that added 3-way + issue_type: `sql/mefdb/005_gate_review_disposition.sql`
- Audit data model: `mef_audit_model.md`
- Operations workflow: `mef_operations.md`
