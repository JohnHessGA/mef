"""`mef import-positions <csv>` — ingest a Fidelity Positions CSV.

Parses the CSV, upserts an ``import_batch`` + one ``position_snapshot`` per
position, and flips any proposed recommendations to active when a matching
holding appears. Idempotent by sha256 file hash.
"""

from __future__ import annotations

from pathlib import Path

from mef.lifecycle import sweep as lifecycle_sweep
from mef.positions.activator import activate_from_latest_import
from mef.positions.importer import import_fidelity_csv


def run(args) -> int:
    path = Path(args.csv_path)
    if not path.exists():
        print(f"file not found: {path}")
        return 2

    print(f"Importing {path} ...")
    result = import_fidelity_csv(path)

    if not result.is_new:
        print(f"  already imported: {result.import_uid} "
              f"(hash {result.file_hash[:12]}…, {result.row_count} positions, "
              f"as-of {result.as_of_date or '?'})")
        print("  skipping auto-activation — nothing new to match against.")
    else:
        print(f"  batch {result.import_uid}  "
              f"{result.row_count} positions  "
              f"as-of {result.as_of_date or '?'}")
        for warn in result.warnings:
            print(f"  warn: {warn}")

        print()
        print("Auto-activation pass:")
        activation = activate_from_latest_import()
        print(f"  proposed recommendations considered: {activation.considered}")
        print(f"  activated:                           {len(activation.activated)}")
        for hit in activation.activated:
            print(
                f"    {hit['symbol']:<6} rec {hit['rec_uid']}  "
                f"qty={hit['quantity']:.0f}  "
                f"anchor=${hit['anchor_price']:.2f}  "
                f"midpoint=${hit['entry_midpoint']:.2f}  "
                f"Δ={hit['delta_fraction']:.2%}"
            )

    # Lifecycle sweep always runs — time-based expiration may have work even
    # when the CSV was a dedupe.
    print()
    print("Lifecycle sweep:")
    life = lifecycle_sweep()
    print(f"  proposed → expired: {len(life.expired)}")
    for e in life.expired:
        print(f"    {e['symbol']:<6} {e['rec_uid']}  window ended {e['entry_window_end']}")
    print(f"  active   → closed:  {len(life.closed)}")
    for c in life.closed:
        last = f"${c['last_price']:.2f}" if c.get('last_price') is not None else "n/a"
        print(f"    {c['symbol']:<6} {c['rec_uid']}  → {c['new_state']:<14} last={last} on {c['last_seen']}")

    return 0
