"""Unit tests for the LLM gate's JSON parsing + response handling.

The gate orchestrator talks to a DB and the Claude CLI, but the pure-
function response parser is exercisable in isolation.
"""

from __future__ import annotations

import pytest

from mef.llm.client import extract_json_block
from mef.llm.gate import _parse_gate_response


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
