"""`mef status` — user-facing investing report (read-only).

Compact header + three sections:

  Actionable Stock Ideas    — Job 1 recs the LLM gate cleared (`approve`)
                              and where price is consistent with the plan.
  Watch / Not Actionable    — Job 1 recs the gate held for review, or that
                              show posture/evidence mismatch, missing
                              stabilization, or low conviction.
  Core Pullback Watchlist   — Job 2 deterministic pullback statuses on the
                              curated 10+50 watchlist (see core_pullback*).

The ETF-posture summary previously rendered after the watchlist was
removed on 2026-05-21 because it overlapped conceptually with Core
Pullback and produced two competing ETF readouts (e.g., IWM showing up
as BUY_ZONE_ACTIVE in one section and `healthy_pullback` in the other).
The underlying helpers `_fetch_etf_posture` / `_render_etf_posture`
remain in this module so a future dedicated ETF view can use them
without re-writing the data plumbing.

No latest-run metadata, no DB connectivity, no recent-alert telemetry —
that lives in `mef health`. No DB writes, no email, no pipeline run.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from mef.db.connection import connect_mefdb, connect_shdb


# ───────────────────────────── public entry ─────────────────────────────

def run(args) -> int:
    report = _gather()
    print(_render(report))
    return 0


# ───────────────────────────── data gathering ─────────────────────────────

def _gather() -> dict[str, Any]:
    out: dict[str, Any] = {
        "now": datetime.now().astimezone(),
        "universe": _fetch_universe_counts(),
        "data_through": _fetch_market_data_through(),
    }
    latest_run_uid = _fetch_latest_run_uid()
    if latest_run_uid:
        out["recommendations"] = _fetch_recommendations(latest_run_uid)
    else:
        out["recommendations"] = []
    # ETF posture is no longer rendered in the default report (see module
    # docstring). Skip the fetch entirely so `mef status` doesn't pay for
    # a full 325-symbol pull_latest_evidence() call that nobody reads.
    # The _fetch_etf_posture / _render_etf_posture helpers remain in
    # this module for a future dedicated ETF view.
    out["pullback_signals"] = _fetch_pullback_signals()
    return out


def _fetch_pullback_signals():
    """Build the Job 2 Core Pullback Watchlist signals.

    Wrapped in a broad try/except: a SHDB or repository outage must not
    prevent the rest of ``mef status`` from rendering. Returns None on
    any failure; the renderer treats None as "section unavailable".
    """
    try:
        from mef.core_pullback import evaluate_watchlist
        from mef.core_pullback_evidence import fetch_pullback_evidence
        from mef.core_pullback_repository import load_enabled_watchlist
    except Exception:
        return None
    try:
        watchlist = load_enabled_watchlist()
        if not watchlist:
            return []
        symbols_by_kind: dict[str, list[str]] = {"stock": [], "etf": []}
        for row in watchlist:
            symbols_by_kind.setdefault(row.asset_kind, []).append(row.symbol)
        evidence = fetch_pullback_evidence(symbols_by_kind)
        return evaluate_watchlist(watchlist, evidence)
    except Exception:
        return None


def _fetch_universe_counts() -> dict[str, int]:
    counts = {"stocks": 0, "etfs": 0}
    try:
        conn = connect_mefdb()
    except Exception:
        return counts
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM mef.universe_stock")
            counts["stocks"] = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM mef.universe_etf")
            counts["etfs"] = cur.fetchone()[0]
    finally:
        conn.close()
    return counts


def _fetch_market_data_through() -> date | None:
    try:
        conn = connect_shdb()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT GREATEST(
                    (SELECT max(bar_date) FROM mart.stock_equity_daily),
                    (SELECT max(bar_date) FROM mart.stock_etf_daily)
                )
            """)
            return cur.fetchone()[0]
    finally:
        conn.close()


