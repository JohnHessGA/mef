"""`mef init-db` — apply MEFDB migrations (idempotent)."""

from __future__ import annotations

from mef.db.schema_init import apply_migrations, list_migrations


def run(args) -> int:
    print("MEF init-db")
    print("===========")

    migrations = list_migrations()
    if not migrations:
        print("No migrations found under sql/mefdb/.")
        return 1

    print(f"Found {len(migrations)} migration file(s):")
    for p in migrations:
        print(f"  - {p.name}")
    print()

    applied = apply_migrations()
    for path, elapsed in applied:
        print(f"  [ok]  {path.name:<48} {elapsed:6.2f}s")

    print()
    print(f"Applied {len(applied)} migration(s).")
    return 0
