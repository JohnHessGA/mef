"""Unit tests for the LLM gate's JSON parsing + response handling.

The gate orchestrator talks to a DB and the Claude CLI, but the pure-
function response parser is exercisable in isolation.
"""

from __future__ import annotations

import pytest

from mef.llm.client import extract_json_block
from mef.llm.gate import _parse_gate_response
from mef.llm.prompts import build_gate_prompt, render_candidates_block


def test_extract_json_block_plain():
    text = '{"reviews": [{"symbol": "AAPL", "decision": "approve", "reason": "ok"}]}'
    assert extract_json_block(text).startswith("{")


def test_extract_json_block_fenced_json():
    text = '```json\n{"reviews": []}\n```'
    assert extract_json_block(text) == '{"reviews": []}'


def test_extract_json_block_fenced_plain():
    text = '```\n{"reviews": []}\n```'
    assert extract_json_block(text) == '{"reviews": []}'


def test_extract_json_block_trailing_prose():
    text = '{"reviews": []}\n\nThank you.'
    # Balanced-brace extraction returns just the JSON object.
    assert extract_json_block(text) == '{"reviews": []}'


def test_parse_gate_response_happy_three_way():
    # Each tuple is (decision, issue_type, reason).
    text = (
        '{"reviews":['
        '{"symbol":"AAPL","decision":"approve","issue_type":"none","reason":"coherent"},'
        '{"symbol":"NVDA","decision":"review","issue_type":"missing_context","reason":"borderline"},'
        '{"symbol":"STX","decision":"reject","issue_type":"risk_shape","reason":"too stretched"}'
        ']}'
    )
    out = _parse_gate_response(text)
    assert out == {
        "AAPL": ("approve", "none", "coherent"),
        "NVDA": ("review", "missing_context", "borderline"),
        "STX":  ("reject", "risk_shape", "too stretched"),
    }


def test_parse_gate_response_ignores_unknown_decision():
    text = (
        '{"reviews":['
        '{"symbol":"A","decision":"maybe","issue_type":"none","reason":"idk"},'
        '{"symbol":"B","decision":"approve","issue_type":"none","reason":""}'
        ']}'
    )
    out = _parse_gate_response(text)
    assert "A" not in out                        # maybe is not a valid decision
    assert out["B"] == ("approve", "none", "")


def test_parse_gate_response_coerces_unknown_issue_type_for_approve():
    # Unknown issue_type on an approve becomes 'none' (most-permissive default).
    text = '{"reviews":[{"symbol":"A","decision":"approve","issue_type":"made_up","reason":"x"}]}'
    out = _parse_gate_response(text)
    assert out["A"] == ("approve", "none", "x")


def test_parse_gate_response_coerces_unknown_issue_type_for_reject():
    # Unknown issue_type on a reject/review becomes 'missing_context' (most-conservative).
    text = '{"reviews":[{"symbol":"A","decision":"reject","issue_type":"weird","reason":"x"}]}'
    out = _parse_gate_response(text)
    assert out["A"] == ("reject", "missing_context", "x")


def test_parse_gate_response_missing_issue_type_uses_safe_default():
    # No issue_type field at all → fall through the same coercion path.
    text = '{"reviews":[{"symbol":"A","decision":"review","reason":"x"}]}'
    out = _parse_gate_response(text)
    assert out["A"] == ("review", "missing_context", "x")


def test_parse_gate_response_missing_reviews_raises():
    with pytest.raises(ValueError):
        _parse_gate_response('{"something_else": []}')


def test_parse_gate_response_reviews_not_list_raises():
    with pytest.raises(ValueError):
        _parse_gate_response('{"reviews": "not a list"}')


def test_parse_gate_response_empty_text_raises():
    with pytest.raises(ValueError):
        _parse_gate_response("")


def _candidate(**kwargs):
    base = {
        "candidate_id": "C-1", "symbol": "AEP", "asset_kind": "stock",
        "posture": "bullish", "conviction_score": 0.76,
        "features": {
            "close": 133.66, "return_20d": 0.038, "rsi_14": 63,
            "macd_histogram": 0.01, "drawdown_current": -0.025,
            "volume_z_score": -0.1, "sector": "Utilities",
        },
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


def test_gate_prompt_includes_pullback_special_rule():
    prompt = build_gate_prompt(
        candidates=[_candidate(needs_pullback=True)],
        as_of_date="2026-04-20",
        spy_return_20d=0.076, spy_return_63d=0.026,
    )
    # The rule's existence matters more than exact wording.
    assert "SPECIAL RULE FOR PULLBACK SETUPS" in prompt
    assert "pullback_setup=true" in prompt
    # Explicitly tells the LLM NOT to flag current-vs-entry gap on pullback setups.
    assert "current price exceeds entry range" in prompt.lower()
