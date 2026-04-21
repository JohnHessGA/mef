"""Unit tests for the LLM gate's JSON parsing + response handling.

The gate orchestrator talks to a DB and the Claude CLI, but the pure-
function response parser is exercisable in isolation.
"""

from __future__ import annotations

import pytest

from mef.llm.client import extract_json_block
from mef.llm.gate import _parse_gate_response
from mef.llm.prompts import build_gate_prompt, render_candidates_block


# ─────────────────────────────────────────────────────────────────────────
# JSON envelope extraction
# ─────────────────────────────────────────────────────────────────────────

def test_extract_json_block_plain():
    text = '{"reviews": [{"symbol": "AAPL", "decision": "approve", "summary": "ok"}]}'
    assert extract_json_block(text).startswith("{")


def test_extract_json_block_fenced_json():
    text = '```json\n{"reviews": []}\n```'
    assert extract_json_block(text) == '{"reviews": []}'


def test_extract_json_block_fenced_plain():
    text = '```\n{"reviews": []}\n```'
    assert extract_json_block(text) == '{"reviews": []}'


def test_extract_json_block_trailing_prose():
    text = '{"reviews": []}\n\nThank you.'
    assert extract_json_block(text) == '{"reviews": []}'


# ─────────────────────────────────────────────────────────────────────────
# _parse_gate_response — new rich-output schema
# ─────────────────────────────────────────────────────────────────────────

def test_parse_gate_response_happy_three_way():
    text = (
        '{"reviews":['
        '{"symbol":"AAPL","decision":"approve",'
        '"summary":"clean setup","strengths":["trend","rs"],'
        '"concerns":[],"key_judgment":"ship"},'
        '{"symbol":"NVDA","decision":"review",'
        '"summary":"borderline","strengths":["oversold"],'
        '"concerns":["vol"],"key_judgment":"human eyes"},'
        '{"symbol":"STX","decision":"reject",'
        '"summary":"bad shape","strengths":[],'
        '"concerns":["rr","drawdown"],"key_judgment":"pass"}'
        ']}'
    )
    out = _parse_gate_response(text)
    assert out["AAPL"]["decision"] == "approve"
    assert out["AAPL"]["summary"] == "clean setup"
    assert out["AAPL"]["strengths"] == ["trend", "rs"]
    assert out["AAPL"]["concerns"] == []
    assert out["AAPL"]["key_judgment"] == "ship"

    assert out["NVDA"]["decision"] == "review"
    assert out["NVDA"]["strengths"] == ["oversold"]
    assert out["NVDA"]["concerns"] == ["vol"]

    assert out["STX"]["decision"] == "reject"
    assert out["STX"]["concerns"] == ["rr", "drawdown"]


def test_parse_gate_response_caps_bullets_at_three():
    # The parser caps strengths/concerns at 3 each — email renders a tighter 2.
    text = (
        '{"reviews":[{"symbol":"A","decision":"approve",'
        '"summary":"ok",'
        '"strengths":["a","b","c","d","e"],'
        '"concerns":["w","x","y","z"],'
        '"key_judgment":"go"}]}'
    )
    out = _parse_gate_response(text)
    assert out["A"]["strengths"] == ["a", "b", "c"]
    assert out["A"]["concerns"] == ["w", "x", "y"]


def test_parse_gate_response_ignores_unknown_decision():
    text = (
        '{"reviews":['
        '{"symbol":"A","decision":"maybe","summary":"idk",'
        '"strengths":[],"concerns":[],"key_judgment":"?"},'
        '{"symbol":"B","decision":"approve","summary":"x",'
        '"strengths":[],"concerns":[],"key_judgment":"y"}'
        ']}'
    )
    out = _parse_gate_response(text)
    assert "A" not in out
    assert out["B"]["decision"] == "approve"


def test_parse_gate_response_coerces_missing_fields_to_defaults():
    # The LLM returns the minimum required fields; missing strengths/
    # concerns are coerced to [] rather than blowing up.
    text = (
        '{"reviews":[{"symbol":"A","decision":"review","summary":"x"}]}'
    )
    out = _parse_gate_response(text)
    assert out["A"]["decision"] == "review"
    assert out["A"]["summary"] == "x"
    assert out["A"]["strengths"] == []
    assert out["A"]["concerns"] == []
    assert out["A"]["key_judgment"] is None


def test_parse_gate_response_coerces_non_string_bullets():
    # Defensive: if the LLM emits a number or object in a bullet slot,
    # the parser drops it rather than polluting downstream text.
    text = (
        '{"reviews":[{"symbol":"A","decision":"approve","summary":"x",'
        '"strengths":["real bullet", 42, null, {"nope":1}, "another"],'
        '"concerns":[], "key_judgment":"go"}]}'
    )
    out = _parse_gate_response(text)
    assert out["A"]["strengths"] == ["real bullet", "another"]


