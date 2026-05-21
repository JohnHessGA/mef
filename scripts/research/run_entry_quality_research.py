#!/usr/bin/env python3
"""MEF Job 1 entry-quality research runner — READ-ONLY.

Reads:
    mefdb  — mef.candidate + mef.daily_run for the trend-engine bullish
             cohort and the engine-confirmation cohort.
    shdb   — mart.stock_equity_daily for per-symbol 10/20/30-day forward
             returns, mart.stock_etf_daily for the SPY benchmark.

Writes nothing. Never opens a write transaction.

Outputs eight cohort tables (Sections 4–11 of the companion SQL file)
to stdout as Markdown, sized to paste straight into a research report.

Usage:
    source ~/repos/mef/.venv/bin/activate
    python scripts/research/run_entry_quality_research.py
    # or, to dump to a file:
    python scripts/research/run_entry_quality_research.py > entry_quality_$(date +%F).md

Companion docs:
    docs/research/mef_entry_quality_research_plan.md
    scripts/research/mef_entry_quality_research.sql
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

# Allow running from a checkout where the venv may not have mef installed
# editable; the project src/ root is always two levels up from this script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from mef.config import load_postgres_config  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Connection helpers — vanilla psycopg2, read-only autocommit.
# ─────────────────────────────────────────────────────────────────────────

def _open(role: str):
    cfg = load_postgres_config()[role]
    conn = psycopg2.connect(
        host=cfg["host"], port=cfg["port"], dbname=cfg["database"],
        user=cfg["user"], password=cfg["password"],
        application_name=f"mef-research-{role}",
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


# ─────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────

# Same WHERE / projection as Section 1 of the SQL companion file.
_BASE_COHORT_SQL = """
SELECT
    c.uid                                            AS candidate_uid,
    c.run_uid,
    substring(dr.notes from 'as_of=(\\d{4}-\\d{2}-\\d{2})')::date AS bar_date,
    c.symbol,
    c.engine,
    c.posture,
    c.conviction_score,
    c.raw_conviction,
    c.hazard_penalty_total,
    c.emitted,
    c.llm_gate_decision,
    c.proposed_entry_zone,
    c.proposed_stop,
    c.proposed_target,
    (c.feature_json->>'close')::numeric             AS close,
    (c.feature_json->>'sma_50')::numeric            AS sma_50,
    (c.feature_json->>'sma_200')::numeric           AS sma_200,
    (c.feature_json->>'sma_50_slope')::numeric      AS sma_50_slope,
    (c.feature_json->>'return_5d')::numeric         AS return_5d,
    (c.feature_json->>'return_20d')::numeric        AS return_20d,
    (c.feature_json->>'return_63d')::numeric        AS return_63d,
    (c.feature_json->>'return_126d')::numeric       AS return_126d,
    (c.feature_json->>'return_252d')::numeric       AS return_252d,
    (c.feature_json->>'rsi_14')::numeric            AS rsi_14,
    (c.feature_json->>'macd_histogram')::numeric    AS macd_histogram,
    (c.feature_json->>'atr_14')::numeric            AS atr_14,
    (c.feature_json->>'drawdown_current')::numeric  AS drawdown_current,
    (c.feature_json->>'free_cash_flow')::numeric    AS free_cash_flow
  FROM mef.candidate c
  JOIN mef.daily_run dr ON dr.uid = c.run_uid
 WHERE dr.status = 'ok'
   AND c.engine = 'trend'
   AND c.posture = 'bullish'
   AND c.conviction_score >= 0.50
