"""MEF's Investing Track identity, sourced from ``aft_core``.

MEF serves **Investing Track 4 — Capital Appreciation**. That mapping
is owned by ``aft_core.tracks`` (see ``~/repos/aft-platform``); MEF
reads it through this module so the label is consistent across the
status report, the email subject, and the email body header.

If ``aft_core`` is not installed in the active venv, the import will
fail with a clear message — the cron-runtime venv must include
``aft_core`` editable until cron migrates to the shared
``~/repos/aft-platform/.venv``.
"""

from __future__ import annotations

from aft_core.tracks import primary_track_for_tool, track_label

_TRACK = primary_track_for_tool("mef")
if _TRACK is None:  # pragma: no cover — invariant of aft_core registry
    raise RuntimeError(
        "aft_core does not register MEF with a primary Investing Track. "
        "Reinstall aft_core (pip install -e ~/repos/aft-platform) into MEF's venv."
    )

#: Canonical MEF Investing Track value (``Track.CAPITAL_APPRECIATION``).
MEF_TRACK = _TRACK

#: Display string, e.g. ``"Track 4 — Capital Appreciation"``.
MEF_TRACK_LABEL: str = track_label(_TRACK)