def test_parse_gate_response_missing_reviews_raises():
    with pytest.raises(ValueError):
        _parse_gate_response('{"something_else": []}')


def test_parse_gate_response_reviews_not_list_raises():
    with pytest.raises(ValueError):
        _parse_gate_response('{"reviews": "not a list"}')


def test_parse_gate_response_empty_text_raises():
    with pytest.raises(ValueError):
        _parse_gate_response("")


# ─────────────────────────────────────────────────────────────────────────
# Prompt content
# ─────────────────────────────────────────────────────────────────────────

def _candidate(**kwargs):
    base = {
        "candidate_id": "C-1", "symbol": "AEP", "asset_kind": "stock",
        "posture": "bullish", "conviction_score": 0.76,
        "raw_conviction": 0.82, "hazard_penalty_total": 0.06,
        "hazard_flags": ["earn_prox:6-10d"],
        "features": {
            "close": 133.66, "return_20d": 0.038, "rsi_14": 63,
            "macd_histogram": 0.01, "drawdown_current": -0.025,
            "volume_z_score": -0.1, "sector": "Utilities",
        },
        "engine": "trend",
        "proposed_expression": "buy_shares",
        "proposed_entry_zone": "$129.68-$132.30",
        "proposed_stop": 121.90, "proposed_target": 141.68,
        "proposed_time_exit": "2026-05-17",
        "needs_pullback": False,
    }
    base.update(kwargs)
    return base


def test_candidates_block_surfaces_pullback_flag():
    pullback_line = render_candidates_block([_candidate(needs_pullback=True)])
    regular_line = render_candidates_block([_candidate(needs_pullback=False)])
    assert "pullback_setup=true" in pullback_line
    assert "pullback_setup=false" in regular_line


def test_candidates_block_surfaces_hazard_overlay():
    """The LLM must see the ranker's hazard decomposition so it doesn't
    re-raise concerns the ranker already priced."""
    line = render_candidates_block([_candidate()])
    assert "raw=0.82" in line
    assert "hazard=0.06" in line
    assert "earn_prox:6-10d" in line


def test_gate_prompt_covers_all_six_postures():
    """The glossary must name every posture the ranker can produce.
    Otherwise an unnamed posture at the gate triggers ad-hoc interpretation."""
    prompt = build_gate_prompt(
        candidates=[_candidate()],
        as_of_date="2026-04-21",
        spy_return_20d=0.04, spy_return_63d=0.02,
    )
    for posture in (
        "bullish", "value_quality", "oversold_bouncing",
        "range_bound", "bearish_caution", "no_edge",
    ):
        assert posture.lower() in prompt.lower(), f"missing posture: {posture}"


def test_gate_prompt_keeps_pullback_and_options_rules():
    prompt = build_gate_prompt(
        candidates=[_candidate(needs_pullback=True)],
        as_of_date="2026-04-21",
        spy_return_20d=0.04, spy_return_63d=0.02,
    )
    assert "Pullback setups" in prompt
    assert "Option candidates" in prompt


def test_gate_prompt_has_no_synthesis_or_max_cap_instructions():
    """The rewrite drops synthesis ordering and the max_new_ideas cap —
    ranker narrows upstream, LLM judges independently per candidate.
    (The prose still uses the word 'synthesis' to tell the LLM NOT to
    produce one; what matters is the output schema.)"""
    prompt = build_gate_prompt(
        candidates=[_candidate()],
        as_of_date="2026-04-21",
        spy_return_20d=0.04, spy_return_63d=0.02,
    )
    assert '"synthesis"' not in prompt           # no synthesis field in schema
    assert "max_new_ideas" not in prompt
    assert "top-pick" in prompt.lower()          # the "do NOT produce" language
    assert "independently" in prompt.lower()     # per-candidate framing


def test_gate_prompt_instructs_hazard_already_priced():
    prompt = build_gate_prompt(
        candidates=[_candidate()],
        as_of_date="2026-04-21",
        spy_return_20d=0.04, spy_return_63d=0.02,
    )
    assert "already" in prompt.lower() and "priced" in prompt.lower()


def test_gate_prompt_includes_good_company_caveat():
    """The most load-bearing line in the new role framing."""
    prompt = build_gate_prompt(
        candidates=[_candidate()],
        as_of_date="2026-04-21",
        spy_return_20d=0.04, spy_return_63d=0.02,
    )
    assert "good company" in prompt.lower()
    assert "good opportunity now" in prompt.lower()