"""


def load_base_cohort() -> list[dict[str, Any]]:
    """Pull every trend-engine bullish candidate that cleared the threshold."""
    conn = _open("mefdb")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_BASE_COHORT_SQL)
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    # Cast numerics to float for arithmetic; preserve None.
    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "is_finite"):    # Decimal
                r[k] = float(v)
    return rows


# Engine-confirmation cohort: per (run_uid, symbol), which non-trend engines
# returned a non-no_edge posture? Used by Section 10 / Cohort G.
_ENGINE_CONFIRMATION_SQL = """
SELECT  run_uid,
        symbol,
        array_agg(DISTINCT engine ORDER BY engine) FILTER (
            WHERE posture <> 'no_edge' AND conviction_score >= 0.40
        ) AS confirming_engines
  FROM mef.candidate
 WHERE engine IN ('mean_reversion', 'value')
 GROUP BY run_uid, symbol
"""


def load_engine_confirmation() -> dict[tuple[str, str], list[str]]:
    conn = _open("mefdb")
    try:
        with conn.cursor() as cur:
            cur.execute(_ENGINE_CONFIRMATION_SQL)
            out: dict[tuple[str, str], list[str]] = {}
            for run_uid, symbol, engines in cur.fetchall():
                out[(run_uid, symbol)] = list(engines or [])
        return out
    finally:
        conn.close()


# Forward returns: window functions over mart.stock_equity_daily.
# Bounded to the symbols actually in the cohort (keep the working set small).
_FORWARD_RETURNS_SQL = """
WITH bars AS (
    SELECT symbol, bar_date, close,
           LEAD(close, 10) OVER w AS close_10,
           LEAD(close, 20) OVER w AS close_20,
           LEAD(close, 30) OVER w AS close_30,
           MIN(close) OVER w_fwd_20 AS min_close_next_20d,
           MIN(close) OVER w_fwd_30 AS min_close_next_30d
      FROM mart.stock_equity_daily
     WHERE symbol = ANY(%(symbols)s)
       AND bar_date >= (CURRENT_DATE - INTERVAL '300 day')
    WINDOW
        w        AS (PARTITION BY symbol ORDER BY bar_date),
        w_fwd_20 AS (PARTITION BY symbol ORDER BY bar_date
                      ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING),
        w_fwd_30 AS (PARTITION BY symbol ORDER BY bar_date
                      ROWS BETWEEN 1 FOLLOWING AND 30 FOLLOWING)
)
SELECT symbol, bar_date,
       close                                  AS entry_close,
       (close_10 / NULLIF(close, 0)) - 1      AS fwd_10d_return,
       (close_20 / NULLIF(close, 0)) - 1      AS fwd_20d_return,
       (close_30 / NULLIF(close, 0)) - 1      AS fwd_30d_return,
       (min_close_next_20d / NULLIF(close, 0)) - 1 AS max_dd_next_20d,
       (min_close_next_30d / NULLIF(close, 0)) - 1 AS max_dd_next_30d
  FROM bars
"""

_SPY_RETURNS_SQL = """
SELECT bar_date,
       (LEAD(close, 10) OVER w / NULLIF(close, 0)) - 1 AS spy_fwd_10d,
       (LEAD(close, 20) OVER w / NULLIF(close, 0)) - 1 AS spy_fwd_20d,
       (LEAD(close, 30) OVER w / NULLIF(close, 0)) - 1 AS spy_fwd_30d
  FROM mart.stock_etf_daily
 WHERE symbol = 'SPY'
   AND bar_date >= (CURRENT_DATE - INTERVAL '300 day')
