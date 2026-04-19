"""Fidelity Positions CSV ingest.

- ``parser.py`` — pure parser, no DB.
- ``importer.py`` — sha256-keyed dedupe, writes import_batch + position_snapshot.
- ``activator.py`` — flips matching proposed recs to active based on the
  latest position_snapshot.
"""
