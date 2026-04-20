"""`mef tag <rec-uid> --provenance <value>` — user override for activation provenance.

Use cases:
- The activator inferred ``mef_attributed`` but you actually bought the
  symbol for an unrelated reason — re-tag as ``independent``.
- The activator inferred ``independent`` (purchase landed outside the
  entry window) but you DID act on the MEF rec, just slowly — re-tag as
  ``mef_attributed``.
- The activator stamped nothing yet (rec hasn't activated) and you want
  to record a provenance for tracking purposes.

Always stamps ``provenance_set_by = 'cli'`` so audits can distinguish
inferred vs human-confirmed values.
"""

from __future__ import annotations

import sys

from mef.db.connection import connect_mefdb


_ALLOWED = ("mef_attributed", "pre_existing", "independent")


def run(args) -> int:
    rec_uid = args.rec_uid
    provenance = args.provenance
    if provenance not in _ALLOWED:
        print(
            f"mef tag: --provenance must be one of {_ALLOWED}, got {provenance!r}",
            file=sys.stderr,
        )
        return 2

    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE mef.recommendation
                   SET provenance        = %s,
                       provenance_set_by = 'cli',
                       updated_at        = now()
                 WHERE uid = %s
                 RETURNING symbol, state, provenance
                """,
                (provenance, rec_uid),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if row is None:
        print(f"mef tag: no recommendation found with uid={rec_uid}", file=sys.stderr)
        return 2

    symbol, state, prov = row
    print(f"Tagged {rec_uid} ({symbol}, state={state}): provenance = {prov} (set by cli)")
    return 0
