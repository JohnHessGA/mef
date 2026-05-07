"""`mef status` — current MEF recommendation report (read-only).

Single user-facing view answering "what does MEF currently think?".
Reads MEFDB, OW, and SHDB; never writes; never sends email; never runs
the pipeline. Pure reporting layer over what the latest scheduled run
already produced.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from mef.db.connection import connect_mefdb, connect_overwatch, connect_shdb


# ───────────────────────────── public entry ─────────────────────────────

def run(args) -> int:
    report = _gather()
    print(_render(report))
    return 0


# ───────────────────────────── data gathering ─────────────────────────────

def _gather() -> dict[str, Any]:
    out: dict[str, Any] = {
        "now": datetime.now().astimezone(),
    }
    out["universe"] = _fetch_universe_counts()
    out["latest_run"] = _fetch_latest_run()
    if out["latest_run"]:
        out["recommendations"] = _fetch_recommendations(out["latest_run"]["uid"])
    else:
        out["recommendations"] = []
    out["mart_freshness"] = _fetch_mart_freshness()
    out["recent_alerts"] = _fetch_recent_alerts(hours=24)
    out["etf_posture"] = _fetch_etf_posture()
    return out


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


def _fetch_latest_run() -> dict[str, Any] | None:
    try:
        conn = connect_mefdb()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT uid, when_kind, intent, status, started_at, ended_at,
                       symbols_evaluated, candidates_passed, recommendations_emitted,
                       email_sent_at
                  FROM mef.daily_run
                 ORDER BY started_at DESC
                 LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
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
                       c.engine, c.hazard_event_type, c.hazard_flags,
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


def _fetch_mart_freshness() -> dict[str, Any]:
    """Compute mart freshness using the same source set and thresholds as the pipeline.

    Pipeline rule (mef.evidence.check_freshness, strictly >):
        age <= warn_after_calendar_days   → ok
        age >  warn_after_calendar_days   → warn (stale)
        age >  abort_after_calendar_days  → abort
    """
    from datetime import date

    out: dict[str, Any] = {
        "latest_bar": None, "days_behind": None,
        "tier": None,  # "ok" | "stale" | "abort" | None
        "warn_threshold": 4, "abort_threshold": 7,
    }

    try:
        from mef.config import load_app_config
        cfg = load_app_config().get("data_freshness", {}) or {}
        out["warn_threshold"] = int(cfg.get("warn_after_calendar_days", 4))
        out["abort_threshold"] = int(cfg.get("abort_after_calendar_days", 7))
    except Exception:
        pass  # fall through with defaults

    try:
        conn = connect_shdb()
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT GREATEST(
                    (SELECT max(bar_date) FROM mart.stock_equity_daily),
                    (SELECT max(bar_date) FROM mart.stock_etf_daily)
                )
            """)
            latest = cur.fetchone()[0]
    finally:
        conn.close()

    if latest is None:
        return out

    days = (date.today() - latest).days
    out["latest_bar"] = latest
    out["days_behind"] = days
    if days > out["abort_threshold"]:
        out["tier"] = "abort"
    elif days > out["warn_threshold"]:
        out["tier"] = "stale"
    else:
        out["tier"] = "ok"
    return out


