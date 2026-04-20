"""Auto-activate proposed recommendations from the latest position snapshot.

Rules (v1, match ``docs/mef_design_spec.md`` §7.3):

- The recommendation must be in state ``proposed``.
- A row in ``mef.position_snapshot`` for the latest ``import_batch`` must
  have the same ``symbol``.
- ``quantity >= position_matching.min_quantity_match`` (config, default 50).
- ``cost_basis_per_share`` (or ``last_price`` fallback if cost basis is
  missing) must be within ``entry_price_tolerance_pct`` of the midpoint
  of the draft entry zone parsed from the proposed recommendation.

On a match we flip state ``proposed → active``, link
``active_match_position_uid``, and stamp ``provenance`` based on when
the position first appeared in our import history relative to the rec's
creation date and entry window. See ``infer_provenance`` for the rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from mef.config import load_app_config
from mef.db.connection import connect_mefdb


def infer_provenance(
    *,
    earliest_position_date: date | None,
    rec_created_date: date,
    entry_window_end: date | None,
) -> str:
    """Classify how a position came to match a recommendation.

    Pure function — caller injects the dates so this is testable without
    a DB. ``earliest_position_date`` is the min ``as_of_date`` for this
    symbol across the entire ``mef.position_snapshot`` history.

    Returns one of: 'mef_attributed' | 'pre_existing' | 'independent'.

    Rules (per docs and 2026-04-19 design discussion):
      - earliest < rec_created       → pre_existing
      - rec_created <= earliest <= entry_window_end → mef_attributed
      - else (after window, or no entry_window_end) → independent
      - earliest is None             → independent (no history)
    """
    if earliest_position_date is None:
        return "independent"
    if earliest_position_date < rec_created_date:
        return "pre_existing"
    if entry_window_end is not None and earliest_position_date <= entry_window_end:
        return "mef_attributed"
    return "independent"


@dataclass
class ActivationResult:
    activated: list[dict[str, Any]]        # rec dicts that flipped proposed → active
    considered: int                         # number of proposed recs scanned


# Matches "$270.00-$275.00" or "limit order $270-$275" — any two dollar
# values separated by '-' (tolerating decimals and optional $).
_ZONE_RE = re.compile(
    r"\$?(?P<low>\d+(?:\.\d+)?)\s*-\s*\$?(?P<high>\d+(?:\.\d+)?)"
)


def _parse_zone_midpoint(zone_text: str | None) -> Decimal | None:
    if not zone_text:
        return None
    m = _ZONE_RE.search(zone_text)
    if not m:
        return None
    try:
        low = Decimal(m.group("low"))
        high = Decimal(m.group("high"))
    except Exception:
        return None
    return (low + high) / Decimal(2)


def _latest_import_uid(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uid FROM mef.import_batch "
            " WHERE status = 'ok' "
            " ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    return row[0] if row else None


def _load_proposed(conn) -> list[dict[str, Any]]:
    """Proposed recs joined to their candidate's entry zone text.

    Rules that keep activation idempotent:
    - If a symbol already has an active rec, skip it entirely — the user is
      already tracking a position for that idea.
    - Otherwise return only the newest proposed per symbol; older duplicates
      wait for the auto-expiration sweep (milestone 7).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH already_active AS (
                SELECT DISTINCT symbol
                  FROM mef.recommendation
                 WHERE state = 'active'
            )
            SELECT DISTINCT ON (r.symbol)
                   r.uid, r.symbol, r.entry_method,
                   r.created_at::date AS rec_created_date,
                   r.entry_window_end,
                   c.proposed_entry_zone
              FROM mef.recommendation r
              LEFT JOIN mef.candidate c ON c.uid = r.candidate_uid
             WHERE r.state = 'proposed'
               AND r.symbol NOT IN (SELECT symbol FROM already_active)
             ORDER BY r.symbol, r.created_at DESC
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _earliest_position_dates(conn, symbols: list[str]) -> dict[str, date]:
    """Return {symbol: earliest as_of_date in mef.position_snapshot}.

    Symbols never seen in any import are absent from the dict.
    """
    if not symbols:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, MIN(as_of_date) AS earliest
              FROM mef.position_snapshot
             WHERE symbol = ANY(%s)
               AND as_of_date IS NOT NULL
             GROUP BY symbol
            """,
            (symbols,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _load_latest_positions_by_symbol(conn, import_uid: str) -> dict[str, dict[str, Any]]:
    """Return the largest matching position per symbol in the latest import."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT uid, symbol, quantity, cost_basis_per_share, last_price
              FROM mef.position_snapshot
             WHERE import_uid = %s
             ORDER BY symbol, quantity DESC NULLS LAST
            """,
            (import_uid,),
        )
        cols = [d[0] for d in cur.description]
        out: dict[str, dict[str, Any]] = {}
        for row in cur.fetchall():
            record = dict(zip(cols, row))
            sym = record["symbol"]
            if sym not in out:
                out[sym] = record
    return out


def _promote(
    conn,
    *,
    rec_uid: str,
    position_uid: str,
    provenance: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE mef.recommendation
               SET state                     = 'active',
                   state_changed_at          = now(),
                   state_changed_by          = 'import',
                   active_match_position_uid = %s,
                   provenance                = %s,
                   provenance_set_by         = 'activator',
                   updated_at                = now()
             WHERE uid = %s
               AND state = 'proposed'
            """,
            (position_uid, provenance, rec_uid),
        )
    conn.commit()