def _fetch_latest_run_uid() -> str | None:
    try:
        conn = connect_mefdb()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT uid FROM mef.daily_run "
                "WHERE status IN ('ok','partial') "
                "ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _fetch_recommendations(run_uid: str) -> list[dict[str, Any]]:
    try:
        conn = connect_mefdb()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.uid, r.symbol, r.asset_kind, r.posture, r.expression,
                       r.entry_method, r.stop_level, r.target_level,
                       r.confidence, r.state, r.reasoning_summary,
                       c.engine,
                       c.llm_gate_decision, c.llm_gate_issue_type,
                       c.llm_gate_key_judgment,
                       (c.feature_json->>'close')::numeric AS close,
                       us.company_name
                  FROM mef.recommendation r
                  JOIN mef.candidate c ON r.candidate_uid = c.uid
             LEFT JOIN mef.universe_stock us ON us.symbol = r.symbol
                 WHERE r.run_uid = %s
                 ORDER BY r.confidence DESC NULLS LAST, r.symbol
                """,
                (run_uid,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _fetch_etf_posture() -> list[Any]:
    """Classify the live ETF universe from SHDB mart. Returns [] on any failure."""
    try:
        from mef.evidence import pull_latest_evidence
        from mef.etf_classifier import classify_universe
    except Exception:
        return []
    try:
        bundle = pull_latest_evidence()
    except Exception:
        return []
    etfs = {sym: row for sym, row in bundle.symbols.items()
            if row.get("asset_kind") == "etf"}
    if not etfs:
        return []
    try:
        return classify_universe(etfs)
    except Exception:
        return []


# ───────────────────────────── classification ─────────────────────────────

def _classify_actionable(rec: dict[str, Any]) -> str:
    """Return 'actionable' or 'watch' for a recommendation row.

    Primary signal is `candidate.llm_gate_decision`:
      - 'approve'                    → actionable
      - 'review' | 'unavailable' | NULL → watch

    The pipeline never inserts 'reject' rows into `recommendation`, so
    that case can't reach the status view in practice.
    """
    decision = (rec.get("llm_gate_decision") or "").strip().lower()
    return "actionable" if decision == "approve" else "watch"


_WATCH_REASON_PATTERNS = [
    (re.compile(r"posture/evidence mismatch|conflicts with the named posture", re.I), "Posture mismatch"),
    (re.compile(r"no clear sign of stabilization|without a stabilization signal|no stabilization", re.I), "No stabilization"),
    (re.compile(r"low conviction|conviction is low", re.I), "Low conviction"),
    (re.compile(r"missing context", re.I), "Missing context"),
    (re.compile(r"volatility mismatch", re.I), "Volatility mismatch"),
    (re.compile(r"risk shape", re.I), "Risk shape"),
]

_ISSUE_TYPE_LABELS = {
    "posture_mismatch":   "Posture mismatch",
    "missing_context":    "Missing context",
    "mechanical":         "Mechanical concern",
    "risk_shape":         "Risk shape",
    "volatility_mismatch":"Volatility mismatch",
    "asset_structure":    "Asset structure",
    "options_structure":  "Options structure",
}


def _watch_status(rec: dict[str, Any]) -> str:
    """Pick a short reason label for a Watch entry.

    Prefers the structured `llm_gate_issue_type` when set; falls back to
    keyword detection in `reasoning_summary` + `llm_gate_key_judgment`;
    final fallback for `unavailable`/NULL gate decisions is 'Unreviewed';
    everything else gets 'Held for review'.
    """
    issue = (rec.get("llm_gate_issue_type") or "").strip().lower()
    if issue and issue != "none" and issue in _ISSUE_TYPE_LABELS:
        return _ISSUE_TYPE_LABELS[issue]

    text = " ".join(filter(None, [
        rec.get("reasoning_summary"),
        rec.get("llm_gate_key_judgment"),
    ]))
    for pattern, label in _WATCH_REASON_PATTERNS:
        if pattern.search(text):
            return label

    decision = (rec.get("llm_gate_decision") or "").strip().lower()
    if decision in ("unavailable", ""):
        return "Unreviewed"
    return "Held for review"


def _actionable_status(rec: dict[str, Any]) -> str:
    """For approved recs, surface 'Wait for pullback' if price is above the entry zone."""
    close = rec.get("close")
    entry_hi = _entry_zone_hi(rec.get("entry_method"))
    if close is not None and entry_hi is not None and float(close) > entry_hi:
        return "Wait for pullback"
    return "Ready"


# ───────────────────────────── rendering ─────────────────────────────

LABEL_ORDER = (
    "extended_wait",
    "healthy_pullback",
    "near_entry",
    "reasonable_entry",
    "breakdown_risk",
    "neutral",
)


def _render(r: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.extend(_render_header(r))
    lines.append("")

    actionable = [x for x in r["recommendations"] if _classify_actionable(x) == "actionable"]
    watch      = [x for x in r["recommendations"] if _classify_actionable(x) == "watch"]

    if not r["recommendations"]:
        lines.append("Latest run emitted no recommendations.")
    else:
        lines.extend(_render_actionable(actionable))
        lines.append("")
        lines.extend(_render_watch(watch))

    lines.append("")
    lines.extend(_render_pullback_watchlist(r))

    # ETF posture section intentionally NOT rendered here — it overlapped
    # with Core Pullback Watchlist and confused the reader. Helper kept
    # in this module for a future dedicated view. See the module docstring.

    return "\n".join(lines)


def _render_pullback_watchlist(r: dict[str, Any]) -> list[str]:
    """Render the Job 2 section. ``None`` signals come from an outage
    inside _gather and render as a one-line "(unavailable)" note."""
    signals = r.get("pullback_signals")
    if signals is None:
        return [
            "CORE PULLBACK WATCHLIST",
            "=======================",
            "  (unavailable — repository or SHDB read failed; see logs)",
        ]
    from mef.core_pullback_render import render_section
    return render_section(signals)


def _render_header(r: dict[str, Any]) -> list[str]:
    now = r["now"].strftime('%Y-%m-%d %H:%M %Z').strip()
    parts = [f"Report: {now}"]
    if r.get("data_through"):
        parts.append(f"market data through {r['data_through']}")
    u = r.get("universe") or {}
    if u.get("stocks") or u.get("etfs"):
        parts.append(f"universe {u['stocks']} stocks / {u['etfs']} ETFs")
    return [
        "MEF — Muse Engine Forecaster",
        " · ".join(parts),
    ]


WATCH_ACTION_LABEL = "Watch"


def _render_actionable(recs: list[dict[str, Any]]) -> list[str]:
    out = [f"Actionable Stock Ideas ({len(recs)})", ""]
    if not recs:
        out.append("  No actionable ideas right now.")
        return out
    blocks: list[str] = []
    for rec in recs:
        action = _action_label(rec.get("expression"))
        blocks.append("\n".join(_format_idea_block(rec, action, _actionable_status(rec))))
    out.append("\n\n".join(blocks))
    return out


def _render_watch(recs: list[dict[str, Any]]) -> list[str]:
    out = [f"Watch / Not Actionable ({len(recs)})", ""]
    if not recs:
        out.append("  Nothing on watch.")
        return out
    blocks: list[str] = []
    for rec in recs:
        # Action label is fixed to "Watch" so the header never implies a buy.
        blocks.append("\n".join(_format_idea_block(rec, WATCH_ACTION_LABEL, _watch_status(rec))))
    out.append("\n\n".join(blocks))
    return out


def _format_idea_block(rec: dict[str, Any], action_label: str, status_label: str) -> list[str]:
    sym = rec.get("symbol") or "?"
    thesis = _short_reason(rec.get("reasoning_summary"), max_len=70)
    head = f"  {sym} — {action_label} / {status_label}"
    if thesis:
        head = f"{head} — {thesis}"

    plan = (
        f"    Entry {_fmt_entry_zone(rec.get('entry_method'))} · "
        f"Stop {_fmt_dollars(rec.get('stop_level'))} · "
        f"Target {_fmt_dollars(rec.get('target_level'))} · "
        f"{_fmt_conf(rec.get('confidence'))} conv"
    )

    detail = rec.get("llm_gate_key_judgment") or rec.get("reasoning_summary") or ""
    detail_line = f"    {_truncate(detail, 96)}" if detail else ""

    return [head, plan] + ([detail_line] if detail_line else [])


def _render_etf_posture(r: dict[str, Any]) -> list[str]:
    labels = r.get("etf_posture") or []
    if not labels:
        return ["ETF posture", "  (unavailable)"]

    by_label: dict[str, list[Any]] = {k: [] for k in LABEL_ORDER}
    for entry in labels:
        by_label.setdefault(entry.label, []).append(entry)

    lines = [f"ETF posture ({len(labels)})"]
    for label in LABEL_ORDER:
        bucket = by_label.get(label, [])
        lines.append(f"  {label} ({len(bucket)})")
        if not bucket:
            lines.append("    (none)")
            continue
        for e in sorted(bucket, key=lambda x: x.symbol):
            lines.append(f"    {e.symbol:<6}  {e.reason}")
    return lines


# ───────────────────────────── formatters ─────────────────────────────

def _action_label(expression: str | None) -> str:
    if not expression:
        return "?"
    return {"buy_shares": "Buy", "sell_shares": "Sell", "short_shares": "Short"}.get(
        expression, expression.replace("_", " ").title()
    )


def _fmt_conf(v) -> str:
    if v is None:
        return "?"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "?"


def _fmt_dollars(v) -> str:
    if v is None:
        return "?"
    try:
        return f"${int(round(float(v)))}"
    except (TypeError, ValueError):
        return "?"


_ENTRY_ZONE_RE = re.compile(r"\$([0-9.]+)\s*-\s*\$([0-9.]+)")


def _fmt_entry_zone(entry_method: str | None) -> str:
    if not entry_method:
        return "?"
    m = _ENTRY_ZONE_RE.search(entry_method)
    if not m:
        return entry_method
    lo = int(round(float(m.group(1))))
    hi = int(round(float(m.group(2))))
    return f"${lo}-${hi}"


def _entry_zone_hi(entry_method: str | None) -> float | None:
    if not entry_method:
        return None
    m = _ENTRY_ZONE_RE.search(entry_method)
    if not m:
        return None
    try:
        return float(m.group(2))
    except ValueError:
        return None


def _short_reason(text: str | None, max_len: int = 80) -> str:
    if not text:
        return ""
    head = re.split(r"[.;—]", text, maxsplit=1)[0].strip()
    if len(head) > max_len:
        return head[: max_len - 1] + "…"
    return head


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
