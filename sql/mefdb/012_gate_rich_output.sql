-- MEF / MEFDB — migration 012: LLM gate rich output.
--
-- Expands the LLM gate's per-candidate output from a single `reason` string
-- to a structured set of fields: summary, strengths[], concerns[], and a
-- bottom-line key_judgment. Driven by the 2026-04-21 prompt rewrite that
-- moved the gate to Opus 4.7 with a thesis-quality / coherence / timing
-- rubric (see docs/mef_llm_gate.md).
--
-- Source of truth for gate output is mef.candidate. mef.recommendation no
-- longer mirrors LLM prose fields — callers join via candidate_uid.
--
-- New columns on mef.candidate:
--   llm_gate_summary       — 1–2 sentence rationale for the decision
--   llm_gate_strengths     — short bullets describing what supports the case
--   llm_gate_concerns      — short bullets describing what weakens the case
--   llm_gate_key_judgment  — one-sentence bottom line (why now / why not)
--
-- Deprecations (left in place, marked via COMMENT):
--   mef.candidate.llm_gate_reason
--     — superseded by llm_gate_summary
--   mef.candidate.llm_gate_issue_type
--     — superseded by llm_gate_concerns; the enum classifier is no longer
--       populated, and the CHECK constraint already permits NULL
--   mef.recommendation.llm_review_color
--     — never actually held a color; candidate table is the source of truth
--   mef.recommendation.llm_review_concern
--     — candidate table is the source of truth
--
-- Idempotent: safe to re-run.

\set ON_ERROR_STOP on

SET search_path TO mef, public;

ALTER TABLE mef.candidate
    ADD COLUMN IF NOT EXISTS llm_gate_summary       TEXT,
    ADD COLUMN IF NOT EXISTS llm_gate_strengths     TEXT[],
    ADD COLUMN IF NOT EXISTS llm_gate_concerns      TEXT[],
    ADD COLUMN IF NOT EXISTS llm_gate_key_judgment  TEXT;

COMMENT ON COLUMN mef.candidate.llm_gate_reason IS
    'DEPRECATED 2026-04-21 — superseded by llm_gate_summary. Populated on historical rows only.';
COMMENT ON COLUMN mef.candidate.llm_gate_issue_type IS
    'DEPRECATED 2026-04-21 — superseded by llm_gate_concerns. Not populated by new code.';
COMMENT ON COLUMN mef.recommendation.llm_review_color IS
    'DEPRECATED 2026-04-21 — mef.candidate.llm_gate_summary is the source of truth. Not populated by new code.';
COMMENT ON COLUMN mef.recommendation.llm_review_concern IS
    'DEPRECATED 2026-04-21 — mef.candidate.llm_gate_concerns is the source of truth. Not populated by new code.';
