"""`mef score` — score every closed rec that doesn't have a score row yet.

Idempotent. Re-runs on the same closed recs are no-ops.
"""

from __future__ import annotations

from mef.scoring import score_all_pending


def _money(v) -> str:
    return f"${v:,.2f}" if v is not None else "n/a"


def _pct(v) -> str:
    return f"{v:+.1%}" if v is not None else "n/a"


def run(args) -> int:
    summary = score_all_pending()

    print("MEF score")
    print("=========")
    print(f"  closed recs already scored:  {summary.already_scored}")
    print(f"  new score rows written:      {len(summary.new_rows)}")
    print(f"  skipped (insufficient data): {len(summary.skipped)}")
    print()

    if summary.new_rows:
        print(f"{'rec':<11} {'symbol':<6} {'outcome':<8} "
              f"{'entry':>10} {'exit':>10} {'days':>5} "
              f"{'P&L/100sh':>12} {'SPY':>8} {'sector':>5} {'sec ret':>8}")
        print("─" * 95)
        for r in summary.new_rows:
            print(
                f"{r['rec_uid']:<11} {r['symbol']:<6} {r['outcome']:<8} "
                f"{_money(r['entry_price']):>10} {_money(r['exit_price']):>10} "
                f"{r['days_held']:>5} "
                f"{_money(r['pnl_100sh']):>12} "
                f"{_pct(r['spy_window']):>8} "
                f"{(r['sector_etf'] or '-'):>5} "
                f"{_pct(r['sector_window']):>8}"
            )
            if r.get("state_aligned"):
                print(f"  ↳ rec.state aligned to closed_{r['outcome']}")

    if summary.skipped:
        print()
        print("Skipped:")
        for s in summary.skipped:
            print(f"  {s['symbol']:<6} {s['rec_uid']}  {s['reason']}")

    return 0
