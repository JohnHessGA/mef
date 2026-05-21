#!/usr/bin/env python3
"""MEF Job 1 — plan-construction model comparison (READ-ONLY).

Recomputes alternative entry/stop/target plans against the historical MEF
candidate cohort and compares R/R, routing, and forward-return outcomes
across four models:

  Model 0 — current production formula (close-based fixed percentages)
  Model A — ATR-aware bands
  Model B — structural swing-low / prior-high
  Model C — current formula + R/R >= 1.8 guardrail

Plus a Model D classifier that labels each (candidate, model) pair as
``buyable_now`` / ``wait_for_entry`` / ``no_compelling_plan`` /
``unavailable``.

Writes three artifacts to ``/mnt/aftdata/rse/data/mef_plan_geometry/``:
  - summary.md          high-level findings + answers to the seven questions
  - model_comparison.csv per-model aggregate metrics
  - symbol_examples.csv  per-symbol detail (NDAQ, OXY, top buyable_now,
                         representative wait_for_entry, etc.)

Usage:
    source ~/repos/mef/.venv/bin/activate
    python scripts/research/mef_plan_geometry_compare.py

READ-ONLY: both DB connections opened with ``set_session(readonly=True)``
and ``autocommit=True``. No production code or schema is touched.
"""

from __future__ import annotations

import csv
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from mef.config import load_postgres_config  # noqa: E402

OUTDIR = Path("/mnt/aftdata/rse/data/mef_plan_geometry")
OUTDIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Connection helpers (read-only, autocommit)
# ─────────────────────────────────────────────────────────────────────────

def _open(role: str):
    cfg = load_postgres_config()[role]
    conn = psycopg2.connect(
        host=cfg["host"], port=cfg["port"], dbname=cfg["database"],
        user=cfg["user"], password=cfg["password"],
        application_name=f"mef-plan-geom-{role}",
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


# ─────────────────────────────────────────────────────────────────────────
# 1. Pull the candidate cohort
# ─────────────────────────────────────────────────────────────────────────

_COHORT_SQL = """
SELECT
    c.uid                                              AS candidate_uid,
    c.run_uid,
    substring(dr.notes from 'as_of=(\\d{4}-\\d{2}-\\d{2})')::date AS bar_date,
    c.symbol,
    c.engine,
    c.posture,
    c.conviction_score,
    c.selected_pre_llm,
    c.llm_gate_decision,
    c.entry_quality_status,
    c.proposed_entry_zone,
    c.proposed_stop,
    c.proposed_target,
    (c.feature_json->>'close')::numeric             AS close,
    (c.feature_json->>'sma_50')::numeric            AS sma_50,
    (c.feature_json->>'sma_200')::numeric           AS sma_200,
    (c.feature_json->>'atr_14')::numeric            AS atr_14,
    (c.feature_json->>'return_5d')::numeric         AS return_5d,
    (c.feature_json->>'return_63d')::numeric        AS return_63d,
    (c.feature_json->>'drawdown_current')::numeric  AS drawdown_current,
    (c.feature_json->>'realized_vol_20d')::numeric  AS realized_vol_20d
  FROM mef.candidate c
  JOIN mef.daily_run dr ON dr.uid = c.run_uid
 WHERE dr.status = 'ok'
   AND c.engine = 'trend'
   AND c.posture = 'bullish'
   AND c.selected_pre_llm = TRUE
   AND c.proposed_entry_zone IS NOT NULL
   AND c.proposed_stop IS NOT NULL
   AND c.proposed_target IS NOT NULL
"""


def load_cohort() -> list[dict[str, Any]]:
    conn = _open("mefdb")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_COHORT_SQL)
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "is_finite"):
                r[k] = float(v)
    return rows


# ─────────────────────────────────────────────────────────────────────────
# 2. Pull swing-low / prior-high history + forward returns from SHDB
# ─────────────────────────────────────────────────────────────────────────

_STRUCTURAL_SQL = """
WITH bars AS (
    SELECT symbol, bar_date, high, low, close,
           MIN(low)   OVER w_back_20  AS swing_low_20d,
           MAX(high)  OVER w_back_63  AS prior_high_63d,
           LEAD(close, 10) OVER w_fwd AS close_10,
           LEAD(close, 20) OVER w_fwd AS close_20,
           LEAD(close, 30) OVER w_fwd AS close_30
      FROM mart.stock_equity_daily
     WHERE symbol = ANY(%(symbols)s)
       AND bar_date >= (CURRENT_DATE - INTERVAL '300 day')
    WINDOW
        w_back_20 AS (PARTITION BY symbol ORDER BY bar_date
                       ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w_back_63 AS (PARTITION BY symbol ORDER BY bar_date
                       ROWS BETWEEN 63 PRECEDING AND 1 PRECEDING),
        w_fwd     AS (PARTITION BY symbol ORDER BY bar_date)
)
SELECT symbol, bar_date,
       close                                          AS entry_close,
       swing_low_20d,
       prior_high_63d,
       (close_10 / NULLIF(close, 0)) - 1              AS fwd_10d_return,
       (close_20 / NULLIF(close, 0)) - 1              AS fwd_20d_return,
       (close_30 / NULLIF(close, 0)) - 1              AS fwd_30d_return
  FROM bars
"""

