"""Unit tests for the Entry Quality Overlay (Job 1 v1).

Pure tests over ``mef.entry_quality.evaluate_entry_quality``. The five
spec cases below pin the conservative 3-way routing rule: only the
strong-run / weak-R:R / no-pullback intersection demotes a candidate to
'watch'. Each of the three signals alone is intentionally a pass.
"""

from __future__ import annotations

from mef.entry_quality import (
    FLAG_EXTENDED_FROM_SMA200,
    FLAG_NEGATIVE_FCF,
    FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK,
    FLAG_WEAK_RISK_REWARD,
    STATUS_PASS,
    STATUS_WATCH,
    evaluate_entry_quality,
)


# ─────────────────────────────────────────────────────────────────────────
# Plan / feature factories — small helpers so each test reads top-down.
# ─────────────────────────────────────────────────────────────────────────

def _plan(*, entry_lo=58.0, entry_hi=60.0, stop=55.0, target=63.0):
    """Default plan yields entry_mid=59, risk=4, reward=4 → r/r = 1.00."""
    return {
        "entry_zone": f"${entry_lo}-${entry_hi}",
        "stop":       stop,
        "target":     target,
    }


def _features(**overrides):
    base = {
        "close":            60.0,
        "sma_200":          50.0,
        "return_63d":       0.25,    # >20% by default (the strong-run side of the rule)
        "drawdown_current": -0.02,   # > -5% by default (the no-pullback side)
        "free_cash_flow":   500_000_000.0,
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────
# Case 1 — OXY-shape: weak R:R + strong run + no pullback → WATCH
# ─────────────────────────────────────────────────────────────────────────

def test_oxy_shape_routes_to_watch():
    """All three signals trip: r/r = 1.0 (<1.5), return_63d 31.8% (>20%),
    drawdown_current -2% (> -5%). Must route to 'watch'."""
    p = _plan(entry_lo=59.49, entry_hi=60.70, stop=56.45, target=65.56)
    f = _features(return_63d=0.318, drawdown_current=-0.02,
                  free_cash_flow=-1_528_000_000.0)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_WATCH
    assert FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK in eq.flags
    assert eq.summary is not None and "poor entry quality" in eq.summary.lower()
    assert eq.risk_reward is not None and eq.risk_reward < 1.5
    # Display-only flags also surface (informational).
    assert FLAG_WEAK_RISK_REWARD in eq.flags
    assert FLAG_NEGATIVE_FCF in eq.flags


# ─────────────────────────────────────────────────────────────────────────
# Case 2 — High 63d return but good R:R → PASS (don't demote on ran-up alone)
# ─────────────────────────────────────────────────────────────────────────

def test_high_63d_return_but_good_rr_is_pass():
    """return_63d 35%, drawdown_current -2% (no pullback), but R:R 2.5
    (entry_mid=59, risk=4, reward=10). Routing rule must not fire."""
    p = _plan(entry_lo=58.0, entry_hi=60.0, stop=55.0, target=69.0)
    f = _features(return_63d=0.35, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS
    assert FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK not in eq.flags
    assert FLAG_WEAK_RISK_REWARD not in eq.flags
    assert eq.risk_reward is not None and eq.risk_reward >= 1.5


# ─────────────────────────────────────────────────────────────────────────
# Case 3 — Weak R:R but no strong 63d run → PASS (don't demote on R:R alone)
# ─────────────────────────────────────────────────────────────────────────

def test_weak_rr_but_no_strong_runup_is_pass():
    """R:R 1.0 (weak), return_63d 8% (<20%). Routing must not fire even
    though WEAK_RISK_REWARD display flag surfaces."""
    p = _plan()                          # default 1.0 r/r
    f = _features(return_63d=0.08, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS
    assert FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK not in eq.flags
    assert FLAG_WEAK_RISK_REWARD in eq.flags   # informational, not routing


# ─────────────────────────────────────────────────────────────────────────
# Case 4 — Weak R:R + strong run BUT real pullback → PASS
# ─────────────────────────────────────────────────────────────────────────

def test_weak_rr_strong_runup_but_real_pullback_is_pass():
    """drawdown_current = -8% (deeper than -5%). The "no pullback" leg
    fails, so the routing rule must not fire."""
    p = _plan()                          # 1.0 r/r
    f = _features(return_63d=0.30, drawdown_current=-0.08)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS
    assert FLAG_STRONG_RUN_WEAK_RR_NO_PULLBACK not in eq.flags


# ─────────────────────────────────────────────────────────────────────────
# Case 5 — Drawdown right at the boundary (-0.05) → PASS (strict > floor)
# ─────────────────────────────────────────────────────────────────────────

def test_drawdown_exactly_at_boundary_is_pass():
    """The spec uses strict > -0.05 (i.e. 'less than 5% pullback').
    A drawdown of exactly -0.05 satisfies <= -0.05 and so does NOT fire."""
    p = _plan()
    f = _features(return_63d=0.30, drawdown_current=-0.05)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS


# ─────────────────────────────────────────────────────────────────────────
# Boundary case — return_63d exactly at 20% → PASS (strict > threshold)
# ─────────────────────────────────────────────────────────────────────────

def test_return_63d_exactly_at_threshold_is_pass():
    p = _plan()
    f = _features(return_63d=0.20, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS


# ─────────────────────────────────────────────────────────────────────────
# Boundary case — risk_reward exactly at 1.5 → PASS (strict <)
# ─────────────────────────────────────────────────────────────────────────

def test_risk_reward_exactly_at_threshold_is_pass():
    # entry_mid=59, stop=55, target=65 → risk=4, reward=6, r:r=1.5
    p = _plan(stop=55.0, target=65.0)
    f = _features(return_63d=0.30, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.risk_reward == 1.5
    assert eq.status == STATUS_PASS


# ─────────────────────────────────────────────────────────────────────────
# Degradation — missing plan/data must not crash; defaults to PASS.
# ─────────────────────────────────────────────────────────────────────────

def test_no_plan_returns_pass_without_crash():
    """Entry Quality Overlay is a demoter, not a sanity gate. When the
    plan is missing the verdict is 'pass' so the candidate is not
    silently demoted on a data gap."""
    f = _features(return_63d=0.30, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone=None, stop=None, target=None, features=f,
    )
    assert eq.status == STATUS_PASS
    assert eq.risk_reward is None


def test_unparseable_entry_zone_returns_pass():
    f = _features(return_63d=0.30, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone="around 58", stop=55.0, target=63.0, features=f,
    )
    assert eq.status == STATUS_PASS
    assert eq.risk_reward is None


def test_missing_features_returns_pass():
    p = _plan()
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"],
        features={},
    )
    assert eq.status == STATUS_PASS


def test_non_positive_risk_returns_pass_without_crash():
    """If stop is at or above entry_mid (degenerate plan), risk_reward is
    None and the rule must not fire — even on a 'qualifying' return/dd."""
    p = _plan(entry_lo=58.0, entry_hi=60.0, stop=60.0, target=65.0)
    f = _features(return_63d=0.30, drawdown_current=-0.02)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.risk_reward is None
    assert eq.status == STATUS_PASS


# ─────────────────────────────────────────────────────────────────────────
# Display-only flags — surface independently of the routing rule.
# ─────────────────────────────────────────────────────────────────────────

def test_extended_from_sma200_is_display_only():
    """+27% extension above SMA200 is the OXY case, but on its own it
    must NOT route to watch — the v1 rule is the three-way intersection."""
    p = _plan(entry_lo=58.0, entry_hi=60.0, stop=55.0, target=72.0)  # r/r = 3.25, no demote
    f = _features(close=60.0, sma_200=47.0,
                  return_63d=0.10, drawdown_current=-0.20)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS
    assert FLAG_EXTENDED_FROM_SMA200 in eq.flags


def test_negative_fcf_is_display_only():
    """Negative FCF alone does NOT demote — per the RSE finding."""
    p = _plan(entry_lo=58.0, entry_hi=60.0, stop=55.0, target=72.0)  # good r/r
    f = _features(return_63d=0.10, free_cash_flow=-1_000_000_000.0)
    eq = evaluate_entry_quality(
        entry_zone=p["entry_zone"], stop=p["stop"], target=p["target"], features=f,
    )
    assert eq.status == STATUS_PASS
    assert FLAG_NEGATIVE_FCF in eq.flags


# ─────────────────────────────────────────────────────────────────────────
# Boundary discipline — module must not import LLM/CIA/network code.
# ─────────────────────────────────────────────────────────────────────────

def test_module_has_no_llm_cia_or_network_imports():
    import ast
    import mef.entry_quality as eq_mod
    tree = ast.parse(open(eq_mod.__file__).read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for prefix in ("mef.llm", "mef.cia", "anthropic", "requests", "urllib"):
        assert not any(m.startswith(prefix) for m in imported), (
            f"entry_quality.py must not import {prefix!r}"
        )
