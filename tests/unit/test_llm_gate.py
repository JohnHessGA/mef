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


def test_parse_gate_response_happy():
    text = '{"reviews":[{"symbol":"AAPL","decision":"approve","reason":"coherent"},{"symbol":"STX","decision":"reject","reason":"too stretched"}]}'
    out = _parse_gate_response(text)
    assert out == {
        "AAPL": ("approve", "coherent"),
        "STX":  ("reject",  "too stretched"),
    }


def test_parse_gate_response_ignores_unknown_decision():
    text = '{"reviews":[{"symbol":"A","decision":"maybe","reason":"idk"},{"symbol":"B","decision":"approve","reason":""}]}'
    out = _parse_gate_response(text)
    assert "A" not in out                        # maybe is not a valid decision
    assert out["B"] == ("approve", "")


def test_parse_gate_response_missing_reviews_raises():
    with pytest.raises(ValueError):
        _parse_gate_response('{"something_else": []}')


def test_parse_gate_response_reviews_not_list_raises():
    with pytest.raises(ValueError):
        _parse_gate_response('{"reviews": "not a list"}')


def test_parse_gate_response_empty_text_raises():
    with pytest.raises(ValueError):
        _parse_gate_response("")