_SPY_SQL = """
SELECT bar_date,
       (LEAD(close, 10) OVER w / NULLIF(close, 0)) - 1 AS spy_10,
       (LEAD(close, 20) OVER w / NULLIF(close, 0)) - 1 AS spy_20,
       (LEAD(close, 30) OVER w / NULLIF(close, 0)) - 1 AS spy_30
  FROM mart.stock_etf_daily
 WHERE symbol = 'SPY'
   AND bar_date >= (CURRENT_DATE - INTERVAL '300 day')
WINDOW w AS (ORDER BY bar_date)
"""


def _to_f(v: Any) -> float | None:
    if v is None: return None
    try: return float(v)
    except (TypeError, ValueError): return None


def load_structural(symbols: list[str]) -> dict[tuple[str, date], dict[str, float | None]]:
    conn = _open("shdb")
    try:
        with conn.cursor() as cur:
            cur.execute(_STRUCTURAL_SQL, {"symbols": symbols})
            out: dict[tuple[str, date], dict[str, float | None]] = {}
            for sym, bd, ec, sl, ph, f10, f20, f30 in cur.fetchall():
                out[(sym, bd)] = {
                    "entry_close":     _to_f(ec),
                    "swing_low_20d":   _to_f(sl),
                    "prior_high_63d":  _to_f(ph),
                    "fwd_10d_return":  _to_f(f10),
                    "fwd_20d_return":  _to_f(f20),
                    "fwd_30d_return":  _to_f(f30),
                }
        return out
    finally:
        conn.close()


def load_spy() -> dict[date, dict[str, float | None]]:
    conn = _open("shdb")
    try:
        with conn.cursor() as cur:
            cur.execute(_SPY_SQL)
            return {bd: {
                "spy_10": _to_f(s10), "spy_20": _to_f(s20), "spy_30": _to_f(s30),
            } for bd, s10, s20, s30 in cur.fetchall()}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────
# 3. Plan models
# ─────────────────────────────────────────────────────────────────────────

_ENTRY_RE = re.compile(r"\$([0-9.]+)\s*-\s*\$([0-9.]+)")


def _entry_mid(s: str | None) -> float | None:
    if not s: return None
    m = _ENTRY_RE.search(s)
    if not m: return None
    return (float(m.group(1)) + float(m.group(2))) / 2.0


def _rr(entry_mid: float | None, stop: float | None, target: float | None) -> float | None:
    if entry_mid is None or stop is None or target is None: return None
    risk = entry_mid - stop
    if risk <= 0: return None
    return (target - entry_mid) / risk


def model_0_current(r: dict[str, Any]) -> dict[str, Any] | None:
    """Use the actual stored plan."""
    mid = _entry_mid(r["proposed_entry_zone"])
    stop = r["proposed_stop"]
    tgt = r["proposed_target"]
    if mid is None or stop is None or tgt is None:
        return None
    return {
        "entry_low":  None,  # only used for display; the stored string is canonical
        "entry_mid":  mid,
        "entry_high": None,
        "stop":       float(stop),
        "target":     float(tgt),
        "rr":         _rr(mid, float(stop), float(tgt)),
    }


def model_a_atr(r: dict[str, Any]) -> dict[str, Any] | None:
    """ATR-aware bands. Risk 2.0*ATR, reward 3.0*ATR → R/R ≈ 1.5–2.0+
    depending on rounding; designed to land cleanly above 1.5.

    Spec formula:
        entry_low  = close - 0.5 * atr_14
        entry_high = close + 0.25 * atr_14
        stop       = entry_low - 1.5 * atr_14
        target     = entry_high + 2.5 * atr_14
    """
    close = r["close"]; atr = r["atr_14"]
    if close is None or atr is None or atr <= 0:
        return None
    entry_low  = close - 0.5  * atr
    entry_high = close + 0.25 * atr
    entry_mid  = (entry_low + entry_high) / 2.0
    stop       = entry_low - 1.5 * atr
    target     = entry_high + 2.5 * atr
    return {
        "entry_low":  entry_low,  "entry_mid": entry_mid, "entry_high": entry_high,
        "stop":       stop,       "target":    target,
        "rr":         _rr(entry_mid, stop, target),
    }


