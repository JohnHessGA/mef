"""`mef dismiss <rec-uid>` — mark a proposed recommendation as not-implemented.

Only proposed recs can be dismissed; already-active or already-closed recs
are left alone with a clear message.
"""

from __future__ import annotations

from mef.db.connection import connect_mefdb
from mef.uid import next_uid


def run(args) -> int:
    rec_uid = args.rec_uid
    note = args.note or ""

    conn = connect_mefdb()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state, symbol, run_uid FROM mef.recommendation WHERE uid = %s",
                (rec_uid,),
            )
            row = cur.fetchone()
            if row is None:
                print(f"rec {rec_uid} not found.")
                return 1
            current_state, symbol, run_uid = row

            if current_state != "proposed":
                print(
                    f"rec {rec_uid} ({symbol}) is in state '{current_state}' — "
                    "only 'proposed' recs can be dismissed. Nothing changed."
                )
                return 0

            cur.execute(
                """
                UPDATE mef.recommendation
                   SET state            = 'dismissed',
                       state_changed_at = now(),
                       state_changed_by = 'cli',
                       updated_at       = now()
                 WHERE uid = %s
                   AND state = 'proposed'
                """,
                (rec_uid,),
            )

            update_uid = next_uid(conn, "recommendation_update")
            cur.execute(
                """
                INSERT INTO mef.recommendation_update (
                    uid, rec_uid, run_uid, prior_state, new_state, guidance, notes
                )
                VALUES (%s, %s, %s, 'proposed', 'dismissed', 'dismiss', %s)
                """,
                (update_uid, rec_uid, run_uid, note or None),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"rec {rec_uid} ({symbol}) → dismissed.")
    if note:
        print(f"  note: {note}")
    return 0
