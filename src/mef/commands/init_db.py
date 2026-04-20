"""`mef init-db` — apply MEFDB and Overwatch migrations (idempotent)."""

from __future__ import annotations

from mef.db.schema_init import apply_all_migrations, _list_migrations, _MEFDB_DIR, _OVERWATCH_DIR


def run(args) -> int:
    print("MEF init-db")
    print("===========")

    mefdb_files = _list_migrations(_MEFDB_DIR)
    ow_files = _list_migrations(_OVERWATCH_DIR)

    if not mefdb_files and not ow_files:
        print("No migration files found under sql/mefdb/ or sql/overwatch/.")
        return 1

    print(f"sql/mefdb/      ({len(mefdb_files)} file(s))")
    for p in mefdb_files:
        print(f"  - {p.name}")
    print(f"sql/overwatch/  ({len(ow_files)} file(s))")
    for p in ow_files:
        print(f"  - {p.name}")
    print()

    applied = apply_all_migrations()

    if applied["mefdb"]:
        print("Applied to mefdb:")
        for path, elapsed in applied["mefdb"]:
            print(f"  [ok]  {path.name:<48} {elapsed:6.2f}s")
    if applied["overwatch"]:
        print("Applied to overwatch:")
        for path, elapsed in applied["overwatch"]:
            print(f"  [ok]  {path.name:<48} {elapsed:6.2f}s")

    print()
    total = len(applied["mefdb"]) + len(applied["overwatch"])
    print(f"Applied {total} migration(s).")
    return 0