def _fetch_recent_alerts(hours: int = 24) -> dict[str, list[tuple[str, int]]]:
    """Return {'error': [(code, n), ...], 'warning': [...]}."""
    out: dict[str, list[tuple[str, int]]] = {"error": [], "warning": []}
    try:
        conn = connect_overwatch()
    except Exception:
        return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT severity, code, count(*)
                  FROM ow.mef_event
                 WHERE severity IN ('error','warning')
                   AND created_at > now() - (%s || ' hours')::interval
                 GROUP BY severity, code
                 ORDER BY 1, 3 DESC
                """,
                (str(hours),),
            )
            for severity, code, n in cur.fetchall():
                out.setdefault(severity, []).append((code, int(n)))
    finally:
        conn.close()
    return out


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
    lines.extend(_render_latest_run(r))
    lines.append("")
    lines.extend(_render_data_status(r))
    lines.append("")
    lines.extend(_render_recommendations(r))
    lines.append("")
    lines.extend(_render_etf_posture(r))
    return "\n".join(lines)


def _render_header(r: dict[str, Any]) -> list[str]:
    now = r["now"]
    u = r["universe"]
    return [
        "MEF — Muse Engine Forecaster",
        f"Report: {now.strftime('%Y-%m-%d %H:%M %Z').strip()}"
        f"   |   Universe: {u['stocks']} stocks · {u['etfs']} ETFs",
    ]


def _render_latest_run(r: dict[str, Any]) -> list[str]:
    run = r["latest_run"]
    if not run:
        return ["Latest run", "  (none — MEF has not been run yet)"]
    started = _fmt_dt(run.get("started_at"))
    ended = run.get("ended_at")
    duration = _fmt_duration(run.get("started_at"), ended) if ended else "running"
    lines = [
        "Latest run",
        f"  uid:           {run['uid']}",
        f"  started:       {started} ({run.get('when_kind','?')}, {duration}, status={run.get('status','?')})",
    ]
    pipeline = (
        f"{run.get('symbols_evaluated','?')} evaluated → "
        f"{run.get('candidates_passed','?')} passed → "
        f"{run.get('recommendations_emitted','?')} emitted"
    )
    lines.append(f"  pipeline:      {pipeline}")
    return lines


def _render_data_status(r: dict[str, Any]) -> list[str]:
    lines = ["Data status"]
    f = r["mart_freshness"]
    if f.get("latest_bar") is None:
        lines.append("  SHDB mart:     unavailable")
    else:
        tier = f.get("tier")
        if tier == "ok":
            tag = "fresh"
        elif tier == "stale":
            tag = f"STALE ({f['days_behind']}d behind, warn>{f['warn_threshold']})"
        elif tier == "abort":
            tag = f"ABORT ({f['days_behind']}d behind, abort>{f['abort_threshold']})"
        else:
            tag = f"unknown ({f.get('days_behind','?')}d)"
        lines.append(f"  SHDB mart:     latest bar {f['latest_bar']} ({tag})")

    alerts = r["recent_alerts"]
    err_total = sum(n for _, n in alerts.get("error", []))
    warn_total = sum(n for _, n in alerts.get("warning", []))
    if not err_total and not warn_total:
        lines.append("  Alerts (24h):  none")
    else:
        parts = []
        if err_total:
            err_codes = ", ".join(f"{c}×{n}" for c, n in alerts["error"])
            parts.append(f"{err_total} error ({err_codes})")
        if warn_total:
            warn_codes = ", ".join(f"{c}×{n}" for c, n in alerts["warning"])
            parts.append(f"{warn_total} warning ({warn_codes})")
        lines.append(f"  Alerts (24h):  {' · '.join(parts)}")
    return lines


def _render_recommendations(r: dict[str, Any]) -> list[str]:
    recs = r["recommendations"]
    if not recs:
        return ["Recommendations", "  (latest run emitted no recommendations)"]

    lines = [f"Recommendations ({len(recs)})"]
    header = (
        f"  {'conv':>4}  {'sym':<5}  {'name':<22}  "
        f"{'engine':<8}  {'posture':<17}  "
        f"{'entry':<11}  {'stop':>5}  {'target':>6}"
    )
    lines.append(header)
    for rec in recs:
        lines.extend(_format_rec_block(rec))
    return lines


def _format_rec_block(rec: dict[str, Any]) -> list[str]:
    conv = _fmt_conf(rec.get("confidence"))
    sym = (rec.get("symbol") or "?")[:5]
    name = _short_name(rec.get("company_name"), 22)
    engine = _short_engine(rec.get("engine"))[:8]
    posture = (rec.get("posture") or "")[:17]
    entry = _fmt_entry_zone(rec.get("entry_method"))[:11]
    stop = _fmt_dollars(rec.get("stop_level"))
    target = _fmt_dollars(rec.get("target_level"))
    head = (
        f"  {conv:>4}  {sym:<5}  {name:<22}  "
        f"{engine:<8}  {posture:<17}  "
        f"{entry:<11}  {stop:>5}  {target:>6}"
    )

    reason = _short_reason(rec.get("reasoning_summary"), max_len=90)
    flags = _meaningful_hazards(rec.get("hazard_event_type"), rec.get("hazard_flags"))
    detail = "        " + reason if reason else ""
    if flags:
        suffix = f"  [{', '.join(flags)}]"
        detail = (detail + suffix) if detail else "        " + suffix.lstrip()

    out = [head]
    if detail:
        out.append(detail)
    return out


def _short_name(name: str | None, max_len: int) -> str:
    if not name:
        return ""
    name = name.strip()
    return name if len(name) <= max_len else name[: max_len - 1] + "…"


_GENERIC_HAZARD_FLAGS = {"macro:other"}


def _meaningful_hazards(event_type: str | None, flags) -> list[str]:
    """Return the subset of hazard signals worth surfacing in the terminal.

    `macro:other` is the generic baseline tag emitted on every candidate
    and adds no information; suppress it. Flags like `macro:fomc`,
    `macro:pce`, and any `earn_prox:*` carry actual signal.
    """
    out: list[str] = []
    if event_type and event_type != "other":
        out.append(f"event:{event_type}")
    if flags:
        for f in flags:
            if f and f not in _GENERIC_HAZARD_FLAGS:
                out.append(f)
    return out


def _render_etf_posture(r: dict[str, Any]) -> list[str]:
    labels = r["etf_posture"]
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

_ENGINE_SHORT = {
    "trend": "trend",
    "value": "value",
    "mean_reversion": "mean_rev",
}


def _short_engine(engine: str | None) -> str:
    if not engine:
        return "?"
    return _ENGINE_SHORT.get(engine, engine)


def _fmt_conf(v) -> str:
    if v is None:
        return "?"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "?"


def _fmt_dollars(v) -> str:
    """Whole-dollar formatting for prices: 84.45 → '$84'."""
    if v is None:
        return "?"
    try:
        return f"${int(round(float(v)))}"
    except (TypeError, ValueError):
        return "?"


_ENTRY_ZONE_RE = re.compile(r"\$([0-9.]+)\s*-\s*\$([0-9.]+)")


def _fmt_entry_zone(entry_method: str | None) -> str:
    """Parse entry_method like 'limit order $76.63-$78.19' → '$77-$78'."""
    if not entry_method:
        return "?"
    m = _ENTRY_ZONE_RE.search(entry_method)
    if not m:
        return entry_method[:14]
    lo = int(round(float(m.group(1))))
    hi = int(round(float(m.group(2))))
    return f"${lo}-${hi}"


def _short_reason(text: str | None, max_len: int = 80) -> str:
    if not text:
        return ""
    # Take first sentence-ish chunk (split on period, semicolon, or em-dash).
    head = re.split(r"[.;—]", text, maxsplit=1)[0].strip()
    if len(head) > max_len:
        return head[: max_len - 1] + "…"
    return head


def _fmt_dt(dt) -> str:
    if dt is None:
        return "?"
    if isinstance(dt, datetime):
        local = dt.astimezone() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone()
        return local.strftime("%Y-%m-%d %H:%M %Z").strip()
    return str(dt)


def _fmt_duration(start, end) -> str:
    if start is None or end is None:
        return "?"
    try:
        secs = int((end - start).total_seconds())
    except Exception:
        return "?"
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m{secs % 60:02d}s"
