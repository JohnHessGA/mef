"""`mef score` — score every closed rec that doesn't have a score row yet.

Also runs the LLM-gate audit: shadow-scores any rejected candidate whose
time_exit has elapsed (or that hit stop/target along the way), so we can
later compare approved-vs-rejected outcome distributions.

Idempotent. Re-runs on the same closed recs are no-ops.
"""

from __future__ import annotations

from mef.paper_scoring import paper_score_emitted
from mef.scoring import score_all_pending
from mef.shadow_scoring import shadow_score_rejected


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

    # ────────── LLM-gate audit: shadow-score rejected candidates ──────────
    shadow = shadow_score_rejected()
    print()
    print("Shadow scoring (LLM-rejected candidates)")
    print("----------------------------------------")
    print(f"  rejects already shadow-scored:  {shadow.already_scored}")
    print(f"  new shadow_score rows written:  {len(shadow.new_rows)}")
    print(f"  deferred (time_exit not yet):   {len(shadow.deferred)}")
    print(f"  skipped (missing inputs):       {len(shadow.skipped)}")

    if shadow.new_rows:
        print()
        print(f"{'shadow':<11} {'symbol':<6} {'outcome':<8} "
              f"{'entry':>10} {'exit':>10} {'days':>5} "
              f"{'P&L/100sh':>12} {'SPY':>8} {'sector':>5} {'sec ret':>8}")
        print("─" * 95)
        for r in shadow.new_rows:
            print(
                f"{r['shadow_score_uid']:<11} {r['symbol']:<6} {r['outcome']:<8} "
                f"{_money(r.get('entry_price')):>10} {_money(r.get('exit_price')):>10} "
                f"{(r.get('days_held') if r.get('days_held') is not None else '-'):>5} "
                f"{_money(r.get('pnl_100sh')):>12} "
                f"{_pct(r.get('spy_window')):>8} "
                f"{(r.get('sector_etf') or '-'):>5} "
                f"{_pct(r.get('sector_window')):>8}"
            )

    # ────────── Paper trading: forward-walk every emitted rec ──────────
    paper = paper_score_emitted()
    print()
    print("Paper trading (every emitted recommendation)")
    print("--------------------------------------------")
    print(f"  emitted recs already paper-scored:  {paper.already_scored}")
    print(f"  new paper_score rows written:       {len(paper.new_rows)}")
    print(f"  deferred (time_exit not yet):       {len(paper.deferred)}")
    print(f"  skipped (missing inputs):           {len(paper.skipped)}")

    if paper.new_rows:
        print()
        print(f"{'paper':<11} {'rec':<11} {'symbol':<6} {'gate':<11} {'outcome':<8} "
              f"{'entry':>10} {'exit':>10} {'days':>5} "
              f"{'P&L/100sh':>12} {'SPY':>8} {'sector':>5} {'sec ret':>8}")
        print("─" * 119)
        for r in paper.new_rows:
            print(
                f"{r['paper_score_uid']:<11} {r['rec_uid']:<11} {r['symbol']:<6} "
                f"{r['gate_decision']:<11} {r['outcome']:<8} "
                f"{_money(r.get('entry_price')):>10} {_money(r.get('exit_price')):>10} "
                f"{(r.get('days_held') if r.get('days_held') is not None else '-'):>5} "
                f"{_money(r.get('pnl_100sh')):>12} "
                f"{_pct(r.get('spy_window')):>8} "
                f"{(r.get('sector_etf') or '-'):>5} "
                f"{_pct(r.get('sector_window')):>8}"
            )

    return 0