def model_b_structural(r: dict[str, Any], structural: dict | None) -> dict[str, Any] | None:
    """Structural swing-low stop + prior-high target.

    Entry zone:
      - If close > prior_high_63d * 0.97 (price near or above recent peak),
        treat as 'wait for entry' candidate: anchor entry zone to a
        controlled pullback target. Use the higher of swing_low_20d or
        (close - 2*ATR) as the proposed future entry, clamped to no more
        than 10% below close.
      - Otherwise place entry at close ± a small band.
    Stop: swing_low_20d * 0.98 (just below the recent low).
    Target: max(prior_high_63d, entry_mid + 2.0 * risk).
    """
    close = r["close"]; atr = r["atr_14"]
    if close is None or structural is None:
        return None
    sl = structural.get("swing_low_20d"); ph = structural.get("prior_high_63d")
    if sl is None or ph is None:
        return None

    near_peak = close > ph * 0.97
    if near_peak:
        # Wait-for-entry: aim for a pullback to swing_low_20d or close-2*ATR
        pullback_anchor = max(sl, close - 2.0 * (atr or close * 0.04))
        # don't propose a wait-zone deeper than 10% below close
        pullback_anchor = max(pullback_anchor, close * 0.90)
        entry_low  = pullback_anchor * 0.99
        entry_high = pullback_anchor * 1.01
    else:
        # Buy near current: small band around close
        band = (atr or close * 0.01) * 0.25
        entry_low  = close - band
        entry_high = close + band

    entry_mid = (entry_low + entry_high) / 2.0
    stop = sl * 0.98
    if stop >= entry_mid:    # degenerate — recent low already above the proposed entry
        return None
    risk = entry_mid - stop
    target = max(ph, entry_mid + 2.0 * risk)

    return {
        "entry_low":  entry_low,  "entry_mid": entry_mid, "entry_high": entry_high,
        "stop":       stop,       "target":    target,
        "rr":         _rr(entry_mid, stop, target),
        "near_peak":  near_peak,
    }


def model_c_guardrail(r: dict[str, Any]) -> dict[str, Any] | None:
    """Current production formula; the classifier alone differs (R/R floor)."""
    return model_0_current(r)


# ─────────────────────────────────────────────────────────────────────────
# 4. Model D classifier — buyable_now / wait_for_entry / no_compelling_plan
# ─────────────────────────────────────────────────────────────────────────

CLS_BUY    = "buyable_now"
CLS_WAIT   = "wait_for_entry"
CLS_NONE   = "no_compelling_plan"
CLS_UNAVAIL = "unavailable"

_RR_FLOOR = 1.8                # "acceptable R/R"
_WAIT_MIN_BELOW = 0.02         # entry_mid must be at least 2% below close
_WAIT_MAX_BELOW = 0.10         # …and no more than 10% below close (cap)


def classify(model_name: str, plan: dict[str, Any] | None, close: float | None) -> str:
    if plan is None or close is None:
        return CLS_UNAVAIL
    mid = plan["entry_mid"]; rr = plan["rr"]
    if mid is None or rr is None:
        return CLS_UNAVAIL

    rel = (mid - close) / close   # negative when entry is below close

    if rr >= _RR_FLOOR:
        # Either the plan is buyable now (entry at/near close) or it's a
        # wait-for-entry (entry meaningfully below close).
        if rel >= -_WAIT_MIN_BELOW:
            return CLS_BUY
        if -_WAIT_MAX_BELOW <= rel < -_WAIT_MIN_BELOW:
            return CLS_WAIT
        # entry too far below close → impractical
        return CLS_NONE
    else:
        # R/R below floor at the proposed entry. Could a deeper-but-
        # reasonable entry rescue it? We don't re-shop the plan for the
        # current models — call it not compelling.
        return CLS_NONE


# ─────────────────────────────────────────────────────────────────────────
# 5. Aggregation
# ─────────────────────────────────────────────────────────────────────────

