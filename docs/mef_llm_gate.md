# MEF LLM Gate

Version: 2026-04-21 (v3 rewrite)
Status: Active design — update when the prompt or disposition vocabulary changes.

The LLM is a **gate**, not an idea generator. The deterministic ranker
decides what's a candidate; the LLM decides whether each candidate is
worth considering now.

This doc captures the gate's philosophy, the v3 prompt structure, the
disposition vocabulary, the rich per-candidate output, the validation
contract, and how to iterate on it.

---

## Why have a gate at all?

The deterministic ranker has no understanding of the world — it scores
features, applies thresholds, and emits the top N. That's enough for a
first pass but it doesn't catch:

- **Internal incoherence** (features, posture, and plan not supporting one another)
- **Trade-shape weaknesses** (a ratio that looks fine in isolation but is wrong for this style of name)
- **Timing / present attractiveness** (a fine company with a poor entry right now)
- **Hidden concerns the ranker didn't price** (under-priced hazard, fragile thesis)

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
| `approve`     | Strong enough to present as a live recommendation now.             | Becomes a `mef.recommendation` row. **Appears in the "New ideas" email section.** |
| `review`      | Shows merit, deserves human inspection, not confident enough to auto-ship. | Becomes a `mef.recommendation` row. **Appears in the "Held for review" email section** with the full LLM rationale. Auto-activates on a matching CSV import. |
| `reject`      | Not sufficiently compelling, coherent, or timely.                  | **Does not** become a recommendation. Audit trail lives on `mef.candidate` (decision + rich output columns). |
| `unavailable` | (Pseudo-disposition.) LLM call failed; fallback only.              | Becomes a recommendation. **Appears in the "New ideas" email section** with a "not reviewed by LLM" warning so an LLM outage doesn't silence MEF entirely. |

The earlier binary (approve/reject) collapsed the "borderline" case
into one or the other; the 3-way preserves it as its own thing. That
matters because borderline ideas are exactly where audit data is most
informative — comparing review-outcomes against approve and reject
distributions tells us whether the LLM's caution is calibrated.

---

## Per-candidate rich output

As of 2026-04-21, each decision carries a structured explanation
instead of a single-sentence reason. The fields, stored on
`mef.candidate`:

| Column                   | Contents                                                  |
|--------------------------|-----------------------------------------------------------|
| `llm_gate_decision`      | `approve` / `review` / `reject` / `unavailable`           |
| `llm_gate_summary`       | 1–2 sentence rationale for the decision                   |
| `llm_gate_strengths`     | Short bullets describing what supports the case (up to 3) |
| `llm_gate_concerns`      | Short bullets describing what weakens the case (up to 3)  |
| `llm_gate_key_judgment`  | One-sentence bottom line: why approve / review / reject **right now** |

### Deprecated fields (kept for migration compatibility)

| Column                                   | Status                                                  |
|------------------------------------------|---------------------------------------------------------|
| `mef.candidate.llm_gate_reason`          | DEPRECATED — superseded by `llm_gate_summary`. Populated on historical rows only. Not written by new code. |
| `mef.candidate.llm_gate_issue_type`      | DEPRECATED — superseded by `llm_gate_concerns`. The 8-value enum classifier is no longer populated; the column's CHECK constraint already permits NULL. |
| `mef.recommendation.llm_review_color`    | DEPRECATED — never actually held a color. `mef.candidate` is the source of truth for gate output; recommendations read via FK join. Not written by new code. |
| `mef.recommendation.llm_review_concern`  | DEPRECATED — same reason. Not written by new code. |

Schema comments on each of these columns reflect the deprecation
(`\d+ mef.candidate` / `\d+ mef.recommendation` shows them).

---

## The prompt

Lives in `src/mef/llm/prompts.py :: GATE_PROMPT_TEMPLATE`.
Version: **v3 (2026-04-21)**. Model: **Opus 4.7**
(`DEFAULT_MODEL = "claude-opus-4-7"` in `src/mef/llm/client.py`).

### Role framing

