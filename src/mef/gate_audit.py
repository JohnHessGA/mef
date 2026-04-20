"""LLM-gate audit aggregations.

Reads ``mef.paper_score`` (every emitted rec, gate_decision in
approve/unavailable) and ``mef.shadow_score`` (every rejected
candidate) — both produced by the same forward-walk methodology — and
summarizes their outcome distributions side-by-side.

The hypothesis under test: **the LLM gate is helping**, i.e. the
approved group has a materially better outcome distribution than the
rejected group. If win rate, avg P&L, and SPY-relative return are all
roughly equal between approved and rejected, the gate is adding cost
(LLM API + latency) without value.

Sample-size discipline: a difference is meaningless until both sides
have ~20 settled outcomes. Below that, the report flags itself as
under-powered and the user should not act on the numbers.

Pure-data layer here. The CLI presentation (``commands/gate_audit.py``)
formats this into a human-readable table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mef.db.connection import connect_mefdb


# Approved outcomes are read from mef.paper_score (gate_decision='approve').
# Rejected outcomes are read from mef.shadow_score (always gate_decision='reject').
# Unavailable (gate down) outcomes live in paper_score with gate_decision='unavailable'
# and are reported as a third group so we can see whether falling back to
# "ship without LLM review" is itself worse than rejecting.

MIN_SAMPLE_FOR_SIGNAL = 20


@dataclass
class OutcomeStats:
    """Aggregated outcome distribution for one decision group."""
    label: str                       # 'approved' | 'rejected' | 'unavailable'
    n: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    pnl_100sh_total: float = 0.0
    pnl_100sh_count: int = 0
    spy_rel_total: float = 0.0
    spy_rel_count: int = 0
    sector_rel_total: float = 0.0
    sector_rel_count: int = 0
    days_held_total: int = 0
    days_held_count: int = 0
    by_outcome: dict[str, int] = field(default_factory=dict)

    @property
    def win_rate(self) -> float | None:
        return (self.wins / self.n) if self.n else None

    @property
    def avg_pnl_100sh(self) -> float | None:
        return (self.pnl_100sh_total / self.pnl_100sh_count) if self.pnl_100sh_count else None

    @property
    def avg_spy_relative(self) -> float | None:
        """Average of (paper return - SPY return over same window) across rows
        where both are available. Computed from per-row entry/exit prices."""
        return (self.spy_rel_total / self.spy_rel_count) if self.spy_rel_count else None

    @property
    def avg_sector_relative(self) -> float | None:
        return (self.sector_rel_total / self.sector_rel_count) if self.sector_rel_count else None

    @property
    def avg_days_held(self) -> float | None:
        return (self.days_held_total / self.days_held_count) if self.days_held_count else None

    @property
    def has_signal_quality_sample(self) -> bool:
        return self.n >= MIN_SAMPLE_FOR_SIGNAL


def _absorb_row(stats: OutcomeStats, row: dict[str, Any]) -> None:
    """Fold one paper/shadow row into the running totals.

    Per-row math:
      paper_return  = (exit_price - entry_price) / entry_price
      spy_relative  = paper_return - spy_return_same_window
      sector_rel    = paper_return - sector_etf_return_same_window
    SPY/sector returns are NUMERIC fractions already in the source row.
    """
    stats.n += 1
    outcome = row.get("outcome")
    if outcome == "win":
        stats.wins += 1
    elif outcome == "loss":
        stats.losses += 1
    elif outcome == "timeout":
        stats.timeouts += 1
    if outcome:
        stats.by_outcome[outcome] = stats.by_outcome.get(outcome, 0) + 1

    pnl = row.get("estimated_pnl_100_shares_usd")
    if pnl is not None:
        stats.pnl_100sh_total += float(pnl)
        stats.pnl_100sh_count += 1

    days = row.get("days_held")
    if days is not None:
        stats.days_held_total += int(days)
        stats.days_held_count += 1

    entry = row.get("entry_price")
    exit_p = row.get("exit_price")
    if entry is not None and exit_p is not None and float(entry) != 0:
        paper_ret = (float(exit_p) - float(entry)) / float(entry)
        spy = row.get("spy_return_same_window")
        if spy is not None:
            stats.spy_rel_total += paper_ret - float(spy)
            stats.spy_rel_count += 1
        sec = row.get("sector_etf_return_same_window")
        if sec is not None:
            stats.sector_rel_total += paper_ret - float(sec)
            stats.sector_rel_count += 1


def _fetch_paper_rows(conn, gate_decision: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT outcome, entry_price, exit_price, days_held,
                   estimated_pnl_100_shares_usd,
                   spy_return_same_window,
                   sector_etf_return_same_window
              FROM mef.paper_score
             WHERE gate_decision = %s
            """,
            (gate_decision,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _fetch_shadow_rows(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT outcome, entry_price, exit_price, days_held,
                   estimated_pnl_100_shares_usd,
                   spy_return_same_window,
                   sector_etf_return_same_window
              FROM mef.shadow_score
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def aggregate(rows: list[dict[str, Any]], *, label: str) -> OutcomeStats:
    """Pure: fold a list of paper/shadow rows into an OutcomeStats."""
    stats = OutcomeStats(label=label)
    for row in rows:
        _absorb_row(stats, row)
    return stats


@dataclass
class GateAuditReport:
    approved: OutcomeStats
    review: OutcomeStats
    rejected: OutcomeStats
    unavailable: OutcomeStats
    sample_warning: str | None     # set when approved/review/rejected < MIN_SAMPLE_FOR_SIGNAL


def build_report() -> GateAuditReport:
    """Read the live tables and build the comparison report.

    Approved + review + unavailable outcomes live in mef.paper_score (each
    keyed by gate_decision). Rejected outcomes live in mef.shadow_score
    (always gate_decision='reject'). Both tables use the same forward-walk
    methodology so the four columns are directly comparable.
    """
    conn = connect_mefdb()
    try:
        approved_rows = _fetch_paper_rows(conn, "approve")
        review_rows = _fetch_paper_rows(conn, "review")
        unavail_rows = _fetch_paper_rows(conn, "unavailable")
        rejected_rows = _fetch_shadow_rows(conn)
    finally:
        conn.close()

    approved = aggregate(approved_rows, label="approved")
    review = aggregate(review_rows, label="review")
    rejected = aggregate(rejected_rows, label="rejected")
    unavailable = aggregate(unavail_rows, label="unavailable")

    warn = None
    if (
        approved.n < MIN_SAMPLE_FOR_SIGNAL
        or rejected.n < MIN_SAMPLE_FOR_SIGNAL
    ):
        warn = (
            f"Sample insufficient: need ~{MIN_SAMPLE_FOR_SIGNAL}+ settled outcomes per side "
            f"(have approved={approved.n}, review={review.n}, rejected={rejected.n}). "
            f"Treat any apparent gap as noise until approved and rejected both cross that threshold."
        )

    return GateAuditReport(
        approved=approved, review=review, rejected=rejected, unavailable=unavailable,
        sample_warning=warn,
    )