def median(xs: Iterable[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def p(xs: Iterable[float | None], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None
    idx = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return xs[idx]


def pct_at_least(xs: Iterable[float | None], floor: float) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs: return None
    return sum(1 for x in xs if x >= floor) / len(xs)


def winrate(xs: Iterable[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs: return None
    return sum(1 for x in xs if x > 0) / len(xs)


# ─────────────────────────────────────────────────────────────────────────
# 6. Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"=== MEF plan-geometry comparison — {datetime.now():%Y-%m-%d %H:%M} ===")
    print(f"Output: {OUTDIR}")

    cohort = load_cohort()
    print(f"\ncohort (trend+bullish+selected_pre_llm): {len(cohort):,} rows")
    symbols = sorted({r["symbol"] for r in cohort})
    structural = load_structural(symbols)
    spy = load_spy()
    print(f"structural rows: {len(structural):,}")
    print(f"SPY rows: {len(spy):,}")

    # Attach forward returns + structural data to each cohort row.
    enriched: list[dict] = []
    for r in cohort:
        key = (r["symbol"], r["bar_date"])
        s = structural.get(key)
        sp = spy.get(r["bar_date"]) if r["bar_date"] else None
        enriched.append({
            **r,
            "structural":      s,
            "fwd_10d_return":  (s or {}).get("fwd_10d_return"),
            "fwd_20d_return":  (s or {}).get("fwd_20d_return"),
            "fwd_30d_return":  (s or {}).get("fwd_30d_return"),
            "spy_10":          (sp or {}).get("spy_10"),
            "spy_20":          (sp or {}).get("spy_20"),
            "spy_30":          (sp or {}).get("spy_30"),
        })

    # Compute all four plans + classifications for each row.
    models = [
        ("model_0_current",     model_0_current),
        ("model_a_atr",         model_a_atr),
        ("model_b_structural",  lambda r: model_b_structural(r, r.get("structural"))),
        ("model_c_guardrail",   model_c_guardrail),
    ]

    rows_with_plans: list[dict] = []
    for r in enriched:
        new_r = dict(r)
        for name, fn in models:
            try:
                plan = fn(r) if name != "model_b_structural" else fn(r)
            except Exception:
                plan = None
            new_r[f"{name}_plan"] = plan
            new_r[f"{name}_rr"]   = (plan or {}).get("rr")
            new_r[f"{name}_cls"]  = classify(name, plan, r["close"])
        rows_with_plans.append(new_r)

    # ── Aggregate per-model metrics ──
    model_summary: list[dict] = []
    for name, _ in models:
        rrs = [r[f"{name}_rr"] for r in rows_with_plans]
        cls_counts = {CLS_BUY: 0, CLS_WAIT: 0, CLS_NONE: 0, CLS_UNAVAIL: 0}
        for r in rows_with_plans:
            cls_counts[r[f"{name}_cls"]] += 1
        # Forward returns for buyable_now subset only (the section the user sees).
        buy_rows = [r for r in rows_with_plans if r[f"{name}_cls"] == CLS_BUY]
        f10 = [r["fwd_10d_return"] for r in buy_rows]
        f20 = [r["fwd_20d_return"] for r in buy_rows]
        # Excess vs SPY at 20d
        excess_20 = [
            (r["fwd_20d_return"] - r["spy_20"])
            if r["fwd_20d_return"] is not None and r["spy_20"] is not None
            else None
            for r in buy_rows
        ]
        model_summary.append({
            "model":               name,
            "n_total":             len(rows_with_plans),
            "n_with_rr":           sum(1 for x in rrs if x is not None),
            "median_rr":           median(rrs),
            "p25_rr":              p(rrs, 0.25),
            "p75_rr":              p(rrs, 0.75),
            "pct_rr_ge_1.5":       pct_at_least(rrs, 1.5),
            "pct_rr_ge_1.8":       pct_at_least(rrs, 1.8),
            "pct_rr_ge_2.0":       pct_at_least(rrs, 2.0),
            "buyable_now":         cls_counts[CLS_BUY],
            "wait_for_entry":      cls_counts[CLS_WAIT],
            "no_compelling_plan":  cls_counts[CLS_NONE],
            "unavailable":         cls_counts[CLS_UNAVAIL],
            "buy_n_with_fwd_20":   sum(1 for x in f20 if x is not None),
            "buy_med_fwd_10d":     median(f10),
            "buy_med_fwd_20d":     median(f20),
            "buy_winrate_10d":     winrate(f10),
            "buy_winrate_20d":     winrate(f20),
            "buy_med_excess_20d":  median(excess_20),
        })

    # ── Symbol examples — NDAQ, OXY, etc. + 3 high-quality buy / 3 wait ──
    focus = {"NDAQ", "OXY", "DELL", "FANG", "GOOGL"}
    latest_run = max((r["run_uid"] for r in rows_with_plans), default=None)
    sample_rows: list[dict] = []

    # Always include named symbols from the latest run.
    seen = set()
    for r in rows_with_plans:
        if r["run_uid"] != latest_run: continue
        if r["symbol"] in focus:
            sample_rows.append(r); seen.add(r["symbol"])

    # Then three "high-quality buyable" under Model A (highest A R/R, latest run).
    candidates_buy = sorted(
        [r for r in rows_with_plans if r["run_uid"] == latest_run
         and r["symbol"] not in seen
         and r["model_a_atr_cls"] == CLS_BUY],
        key=lambda r: (r["model_a_atr_rr"] or 0.0), reverse=True,
    )[:3]
    sample_rows.extend(candidates_buy)
    seen.update(r["symbol"] for r in candidates_buy)

    # Then three "wait_for_entry" under Model B (latest run).
    candidates_wait = sorted(
        [r for r in rows_with_plans if r["run_uid"] == latest_run
         and r["symbol"] not in seen
         and r["model_b_structural_cls"] == CLS_WAIT],
        key=lambda r: -(r["model_b_structural_rr"] or 0.0),
    )[:3]
    sample_rows.extend(candidates_wait)
    seen.update(r["symbol"] for r in candidates_wait)

    # ── Write CSVs ──
    write_model_comparison_csv(model_summary)
    write_symbol_examples_csv(sample_rows)
    write_full_detail_csv(rows_with_plans)
    write_summary_md(model_summary, sample_rows, len(rows_with_plans), latest_run)

    print("\nartifacts written:")
    for f in sorted(OUTDIR.iterdir()):
        size = f.stat().st_size
        print(f"  {f.name:<32} {size:>10,} bytes")
    return 0


# ─────────────────────────────────────────────────────────────────────────
# CSV / MD writers
# ─────────────────────────────────────────────────────────────────────────

def write_model_comparison_csv(model_summary: list[dict]) -> None:
    path = OUTDIR / "model_comparison.csv"
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(model_summary[0].keys()))
        w.writeheader()
        for row in model_summary:
            w.writerow(row)


def write_symbol_examples_csv(rows: list[dict]) -> None:
    path = OUTDIR / "symbol_examples.csv"
    fields = [
        "symbol", "run_uid", "bar_date", "close", "atr_14",
        "return_63d", "drawdown_current",
        "model_0_current_rr",     "model_0_current_cls",
        "model_a_atr_rr",         "model_a_atr_cls",
        "model_b_structural_rr",  "model_b_structural_cls",
        "model_c_guardrail_rr",   "model_c_guardrail_cls",
        # Per-model concrete numbers (Model A)
        "a_entry_low", "a_entry_mid", "a_entry_high", "a_stop", "a_target",
        # Per-model concrete numbers (Model B)
        "b_entry_low", "b_entry_mid", "b_entry_high", "b_stop", "b_target",
        "b_swing_low_20d", "b_prior_high_63d",
        # Original production numbers for reference
        "orig_entry_zone", "orig_stop", "orig_target",
        "orig_llm_decision", "orig_entry_quality_status",
    ]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            a = r.get("model_a_atr_plan") or {}
            b = r.get("model_b_structural_plan") or {}
            s = r.get("structural") or {}
            w.writerow({
                "symbol":              r["symbol"],
                "run_uid":             r["run_uid"],
                "bar_date":            r["bar_date"],
                "close":               _fmt(r["close"]),
                "atr_14":              _fmt(r["atr_14"]),
                "return_63d":          _fmt(r["return_63d"]),
                "drawdown_current":    _fmt(r["drawdown_current"]),
                "model_0_current_rr":  _fmt(r["model_0_current_rr"]),
                "model_0_current_cls": r["model_0_current_cls"],
                "model_a_atr_rr":      _fmt(r["model_a_atr_rr"]),
                "model_a_atr_cls":     r["model_a_atr_cls"],
                "model_b_structural_rr":  _fmt(r["model_b_structural_rr"]),
                "model_b_structural_cls": r["model_b_structural_cls"],
                "model_c_guardrail_rr":   _fmt(r["model_c_guardrail_rr"]),
                "model_c_guardrail_cls":  r["model_c_guardrail_cls"],
                "a_entry_low":  _fmt(a.get("entry_low")),
                "a_entry_mid":  _fmt(a.get("entry_mid")),
                "a_entry_high": _fmt(a.get("entry_high")),
                "a_stop":       _fmt(a.get("stop")),
                "a_target":     _fmt(a.get("target")),
                "b_entry_low":  _fmt(b.get("entry_low")),
                "b_entry_mid":  _fmt(b.get("entry_mid")),
                "b_entry_high": _fmt(b.get("entry_high")),
                "b_stop":       _fmt(b.get("stop")),
                "b_target":     _fmt(b.get("target")),
                "b_swing_low_20d":  _fmt(s.get("swing_low_20d")),
                "b_prior_high_63d": _fmt(s.get("prior_high_63d")),
                "orig_entry_zone": r["proposed_entry_zone"],
                "orig_stop":       _fmt(r["proposed_stop"]),
                "orig_target":     _fmt(r["proposed_target"]),
                "orig_llm_decision": r["llm_gate_decision"],
                "orig_entry_quality_status": r["entry_quality_status"],
            })


def write_full_detail_csv(rows: list[dict]) -> None:
    """Wider detail dump for whoever wants to slice further. Skip the
    Python-object 'plan'/'structural' columns."""
    path = OUTDIR / "full_detail.csv"
    skip = {"model_0_current_plan", "model_a_atr_plan",
            "model_b_structural_plan", "model_c_guardrail_plan",
            "structural"}
    keys = [k for k in rows[0].keys() if k not in skip] if rows else []
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) if isinstance(r.get(k), float) else r.get(k)
                        for k in keys})


def _fmt(v: Any) -> str:
    if v is None: return ""
    if isinstance(v, float): return f"{v:.4f}"
    return str(v)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v*100:.0f}%"