> *You are a disciplined, conservative reviewer of proposed investment
> candidates. Your task is to determine whether each candidate should be
> approved, held for review, or rejected based only on the information
> provided. Your job is not to generate new ideas, rank a top-pick
> list, or force approvals. It is completely acceptable to return no
> approved ideas in a given run.*

### Nine review principles

1. **Be selective.** High bar for approval.
2. **Judge only the provided evidence.** No browsing, no news, no post-cutoff facts.
3. **Evaluate fit to the intended setup.** Grade against the named posture (see glossary).
4. **Do not confuse a good company with a good opportunity now.** The most load-bearing line.
5. **Focus on coherence.** Features, posture, plan, conclusion should support one another.
6. **Treat hazard flags as already priced.** The ranker has already subtracted `hazard_penalty_total`; don't double-penalize.
7. **Use uncertainty honestly.** Borderline → `review`, never stretch to approve.
8. **Do not force coverage.** Approve none is normal.
9. **Judge candidates independently.** No cross-candidate ranking, no top-pick array.

### Posture glossary

The prompt defines all six postures the ranker can emit:

- **bullish** — trend/continuation, expects positive momentum.
- **value_quality** — cheap + durable, doesn't need strong momentum, but must be investable now.
- **oversold_bouncing** — short-term rebound after recent weakness; some stabilization required.
- **range_bound** — non-trending; tighter timing discipline required.
- **bearish_caution** — fragile structure; should usually lean review/reject.
- **no_edge** — no meaningful setup; should typically be rejected. Its arrival at the gate signals that upstream narrowing may need tightening.

Plus two handling rules:

- **Pullback setups** — when `pullback_setup=true`, a current price above the entry zone is the feature, not a mechanical error.
- **Option candidates** — use the same coherence logic; no options-specific rules in v1.

### Hazard overlay is visible to the LLM

Each candidate line now shows the ranker's hazard decomposition:

```
conviction=0.82 (raw=0.88 − hazard=0.06) hazard_flags=[earn_prox:6-10d]
```

The prompt tells the LLM to treat these as already priced — only
elevate a listed hazard if it still appears materially under-priced.
This kills the failure mode observed on 2026-04-21 where the LLM
re-raised "earnings in 13 days" as a fresh concern on BMY even though
the ranker had already docked its conviction by 0.055 for exactly
that.

### Decision standard

- **approve** — strong enough to present as a live recommendation now
- **review**  — shows merit, worth human inspection, not confident enough to auto-ship
- **reject**  — not sufficiently compelling, coherent, or timely

Plus: *"Use approve sparingly. Use review for borderline but still
interesting cases. Use reject for weak, unclear, contradictory, or
unconvincing cases."*

### What the gate is NOT allowed to do

- ❌ Invent current news, earnings results, or post-cutoff events
- ❌ Browse or claim to have searched
- ❌ Change entry, posture, conviction, stop, target, or time-exit
- ❌ Produce a cross-candidate ranking or top-pick ordering
- ❌ Approve a "maybe" case (must be `review` or `reject`)

### JSON output schema

```json
{
  "reviews": [
    {
      "candidate_id": "C-015041",
      "symbol": "AEP",
      "decision": "approve",
      "summary": "Coherent trend continuation with supportive momentum.",
      "strengths": ["trend support above SMAs", "RS vs SPY +22%"],
      "concerns": ["earnings in 19 days"],
      "key_judgment": "Worth approving — plan is clean and timing is now."
    }
  ]
}
```

---

## How the prompt-volume ceiling works

The ranker narrows the ~320 universe down to **at most 9 candidates**
before the LLM sees anything. The ceiling is set by:

| Knob                       | Location                       | Value (as of 2026-04-21) |
|----------------------------|--------------------------------|--------------------------|
| `conviction_threshold`     | `config/mef.yaml :: ranker`    | 0.5                      |
| `top_n_per_engine`         | `config/mef.yaml :: ranker`    | 3                        |

Max candidates to LLM = `top_n_per_engine × N engines` = 3 × 3 = **9**,
deduplicated by symbol. When engines agree on a name, the effective
count is lower.

The former `max_new_ideas_per_run` knob was removed on 2026-04-21 —
the ranker's per-engine cap + the LLM's high approve bar together
deliver selectivity without an artificial post-LLM truncation.

