"""Import a parsed Fidelity Positions CSV into MEFDB.

- Hashes the file (sha256); if the same hash is already in ``mef.import_batch``
  with status 'ok', the import is a no-op and returns the existing import_uid.
- Otherwise: insert ``import_batch`` and one ``position_snapshot`` per position.

Per our design the importer writes only to MEFDB's own tables — no cross-DB
joins, no read from PHDB. Keeping MEF and IRA Guard independent lets either
tool be rebuilt or replaced without touching the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mef.db.connection import connect_mefdb
from mef.positions.parser import (
    ParsedFile,
    hash_file_sha256,
    parse_fidelity_csv,
    position_payload,
)
from mef.uid import next_uid


@dataclass
class ImportResult:
    import_uid: str
    is_new: bool                # False if we deduped against an existing hash
    source_path: str
    file_hash: str
    row_count: int
    as_of_date: str | None
    warnings: list[str]


def _existing_import_uid(conn, file_hash: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uid FROM mef.import_batch "
            " WHERE file_hash = %s AND status = 'ok' "
            " ORDER BY created_at DESC LIMIT 1",
            (file_hash,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def import_fidelity_csv(path: str | Path) -> ImportResult:
    """Parse + import a Fidelity Positions CSV. Idempotent by sha256."""
    path_str = str(Path(path).resolve())
    file_hash = hash_file_sha256(path)

    conn = connect_mefdb()
    try:
        existing = _existing_import_uid(conn, file_hash)
        if existing:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT row_count, as_of_date FROM mef.import_batch WHERE uid = %s",
                    (existing,),
                )
                row = cur.fetchone()
            return ImportResult(
                import_uid=existing,
                is_new=False,
                source_path=path_str,
                file_hash=file_hash,
                row_count=row[0] if row else 0,
                as_of_date=row[1].isoformat() if row and row[1] else None,
                warnings=["file already imported — returning existing batch"],
            )

        parsed: ParsedFile = parse_fidelity_csv(path)
        if not parsed.header_valid:
            return _record_failed_import(
                conn, path_str, file_hash,
                error_text=f"header mismatch: {parsed.warnings}",
            )

        import_uid = next_uid(conn, "import_batch")
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mef.import_batch (
                    uid, source_path, file_hash, as_of_date, row_count, status
                )
                VALUES (%s, %s, %s, %s, %s, 'ok')
                """,
                (import_uid, path_str, file_hash, parsed.as_of_date, len(parsed.positions)),
            )

            for p in parsed.positions:
                pos_uid = next_uid(conn, "position_snapshot")
                payload = position_payload(p, parsed.as_of_date)
                cur.execute(
                    """
                    INSERT INTO mef.position_snapshot (
                        uid, import_uid, account, symbol,
                        quantity, cost_basis_total, cost_basis_per_share,
                        last_price, market_value, as_of_date
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pos_uid, import_uid, payload["account"], payload["symbol"],
                        payload["quantity"], payload["cost_basis_total"],
                        payload["cost_basis_per_share"],
                        payload["last_price"], payload["market_value"],
                        payload["as_of_date"],
                    ),
                )
        conn.commit()

        return ImportResult(
            import_uid=import_uid,
            is_new=True,
            source_path=path_str,
            file_hash=file_hash,
            row_count=len(parsed.positions),
            as_of_date=parsed.as_of_date.isoformat() if parsed.as_of_date else None,
            warnings=parsed.warnings,
        )
    finally:
        conn.close()


def _record_failed_import(
    conn, source_path: str, file_hash: str, *, error_text: str
) -> ImportResult:
    uid = next_uid(conn, "import_batch")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO mef.import_batch (
                uid, source_path, file_hash, row_count, status, error_text
            )
            VALUES (%s, %s, %s, 0, 'failed', %s)
            """,
            (uid, source_path, file_hash, error_text),
        )
    conn.commit()
    return ImportResult(
        import_uid=uid,
        is_new=True,
        source_path=source_path,
        file_hash=file_hash,
        row_count=0,
        as_of_date=None,
        warnings=[error_text],
    )