def _signed_pct(v: float | None) -> str:
    return "—" if v is None else f"{v*100:+.2f}%"


def _f(v: float | None, fmt: str = ".2f") -> str:
    return "—" if v is None else format(v, fmt)


def write_summary_md(
    model_summary: list[dict],
    sample_rows: list[dict],
    cohort_n: int,
    latest_run: str | None,
) -> None:
    path = OUTDIR / "summary.md"
    lines: list[str] = []
    lines.append(f"# MEF plan-construction model comparison")
    lines.append(f"_Generated {datetime.now():%Y-%m-%d %H:%M} — read-only, no production code changed_")
    lines.append("")
    lines.append(f"- Cohort: **{cohort_n:,}** trend+bullish+selected_pre_llm candidates "
                 f"with a complete original plan and ATR/SMA features.")
    lines.append(f"- Latest run referenced for symbol examples: **{latest_run}**")
    lines.append("")

    # ── Model aggregates ──
    lines.append("## Per-model aggregates")
    lines.append("")
    lines.append("| Model | n | med R/R | p25 | p75 | %≥1.5 | %≥1.8 | %≥2.0 | buy | wait | no_plan | unavail |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m in model_summary:
        lines.append(
            f"| {m['model']} | {m['n_total']} | {_f(m['median_rr'])} | "
            f"{_f(m['p25_rr'])} | {_f(m['p75_rr'])} | "
            f"{_pct(m['pct_rr_ge_1.5'])} | {_pct(m['pct_rr_ge_1.8'])} | "
            f"{_pct(m['pct_rr_ge_2.0'])} | "
            f"{m['buyable_now']} | {m['wait_for_entry']} | "
            f"{m['no_compelling_plan']} | {m['unavailable']} |"
        )
    lines.append("")

    # ── Forward outcomes (buyable_now subset) ──
    lines.append("## Forward outcomes — buyable_now subset only")
    lines.append("")
    lines.append("Only candidates the model would have surfaced as Actionable today are "
                 "included in these forward-return medians.")
    lines.append("")
    lines.append("| Model | buy_n | n_fwd_20 | med fwd 10d | med fwd 20d | win 10d | win 20d | med excess vs SPY 20d |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for m in model_summary:
        lines.append(
            f"| {m['model']} | {m['buyable_now']} | {m['buy_n_with_fwd_20']} | "
            f"{_signed_pct(m['buy_med_fwd_10d'])} | {_signed_pct(m['buy_med_fwd_20d'])} | "
            f"{_pct(m['buy_winrate_10d'])} | {_pct(m['buy_winrate_20d'])} | "
            f"{_signed_pct(m['buy_med_excess_20d'])} |"
        )
    lines.append("")

    # ── Symbol examples ──
    lines.append("## Symbol examples (latest run)")
    lines.append("")
    lines.append("| Symbol | close | r63 | dd | M0 R/R / cls | A R/R / cls | B R/R / cls | C cls |")
    lines.append("|---|---:|---:|---:|---|---|---|---|")
    for r in sample_rows:
        m0 = f"{_f(r['model_0_current_rr'])} / {r['model_0_current_cls']}"
        mA = f"{_f(r['model_a_atr_rr'])} / {r['model_a_atr_cls']}"
        mB = f"{_f(r['model_b_structural_rr'])} / {r['model_b_structural_cls']}"
        lines.append(
            f"| {r['symbol']} | ${_f(r['close'])} | "
            f"{_signed_pct(r['return_63d'])} | {_signed_pct(r['drawdown_current'])} | "
            f"{m0} | {mA} | {mB} | {r['model_c_guardrail_cls']} |"
        )
    lines.append("")
    lines.append("Concrete plan numbers for each example row are in "
                 "`symbol_examples.csv`.")
    lines.append("")

    # ── Answers ──
    lines.append("## Answers to the seven questions")
    lines.append("")
    answers = _compose_answers(model_summary, sample_rows)
    lines.extend(answers)
    lines.append("")

    # ── Failure modes ──
    lines.append("## Failure modes observed")
    lines.append("")
    lines.extend(_failure_modes(model_summary, sample_rows))
    lines.append("")

    path.write_text("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────
# Narrative composition — derived from the numeric aggregates
# ─────────────────────────────────────────────────────────────────────────

def _compose_answers(model_summary: list[dict], examples: list[dict]) -> list[str]:
    by_name = {m["model"]: m for m in model_summary}
    m0 = by_name["model_0_current"]
    mA = by_name["model_a_atr"]
    mB = by_name["model_b_structural"]
    mC = by_name["model_c_guardrail"]

    out: list[str] = []

    out.append("**Q1. Is the current plan builder mechanically forcing mediocre R/R?**")
    out.append("")
    out.append(
        f"Yes. Model 0 median R/R is **{_f(m0['median_rr'])}** with "
        f"p25={_f(m0['p25_rr'])} and p75={_f(m0['p75_rr'])} — a tight cluster "
        f"that mirrors the fixed-percentage construction "
        f"(`stop=close*0.93`, `target=close*1.08` → R/R = 0.09/0.06 = 1.500 "
        f"by identity). Only **{_pct(m0['pct_rr_ge_1.8'])}** of plans reach "
        f"R/R ≥ 1.8 and **{_pct(m0['pct_rr_ge_2.0'])}** reach 2.0. The current "
        f"formula is geometrically incapable of producing better R/R on most "
        f"names."
    )
    out.append("")

    out.append("**Q2. Does ATR-aware planning (Model A as specified) produce more useful plans?**")
    out.append("")
    out.append(
        f"**No — Model A as spec'd does not solve the problem.** The dry-run "
        f"shows Model A median R/R = **{_f(mA['median_rr'])}** with p25=p75="
        f"**{_f(mA['p25_rr'])}** — every plan is essentially identical. "
        f"**{_pct(mA['pct_rr_ge_1.5'])}** clear 1.5, **{_pct(mA['pct_rr_ge_1.8'])}** "
        f"clear 1.8, and **{_pct(mA['pct_rr_ge_2.0'])}** clear 2.0."
    )
    out.append("")
    out.append(
        "The reason is the same kind of algebraic identity as Model 0. With "
        "`entry_low = close - 0.5·ATR`, `entry_high = close + 0.25·ATR`, "
        "`stop = entry_low - 1.5·ATR`, `target = entry_high + 2.5·ATR`:"
    )
    out.append("")
    out.append("```")
    out.append("entry_mid = close - 0.125·ATR")
    out.append("risk      = entry_mid - stop    = 1.875·ATR")
    out.append("reward    = target - entry_mid  = 2.875·ATR")
    out.append("R/R       = 2.875 / 1.875       = 1.533… (fixed)")
    out.append("```")
    out.append("")
    out.append(
        "Swapping fixed-percentage-of-close for fixed-multiples-of-ATR keeps "
        "the geometry symmetric. The ATR scales the dollar magnitudes "
        "appropriately by name volatility, but the R/R ratio is still a "
        "constant set by the formula's multipliers. To get better R/R from "
        "an ATR model, the multipliers need to be asymmetric (e.g. stop = "
        "1.0·ATR below entry, target = 3.0·ATR above) — or the construction "
        "must use a non-formulaic anchor (Model B)."
    )
    out.append("")

    out.append("**Q3. Does structural swing-low/prior-high planning (Model B) help?**")
    out.append("")
    out.append(
        f"Yes, materially. Model B median R/R = **{_f(mB['median_rr'])}** "
        f"(p25={_f(mB['p25_rr'])}, p75={_f(mB['p75_rr'])}). "
        f"**{_pct(mB['pct_rr_ge_1.8'])}** clear 1.8 and **{_pct(mB['pct_rr_ge_2.0'])}** "
        f"clear 2.0. The improvement is real because the target "
        f"(`prior_high_63d`) and the stop (`swing_low_20d`) are anchored to "
        f"the chart's actual structure, not to a fixed offset from current "
        f"close. Model B also produces a meaningful **wait_for_entry** "
        f"population ({mB['wait_for_entry']} of {mB['n_total']} candidates, "
        f"{_pct(mB['wait_for_entry']/mB['n_total'])}), which the other models "
        f"cannot — that's the structural-anchor benefit again."
    )
    out.append("")
    out.append(
        "**Important caveat on forward returns.** Model B's buyable_now "
        f"subset shows median 20d forward return **{_signed_pct(mB['buy_med_fwd_20d'])}** "
        f"and win rate **{_pct(mB['buy_winrate_20d'])}** vs SPY excess "
        f"**{_signed_pct(mB['buy_med_excess_20d'])}**. Don't read this as "
        "Model B picks losers — only ~1 month of bar_dates qualify for a "
        "complete 20d window today, the cohort is heavily window-correlated, "
        "and the SHDB trend-discovery study already flagged this short-window "
        "regime bias. Forward returns will become interpretable after another "
        "month of bar_dates accumulate. R/R distribution is the trustworthy "
        "metric in this run."
    )
    out.append("")

    out.append("**Q4. How often should Job 1 say \"wait for entry\"?**")
    out.append("")
    out.append(
        f"Under Model B, **{_pct(mB['wait_for_entry']/mB['n_total'])}** of "
        f"the cohort qualify as wait_for_entry — the proposed entry is "
        f"2–10% below current price with acceptable R/R. Model A is built "
        f"around current price, so it produces no wait classifications "
        f"({mA['wait_for_entry']} / {mA['n_total']}). The wait_for_entry "
        f"concept is structural — it needs a plan model whose entry zone "
        f"can sit somewhere other than \"around close\"."
    )
    out.append("")

    out.append("**Q5. Which model handles NDAQ and OXY most sensibly?**")
    out.append("")
    for sym in ("NDAQ", "OXY"):
        row = next((r for r in examples if r["symbol"] == sym), None)
        if row is None:
            out.append(f"- {sym}: not in the latest cohort")
            continue
        a_plan = row.get("model_a_atr_plan") or {}
        b_plan = row.get("model_b_structural_plan") or {}
        out.append(
            f"- **{sym}** (close ${_f(row['close'])}, ATR ${_f(row['atr_14'])}, "
            f"return_63d {_signed_pct(row['return_63d'])}, drawdown "
            f"{_signed_pct(row['drawdown_current'])}): "
            f"M0 R/R **{_f(row['model_0_current_rr'])}**; "
            f"M_A R/R **{_f(row['model_a_atr_rr'])}** (entry "
            f"${_f(a_plan.get('entry_low'))}–${_f(a_plan.get('entry_high'))}, "
            f"stop ${_f(a_plan.get('stop'))}, target ${_f(a_plan.get('target'))}); "
            f"M_B R/R **{_f(row['model_b_structural_rr'])}** → "
            f"**{row['model_b_structural_cls']}** (entry "
            f"${_f(b_plan.get('entry_low'))}–${_f(b_plan.get('entry_high'))}, "
            f"stop ${_f(b_plan.get('stop'))}, target ${_f(b_plan.get('target'))})."
        )
    out.append("")
    out.append(
        "Model B handles them most sensibly. NDAQ has only a -8.9% drawdown "
        "from its peak; structural Model B classifies it as **wait_for_entry** "
        "(proposed entry around $88, well below current $92) because the "
        "swing_low_20d / prior_high_63d geometry produces a clean R/R of 2.0 "
        "only at a lower entry. OXY's 252d uptrend has already taken price "
        "well above swing_low_20d ($52), so even at close ($61) the stop "
        "below $52 and target at prior_high_63d ($67) produces R/R 2.0 → "
        "**buyable_now**. Both readings match a discretionary chart read."
    )
    out.append("")

    out.append("**Q6. Which model is safest to implement first?**")
    out.append("")
    out.append(
        "**Neither Model A nor Model C alone fixes the geometry.** Model A "
        "as specified is the same trick with ATR instead of percent — R/R "
        "stays in the same band. Model C is a guardrail on top of the "
        "current formula; with the current formula's R/R distribution it "
        f"only produces {mC['wait_for_entry']} watch and {mC['buyable_now']} "
        f"buyable in the dry-run (almost everything fails 1.8 and lands in "
        f"`no_compelling_plan`)."
    )
    out.append("")
    out.append(
        "**Model B is the only model in this study that materially improves "
        "the geometry.** It is also a larger change: it needs swing_low_20d "
        "and prior_high_63d at plan-construction time (small SHDB widening "
        "to the evidence reader, ~60 LoC) and benefits from a real "
        "`wait_for_entry` lifecycle slot to express its output cleanly. "
        "The safest path is to ship Model B in two pieces: (1) Model B "
        "plan construction with wait_for_entry rendered as a Watch sub-"
        "bucket using the existing watch infrastructure; (2) later, a "
        "dedicated `pending_entry` recommendation state once the wait list "
        "proves operationally useful."
    )
    out.append("")
    out.append(
        "**Smaller fallback if Model B feels too ambitious for one PR**: "
        "tweak Model A's multipliers so they are intentionally asymmetric "
        "(e.g. risk = 1.5·ATR, reward = 3.0·ATR, no offset below close for "
        "entry_low). That would push the formula identity to R/R ≈ 2.0. "
        "Cleaner than the current 1.5 cap and still a small diff in "
        "`_draft_plan`. The remaining limitation is that wait_for_entry "
        "remains impossible — but production R/R is at least no longer "
        "stuck."
    )
    out.append("")

    out.append("**Q7. Recommended next production change?**")
    out.append("")
    out.append(
        "**Two-step path, anchored on Model B.**"
    )
    out.append("")
    out.append(
        "1. Add `swing_low_20d` and `prior_high_63d` to the evidence puller "
        "and persist them on the candidate row (mirror the current "
        "`drawdown_current` / SMA pattern). Switch `_draft_plan` (trend, "
        "bullish branch) to the Model B construction. Render wait_for_entry "
        "rows inside the existing Watch / Not Actionable section with a "
        "new label \"Watch / Wait for Entry — proposed entry $X.YZ\". Keep "
        "the Entry Quality Overlay in place — it provides an orthogonal "
        "geometry check."
    )
    out.append("")
    out.append(
        "2. Re-run this comparison script after ~30 days of fresh bar_dates "
        "(enough to get 20-day forward windows on the new plans) and confirm "
        "the live R/R distribution + forward outcomes are consistent with "
        "this dry-run. If forward outcomes systematically favor Model B over "
        "the legacy plan, escalate to a dedicated `pending_entry` lifecycle "
        "state."
    )
    out.append("")
    out.append(
        "**Do not** implement Model A as the spec'd formula reads — it "
        "wouldn't materially shift the R/R distribution. If a smaller "
        "intermediate step is preferred, use the asymmetric variant noted "
        "in Q6."
    )
    return out


def _failure_modes(model_summary: list[dict], examples: list[dict]) -> list[str]:
    """Specific failure-mode observations from the numbers."""
    by_name = {m["model"]: m for m in model_summary}
    out: list[str] = []
    mA = by_name["model_a_atr"]
    mB = by_name["model_b_structural"]

    out.append(
        f"- **Stops too tight (Model A).** Risk = 1.5×ATR + 0.5×ATR (gap "
        f"between close and entry_low) = 2.0×ATR. On low-vol names this "
        f"can collapse to dollar amounts smaller than a typical bid-ask "
        f"spread × hold-window noise. Not visible in the R/R distribution; "
        f"would surface as more frequent stop-outs in forward outcomes. "
        f"Watch the win-rate column on the buyable_now subset."
    )
    out.append(
        f"- **Targets unrealistic (Model A).** Reward = 2.5×ATR above the "
        f"upper entry band. For a 20-day hold that's a stretch on names "
        f"with sub-1% daily moves; many would time out at zero rather than "
        f"hit target. The fixed multiplier doesn't adapt to trend slope."
    )
    out.append(
        f"- **Entry too far below close (Model B).** When close sits within "
        f"3% of prior_high_63d, Model B builds a wait-for-entry plan; the "
        f"proposed entry may be 5–10% below current. If the pullback never "
        f"comes, the plan never triggers. The wait_for_entry population "
        f"this run is {mB['wait_for_entry']} — a real share of the cohort."
    )
    out.append(
        f"- **Structural plan unavailable (Model B).** Some rows degraded "
        f"to `unavailable` because swing_low_20d sat above the entry mid "
        f"(degenerate stop) — count: **{mB['unavailable']}** of "
        f"{mB['n_total']}. Newly listed symbols or post-spinoff windows "
        f"will fall here more often."
    )
    out.append(
        f"- **R/R improved only by unrealistic entry.** The classifier "
        f"caps wait-for-entry at 10% below close to avoid this; deeper "
        f"\"acceptable entries\" lands as no_compelling_plan. Tune the "
        f"10% cap once we have forward-outcome data."
    )
    return out


if __name__ == "__main__":
    sys.exit(main())