---

## What changed on 2026-04-21 (v3 rewrite)

Driven by a run comparison on 2026-04-21 that showed the LLM flipping
approve ↔ review dispositions on bit-identical inputs two minutes
apart (DR-000033 vs DR-000034). Three symbols (BMY / MRK / PFE) got
downgraded approve → review between the back-to-back runs, even though
the ranker produced identical features and identical plans. The
sampling-variance source was compounded by prompt vagueness around
"materially conflicts" and a conservative-bias clause without
thresholds.

Changes:

1. **Model** — haiku → **Opus 4.7**. Stronger judgment on nuanced rubric calls.
2. **Role framing** — "disciplined reviewer of investment candidates," thesis-centric language.
3. **Nine explicit review principles** with the "good company ≠ good opportunity now" line load-bearing.
4. **Six-posture glossary** — every ranker posture named with a specific definition.
5. **Hazard overlay surfaced in the candidate line** — `conviction=0.82 (raw=0.88 − hazard=0.06)` plus `hazard_flags`, with prompt language telling the LLM hazards are already priced.
6. **Rich per-candidate output** — `summary` + `strengths[]` + `concerns[]` + `key_judgment` replace the single `reason` string and `issue_type` enum.
7. **Synthesis dropped** — no more cross-candidate top-pick ordering; the LLM judges independently per candidate.
8. **`max_new_ideas_per_run` removed** — both from the prompt and from config.
9. **`issue_type` deprecated** — `concerns[]` carries the signal.
10. **Email** — new `Summary:` / `Strengths:` / `Concerns:` / `Judgment:` block (capped at 2 bullets each) renders for both new-idea and held-for-review sections. Legacy `Reasoning:` stays as a fallback for LLM-unavailable runs and historical recs.

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

Per-candidate dispositions are stamped on `mef.candidate` (see the
schema table above). To browse:

```bash
mef rejections --since 2026-04-01     # all rejects with rationales
mef recommendations --state proposed  # approved + reviewed + waiting
mef show R-NNNNNN                     # full per-rec detail incl. rich gate output
```

---

## How to iterate the prompt

1. **Edit `src/mef/llm/prompts.py`.** Whole body is one Python string.
2. **Keep the JSON example braces escaped** — `{{` `}}` stay literal; everything else is a `.format()` slot.
3. **Test against today's run:**
   ```bash
   mef run --when premarket --dry-run
   ```
   Look for the summary line:
   ```
   gate: available=True approve=1 review=4 reject=0 unavailable=0
   ```
4. **Diff against prior runs.** Every prompt's full text is stored in `mef.llm_trace.prompt_text`.
5. **Watch the audit.** Once `mef gate-audit` has ≥20 settled samples per side, it becomes the authoritative judge.

### When to consider splitting the prompt

The v3 design is one prompt covering all six postures via glossary.
The alternative is **per-posture prompts**, each with posture-specific
evaluation criteria. That's more code and more maintenance — only
worth it once audit data shows the unified prompt is systematically
wrong on one posture and right on others.

---

## Reading the gate-audit output

```bash
mef gate-audit
```

Produces a 4-column table:

| Column        | Source                                              | Question it answers                |
|---------------|-----------------------------------------------------|-------------------------------------|
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

- **Approved win rate > Rejected win rate** → gate is helping
- **Approved P&L/100sh > Rejected P&L/100sh** → gate is selecting better trades, not just safer-looking ones
- **Approved vs SPY > Rejected vs SPY** → gate's calls add value above the benchmark

If the comparison is roughly flat, the gate is adding cost (LLM
latency, occasional outages) without value. If `Approved` and
`Review` look indistinguishable, the LLM is being too cautious. If
`Review` looks like `Reject`, the LLM is correctly catching weak
cases via review.

---

## Reference

- Prompt source: `src/mef/llm/prompts.py`
- Gate orchestration: `src/mef/llm/gate.py`
- LLM client (Claude CLI subprocess): `src/mef/llm/client.py`
- Migration that added the rich-output columns: `sql/mefdb/012_gate_rich_output.sql`
- Audit data model: `mef_audit_model.md`
- Operations workflow: `mef_operations.md`
