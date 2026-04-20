"""`mef gate-audit` — compare approved vs rejected outcome distributions.

Reads the synthetic-outcome tables (mef.paper_score for approve/unavailable
and mef.shadow_score for reject), prints a side-by-side comparison so
you can answer: **is the LLM gate adding value, or just cost?**

The gate adds value if approved outcomes beat rejected outcomes on win
rate, P&L per 100 shares, and SPY-relative return — by enough to clear
the noise floor of the available sample.
"""

from __future__ import annotations

from mef.gate_audit import GateAuditReport, OutcomeStats, build_report


def _pct(v: float | None, places: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:+.{places}f}%"


def _money(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"${v:+,.2f}"


def _ratio(num: int, den: int) -> str:
    if den == 0:
        return "n/a"
    return f"{(num / den) * 100:.1f}% ({num}/{den})"


def _row(label: str, app: str, rev: str, rej: str, unavail: str) -> str:
    return f"  {label:<22} {app:>14} {rev:>14} {rej:>14} {unavail:>16}"


def _section(stats: OutcomeStats) -> dict[str, str]:
    return {
        "n":         f"{stats.n}",
        "win_rate":  _ratio(stats.wins, stats.n),
        "wlt":       f"W {stats.wins}  L {stats.losses}  T {stats.timeouts}",
        "pnl":       _money(stats.avg_pnl_100sh),
        "spy_rel":   _pct(stats.avg_spy_relative),
        "sec_rel":   _pct(stats.avg_sector_relative),
        "days":      (f"{stats.avg_days_held:.1f}" if stats.avg_days_held is not None else "n/a"),
    }


def _print_report(report: GateAuditReport) -> None:
    print("MEF gate audit")
    print("==============")
    print()
    print("Question: is the LLM gate's approve/reject signal predictive of")
    print("downstream outcomes? Comparison is methodology-matched: both sides")
    print("use the same close-of-run-day entry and stop/target/time_exit rules.")
    print()

    if report.sample_warning:
        print(f"⚠ {report.sample_warning}")
        print()

    a = _section(report.approved)
    v = _section(report.review)
    r = _section(report.rejected)
    u = _section(report.unavailable)

    print(_row("", "Approved", "Review",   "Rejected", "Unavailable"))
    print(_row("", "(paper)",  "(paper)",  "(shadow)", "(paper, gate down)"))
    print("  " + "─" * 84)
    print(_row("Settled outcomes",     a["n"],        v["n"],        r["n"],        u["n"]))
    print(_row("Win rate",             a["win_rate"], v["win_rate"], r["win_rate"], u["win_rate"]))
    print(_row("Outcome breakdown",    a["wlt"],      v["wlt"],      r["wlt"],      u["wlt"]))
    print(_row("Avg P&L / 100sh",      a["pnl"],      v["pnl"],      r["pnl"],      u["pnl"]))
    print(_row("Avg vs SPY",           a["spy_rel"],  v["spy_rel"],  r["spy_rel"],  u["spy_rel"]))
    print(_row("Avg vs sector ETF",    a["sec_rel"],  v["sec_rel"],  r["sec_rel"],  u["sec_rel"]))
    print(_row("Avg days held",        a["days"],     v["days"],     r["days"],     u["days"]))
    print()

    # Headline interpretation (only when both sides have signal-grade samples).
    if report.approved.has_signal_quality_sample and report.rejected.has_signal_quality_sample:
        diffs = []
        if report.approved.win_rate is not None and report.rejected.win_rate is not None:
            diffs.append(("win rate", (report.approved.win_rate - report.rejected.win_rate) * 100, "pp"))
        if report.approved.avg_pnl_100sh is not None and report.rejected.avg_pnl_100sh is not None:
            diffs.append(("P&L/100sh", report.approved.avg_pnl_100sh - report.rejected.avg_pnl_100sh, "$"))
        if report.approved.avg_spy_relative is not None and report.rejected.avg_spy_relative is not None:
            diffs.append(
                ("vs-SPY", (report.approved.avg_spy_relative - report.rejected.avg_spy_relative) * 100, "pp")
            )
        print("Approved minus rejected (positive = gate is helping):")
        for name, val, unit in diffs:
            sign = "+" if val >= 0 else ""
            if unit == "$":
                print(f"  {name:<12} {sign}${val:,.2f}")
            else:
                print(f"  {name:<12} {sign}{val:.1f}{unit}")
    else:
        print("Headline diff withheld until both sides have a usable sample.")


def run(args) -> int:
    report = build_report()
    _print_report(report)
    return 0