WINDOW w AS (ORDER BY bar_date)
"""


def load_forward_returns(symbols: list[str]) -> dict[tuple[str, date], dict[str, float | None]]:
    conn = _open("shdb")
    try:
        with conn.cursor() as cur:
            cur.execute(_FORWARD_RETURNS_SQL, {"symbols": symbols})
            out: dict[tuple[str, date], dict[str, float | None]] = {}
            for row in cur.fetchall():
                sym, bd, ec, f10, f20, f30, dd20, dd30 = row
                out[(sym, bd)] = {
                    "entry_close":     _to_float(ec),
                    "fwd_10d_return":  _to_float(f10),
                    "fwd_20d_return":  _to_float(f20),
                    "fwd_30d_return":  _to_float(f30),
                    "max_dd_next_20d": _to_float(dd20),
                    "max_dd_next_30d": _to_float(dd30),
                }
        return out
    finally:
        conn.close()


def load_spy_returns() -> dict[date, dict[str, float | None]]:
    conn = _open("shdb")
    try:
        with conn.cursor() as cur:
            cur.execute(_SPY_RETURNS_SQL)
            return {bd: {
                "spy_fwd_10d": _to_float(s10),
                "spy_fwd_20d": _to_float(s20),
                "spy_fwd_30d": _to_float(s30),
            } for bd, s10, s20, s30 in cur.fetchall()}
    finally:
        conn.close()


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────
# Cohort definitions (Sections 4–11 of the companion SQL)
# ─────────────────────────────────────────────────────────────────────────

def _ext_from_sma200(r: dict) -> float | None:
    if r["close"] is None or r["sma_200"] is None or r["sma_200"] == 0:
        return None
    return (r["close"] - r["sma_200"]) / r["sma_200"]


def _bucket_ext_sma200(r: dict) -> str | None:
    e = _ext_from_sma200(r)
    if e is None:
        return None
    if e < 0.05:   return "ext_sma200: 0–5%"
    if e < 0.10:   return "ext_sma200: 5–10%"
    if e < 0.15:   return "ext_sma200: 10–15%"
    if e < 0.20:   return "ext_sma200: 15–20%"
    if e < 0.25:   return "ext_sma200: 20–25%"
    return            "ext_sma200: >25%"


def _bucket_return_63d(r: dict) -> str | None:
    v = r["return_63d"]
    if v is None: return None
    if v < 0.05:  return "return_63d: <5%"
    if v < 0.10:  return "return_63d: 5–10%"
    if v < 0.20:  return "return_63d: 10–20%"
    if v < 0.30:  return "return_63d: 20–30%"
    return            "return_63d: >30%"


def _bucket_runup_pullback(r: dict) -> str | None:
    if r["return_63d"] is None or r["drawdown_current"] is None:
        return None
    if r["return_63d"] <= 0.20:
        return None   # Only studied for big runners
    dd = r["drawdown_current"]
    if dd > -0.05:           return "runup>20% & dd > -5%"
    if dd >= -0.10:          return "runup>20% & dd in [-10%,-5%]"
    return                   "runup>20% & dd < -10%"


def _bucket_sma200_cushion(r: dict) -> str | None:
    e = _ext_from_sma200(r)
    if e is None or e < 0:
        return None  # only meaningful when above SMA200
    if e < 0.03:   return "cushion: 0–3%"
    if e < 0.05:   return "cushion: 3–5%"
    if e < 0.10:   return "cushion: 5–10%"
    return            "cushion: >10%"


def _bucket_choppy_recovery(r: dict) -> str | None:
    """Two flavors of the same shape — round-trip that just made it back."""
    if r["return_63d"] is None or r["return_63d"] <= 0.12:
        return None
    if r["return_126d"] is not None and r["return_126d"] < 0.05:
        return "choppy_recovery: r63>12% & r126<5%"
    if r["return_252d"] is not None and r["return_252d"] < 0.15:
        return "choppy_recovery: r63>12% & r252<15%"
    return None


_ENTRY_ZONE_RE = re.compile(r"\$([0-9.]+)\s*-\s*\$([0-9.]+)")


def _entry_mid(r: dict) -> float | None:
    zone = r.get("proposed_entry_zone")
    if not zone:
        return None
    m = _ENTRY_ZONE_RE.search(zone)
    if not m:
        return None
    try:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    except ValueError:
        return None


def _risk_reward(r: dict) -> float | None:
    mid = _entry_mid(r)
    stop = r.get("proposed_stop")
    tgt  = r.get("proposed_target")
    if mid is None or stop is None or tgt is None:
        return None
    risk = mid - float(stop)
    if risk <= 0:
        return None
    return (float(tgt) - mid) / risk


def _bucket_risk_reward(r: dict) -> str | None:
    rr = _risk_reward(r)
    if rr is None:
        return None
    if rr < 1.2:   return "r:r <1.2"
    if rr < 1.5:   return "r:r 1.2–1.5"
    if rr < 2.0:   return "r:r 1.5–2.0"
    return            "r:r >2.0"


def _bucket_engine_confirmation(r: dict, confirm: dict) -> str:
    key = (r["run_uid"], r["symbol"])
    others = confirm.get(key, [])
    has_value = "value" in others
    has_mr    = "mean_reversion" in others
    if has_value and has_mr:
        return "multi: trend+value+mean_rev"
    if has_value:
        return "multi: trend+value"
    if has_mr:
        return "multi: trend+mean_rev"
    return     "trend only"


def _bucket_fcf(r: dict) -> str:
    fcf = r.get("free_cash_flow")
    if fcf is None:    return "FCF: missing"
    if fcf < 0:        return "FCF: negative"
    return                 "FCF: positive"


# Cohort registry — each entry yields (rows, bucket_function).
def all_cohorts(confirm: dict[tuple[str, str], list[str]]):
    yield "A. Extension from SMA200",       _bucket_ext_sma200
    yield "B. 63-day run-up",               _bucket_return_63d
    yield "C. Run-up with little pullback", _bucket_runup_pullback
    yield "D. SMA200 cushion",              _bucket_sma200_cushion
    yield "E. Choppy recovery",             _bucket_choppy_recovery
    yield "F. Risk/reward geometry",        _bucket_risk_reward
    yield "G. Engine confirmation",         (lambda r: _bucket_engine_confirmation(r, confirm))
    yield "H. Free cash flow",              _bucket_fcf


# ─────────────────────────────────────────────────────────────────────────
# Aggregation
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class CohortRow:
    bucket: str
    n: int
    med_10d: float | None
    med_20d: float | None
    med_30d: float | None
    win_20d: float | None
    win_30d: float | None
    med_max_dd_30d: float | None
    med_rel_spy_30d: float | None


def _median(xs: Iterable[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _winrate(xs: Iterable[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return sum(1 for x in xs if x > 0) / len(xs)


def aggregate(rows: list[dict], bucket_fn) -> list[CohortRow]:
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        b = bucket_fn(r)
        if b is None:
            continue
        buckets.setdefault(b, []).append(r)
    out: list[CohortRow] = []
    for b, members in sorted(buckets.items()):
        out.append(CohortRow(
            bucket=b,
            n=len(members),
            med_10d=_median(m["fwd_10d_return"] for m in members),
            med_20d=_median(m["fwd_20d_return"] for m in members),
            med_30d=_median(m["fwd_30d_return"] for m in members),
            win_20d=_winrate(m["fwd_20d_return"] for m in members),
            win_30d=_winrate(m["fwd_30d_return"] for m in members),
            med_max_dd_30d=_median(m["max_dd_next_30d"] for m in members),
            med_rel_spy_30d=_median(
                (m["fwd_30d_return"] - m["spy_fwd_30d"])
                if m["fwd_30d_return"] is not None and m["spy_fwd_30d"] is not None
                else None
                for m in members
            ),
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────

def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.2f}%"


def _fmt_pct_unsigned(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def render_cohort_md(name: str, rows: list[CohortRow]) -> str:
    out = [
        f"### {name}",
        "",
        "| Bucket | n | med fwd 10d | med fwd 20d | med fwd 30d | win 20d | win 30d | med max-dd 30d | med vs SPY 30d |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if not rows:
        out.append("| _(no candidates in any bucket)_ |  |  |  |  |  |  |  |  |")
    for r in rows:
        out.append(
            f"| {r.bucket} | {r.n} | {_fmt_pct(r.med_10d)} | "
            f"{_fmt_pct(r.med_20d)} | {_fmt_pct(r.med_30d)} | "
            f"{_fmt_pct_unsigned(r.win_20d)} | {_fmt_pct_unsigned(r.win_30d)} | "
            f"{_fmt_pct(r.med_max_dd_30d)} | {_fmt_pct(r.med_rel_spy_30d)} |"
        )
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-bucket-size", type=int, default=20,
        help="Suppress buckets with fewer rows than this (default: 20).",
    )
    args = parser.parse_args()

    print(f"# MEF Job 1 entry-quality research — {datetime.now():%Y-%m-%d %H:%M}")
    print()
    print("Generated by `scripts/research/run_entry_quality_research.py`. Read-only.")
    print()

    print("## Step 1 — Cohort load")
    rows = load_base_cohort()
    print()
    print(f"- base cohort (trend+bullish+conv≥0.50): **{len(rows):,}** rows")
    symbols = sorted({r["symbol"] for r in rows})
    bar_dates = sorted({r["bar_date"] for r in rows if r["bar_date"] is not None})
    print(f"- distinct symbols: **{len(symbols):,}**")
    print(f"- distinct bar_dates: **{len(bar_dates)}** "
          f"({bar_dates[0]} → {bar_dates[-1]})")

    print()
    print("## Step 2 — Forward-return join")
    fwd = load_forward_returns(symbols)
    spy = load_spy_returns()
    print()
    print(f"- forward-return rows fetched: **{len(fwd):,}**")
    print(f"- SPY benchmark rows: **{len(spy):,}**")

    # Attach forward returns + SPY to each candidate.
    matched = 0
    for r in rows:
        bd = r["bar_date"]
        f = fwd.get((r["symbol"], bd)) if bd is not None else None
        s = spy.get(bd) if bd is not None else None
        r["fwd_10d_return"] = f["fwd_10d_return"] if f else None
        r["fwd_20d_return"] = f["fwd_20d_return"] if f else None
        r["fwd_30d_return"] = f["fwd_30d_return"] if f else None
        r["max_dd_next_20d"] = f["max_dd_next_20d"] if f else None
        r["max_dd_next_30d"] = f["max_dd_next_30d"] if f else None
        r["spy_fwd_10d"] = s["spy_fwd_10d"] if s else None
        r["spy_fwd_20d"] = s["spy_fwd_20d"] if s else None
        r["spy_fwd_30d"] = s["spy_fwd_30d"] if s else None
        if f is not None:
            matched += 1
    print(f"- candidates with any forward bar joined: **{matched:,}**")
    n_30d = sum(1 for r in rows if r["fwd_30d_return"] is not None)
    n_20d = sum(1 for r in rows if r["fwd_20d_return"] is not None)
    n_10d = sum(1 for r in rows if r["fwd_10d_return"] is not None)
    print(f"- with full 10d / 20d / 30d forward returns: "
          f"**{n_10d:,} / {n_20d:,} / {n_30d:,}**")

    confirm = load_engine_confirmation()
    print(f"- engine-confirmation pairs loaded: **{len(confirm):,}**")

    print()
    print("## Step 3 — Cohort tables")
    print()
    print(f"_Buckets smaller than n={args.min_bucket_size} are suppressed._")
    print()

    for name, bucket_fn in all_cohorts(confirm):
        cohort_rows = aggregate(rows, bucket_fn)
        # Drop tiny buckets so cohort medians don't claim signal that's noise.
        cohort_rows = [r for r in cohort_rows if r.n >= args.min_bucket_size]
        print(render_cohort_md(name, cohort_rows))
        print()

    print("---")
    print()
    print("Methodology, caveats, and how to interpret these tables live in")
    print("`docs/research/mef_entry_quality_research_plan.md`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