def activate_from_latest_import() -> ActivationResult:
    """Run after a successful CSV import — flip any qualifying proposed recs."""
    cfg = load_app_config()
    match_cfg = cfg.get("position_matching") or {}
    min_qty = Decimal(str(match_cfg.get("min_quantity_match", 50)))
    tol_pct = Decimal(str(match_cfg.get("entry_price_tolerance_pct", 5.0)))
    tol_frac = tol_pct / Decimal(100)

    conn = connect_mefdb()
    try:
        import_uid = _latest_import_uid(conn)
        if not import_uid:
            return ActivationResult(activated=[], considered=0)

        positions = _load_latest_positions_by_symbol(conn, import_uid)
        proposed = _load_proposed(conn)
        # Earliest position date per symbol drives provenance inference.
        symbols_to_check = [r["symbol"] for r in proposed if positions.get(r["symbol"])]
        earliest_dates = _earliest_position_dates(conn, symbols_to_check)

        activated: list[dict[str, Any]] = []
        for rec in proposed:
            pos = positions.get(rec["symbol"])
            if not pos:
                continue

            qty = pos.get("quantity")
            if qty is None or qty < min_qty:
                continue

            zone_text = rec["proposed_entry_zone"] or rec["entry_method"]
            midpoint = _parse_zone_midpoint(zone_text)
            if midpoint is None:
                continue  # can't judge — leave as proposed

            anchor = pos.get("cost_basis_per_share") or pos.get("last_price")
            if anchor is None:
                continue

            delta_frac = abs(Decimal(str(anchor)) - midpoint) / midpoint
            if delta_frac > tol_frac:
                continue

            provenance = infer_provenance(
                earliest_position_date=earliest_dates.get(rec["symbol"]),
                rec_created_date=rec["rec_created_date"],
                entry_window_end=rec["entry_window_end"],
            )
            _promote(
                conn, rec_uid=rec["uid"], position_uid=pos["uid"], provenance=provenance,
            )
            activated.append({
                "rec_uid":          rec["uid"],
                "symbol":           rec["symbol"],
                "position_uid":     pos["uid"],
                "quantity":         float(qty),
                "anchor_price":     float(anchor),
                "entry_midpoint":   float(midpoint),
                "delta_fraction":   float(delta_frac),
                "provenance":       provenance,
            })
        return ActivationResult(activated=activated, considered=len(proposed))
    finally:
        conn.close()
