"""Pin the unavailable-routing contract for Actionable Stock Ideas.

After the 2026-05-20 presentation cleanup:

* ``approve``     → recommendation row, ``should_email=True``, renders in
                    the "New ideas" section.
* ``review``      → recommendation row, ``should_email=False``, renders in
                    the dedicated "Held for review" section.
* ``reject``      → no recommendation row (candidate + llm_trace only).
* ``unavailable`` → recommendation row (lifecycle survives), ``should_email
                    =False``, renders in its own "Algorithmic candidates not
                    fully reviewed" subsection — never in New ideas.

When zero ideas are approved, the email body must clearly say
"No approved new stock ideas today." instead of fudging the wording.

These tests guard against a regression where an LLM-gate outage gets
silently presented as an approved actionable idea.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pytest

from mef.email_render import render_daily_email
from mef.llm.gate import GateDecision, GateResult
from mef import run_pipeline as rp


# ─────────────────────────────────────────────────────────────────────────
# Fixtures / fakes
# ─────────────────────────────────────────────────────────────────────────


def _time():
    return datetime(2026, 5, 20, 12, 30, tzinfo=timezone.utc)


def _idea(**kwargs) -> dict[str, Any]:
    base: dict[str, Any] = {
        "rec_uid":    "R-000001",
        "symbol":     "AAPL",
        "asset_kind": "stock",
        "posture":    "bullish",
        "expression": "buy_shares",
        "entry_zone": "$270-$275",
        "stop":       260.00,
        "target":     295.00,
        "time_exit":  date(2026, 6, 19),
        "potential_gain_100sh": 2500.00,
        "potential_loss_100sh": 1000.00,
        "risk_reward":          2.5,
        "reasoning_summary":    "coherent plan; above SMA50/200",
        "llm_gate": "approve",
    }
    base.update(kwargs)
    return base


@dataclass
class _FakeCandidate:
    """Minimal RankedCandidate stand-in — only the attributes
    _insert_recommendations actually reads."""
    symbol: str
    engine: str = "trend"
    asset_kind: str = "stock"
    posture: str = "bullish"
    conviction_score: float = 0.72
    proposed_expression: str | None = "buy_shares"
    proposed_entry_zone: str | None = "$270-$275"
    proposed_stop: float | None = 260.0
    proposed_target: float | None = 295.0
    proposed_time_exit: date | None = date(2026, 6, 19)
    needs_pullback: bool = False
    reasoning_notes: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=lambda: {"close": 272.0})


class _FakeCursor:
    """Records execute() calls without touching a real DB."""
    def __init__(self) -> None:
        self.executes: list[tuple[str, tuple]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executes.append((sql, params))


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1


# ─────────────────────────────────────────────────────────────────────────
# Pipeline-level: _insert_recommendations routing
# ─────────────────────────────────────────────────────────────────────────


def _decision(sym: str, kind: str) -> GateDecision:
    return GateDecision(
        symbol=sym,
        decision=kind,
        summary=("ok" if kind != "unavailable" else None),
        strengths=[],
        concerns=[],
        key_judgment=None,
    )


def _gate_result(per_symbol: dict[str, str]) -> GateResult:
    decisions = {sym: _decision(sym, kind) for sym, kind in per_symbol.items()}
    return GateResult(
        decisions=decisions,
        available=all(k != "unavailable" for k in per_symbol.values()),
        llm_trace_uid="L-000001",
        approved=[s for s, k in per_symbol.items() if k == "approve"],
        review=[s for s, k in per_symbol.items() if k == "review"],
        rejected=[s for s, k in per_symbol.items() if k == "reject"],
        unavailable=[s for s, k in per_symbol.items() if k == "unavailable"],
        unavailable_kind=("error" if "unavailable" in per_symbol.values() else None),
    )


def test_insert_recommendations_routing_pins_should_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """One per disposition: approve → should_email=True; review and
    unavailable → False; reject → no row at all. Pins the contract that
    drives the email rendering buckets downstream."""
    monkeypatch.setattr(
        rp, "next_uid",
        lambda conn, kind: f"R-{kind[:3].upper()}-NEW",
    )

    survivors = [
        _FakeCandidate(symbol="AAPL"),  # approve
        _FakeCandidate(symbol="TSLA"),  # review
        _FakeCandidate(symbol="NVDA"),  # reject
        _FakeCandidate(symbol="META"),  # unavailable
    ]
    candidate_uid_map = {
        ("trend", "AAPL"): "C-1",
        ("trend", "TSLA"): "C-2",
        ("trend", "NVDA"): "C-3",
        ("trend", "META"): "C-4",
    }
    gate = _gate_result({
        "AAPL": "approve",
        "TSLA": "review",
        "NVDA": "reject",
        "META": "unavailable",
    })

    conn = _FakeConn()
    rows = rp._insert_recommendations(
        conn, run_uid="DR-000001", survivors=survivors,
        candidate_uid_map=candidate_uid_map, gate=gate,
    )

    by_sym = {r["symbol"]: r for r in rows}

    # reject is the only disposition with no recommendation row.
    assert "NVDA" not in by_sym, "rejected ideas must not become recommendations"
    assert set(by_sym) == {"AAPL", "TSLA", "META"}

    # should_email is approve-only — the field that gates "New ideas".
    assert by_sym["AAPL"]["should_email"] is True
    assert by_sym["TSLA"]["should_email"] is False
    assert by_sym["META"]["should_email"] is False

    # llm_gate is preserved so the renderer can route review vs unavailable
    # into their respective subsections.
    assert by_sym["AAPL"]["llm_gate"] == "approve"
    assert by_sym["TSLA"]["llm_gate"] == "review"
    assert by_sym["META"]["llm_gate"] == "unavailable"

    # One INSERT per surviving disposition (3, not 4 — reject is skipped).
    assert len(conn.cur.executes) == 3


# ─────────────────────────────────────────────────────────────────────────
# Renderer-level: where each disposition lands in the email body
# ─────────────────────────────────────────────────────────────────────────


def test_approve_renders_in_new_ideas_section() -> None:
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-1", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=20,
        new_ideas=[_idea(symbol="AAPL", llm_gate="approve")],
    )
    body = email.body
    new_idx = body.index("New ideas (1):")
    # The symbol must appear after the "New ideas" header and not in
    # any of the other two buckets.
    assert "AAPL" in body[new_idx:]
    assert "Held for review" not in body
    assert "Algorithmic candidates not fully reviewed" not in body


def test_review_renders_in_held_for_review_section_not_new_ideas() -> None:
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-2", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=20,
        new_ideas=[],
        review_ideas=[_idea(symbol="TSLA", llm_gate="review",
                            reasoning_summary="RSI extended after rally")],
    )
    body = email.body
    assert "Held for review (1)" in body
    review_idx = body.index("Held for review (1)")
    # TSLA must appear under Held for review, not before it.
    assert "TSLA" in body[review_idx:]
    assert "TSLA" not in body[:review_idx]
    # And the "New ideas" section must say no approved ideas.
    assert "No approved new stock ideas today." in body


def test_unavailable_does_not_appear_as_new_idea() -> None:
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-3", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=20,
        new_ideas=[],
        unavailable_ideas=[_idea(symbol="META", llm_gate="unavailable")],
        llm_gate_available=False,
        llm_gate_unavailable_kind="error",
    )
    body = email.body
    # The "No approved" sentinel must render — an LLM outage is not an
    # approved actionable idea.
    assert "No approved new stock ideas today." in body
    # META must appear only in the dedicated subsection, never before it.
    section_header = "Algorithmic candidates not fully reviewed (1)"
    assert section_header in body
    section_idx = body.index(section_header)
    assert "META" in body[section_idx:]
    assert "META" not in body[:section_idx]
    # And per-idea "Not reviewed by LLM" inline marker still fires so the
    # row is unmistakable even when read out of context.
    assert "Not reviewed by LLM" in body


def test_no_approved_message_when_only_reject_review_unavailable() -> None:
    """All survivors are non-approved → the email says no approved ideas."""
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-4", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=20,
        new_ideas=[],
        review_ideas=[_idea(symbol="TSLA", llm_gate="review")],
        unavailable_ideas=[_idea(symbol="META", llm_gate="unavailable")],
        llm_gate_rejected=2,
    )
    body = email.body
    assert "No approved new stock ideas today." in body
    # Held-for-review and unavailable subsections still render.
    assert "Held for review (1)" in body
    assert "Algorithmic candidates not fully reviewed (1)" in body
    # Rejected count is logged for audit in the footer.
    assert "2 rejected" in body


def test_unavailable_subsection_omitted_when_empty() -> None:
    """No unavailable ideas → no subsection header at all (avoids
    rendering an empty 'Algorithmic candidates not fully reviewed (0)'
    box on every healthy run)."""
    email = render_daily_email(
        when_kind="premarket", intent="today_after_10am",
        run_uid="DR-5", started_at=_time(),
        stocks_in_universe=305, etfs_in_universe=20,
        new_ideas=[_idea(symbol="AAPL", llm_gate="approve")],
    )
    assert "Algorithmic candidates not fully reviewed" not in email.body
