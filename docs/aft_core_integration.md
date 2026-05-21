# MEF ← aft_core integration (M2)

**Date:** 2026-05-21
**Status:** M2 — first additive consumer of `aft_core`.

MEF is the first AFT application stream to consume `aft_core` (lives
at `~/repos/aft-platform/`). The integration is intentionally tiny:
display/metadata only, no scoring or routing change.

## What MEF imports

```python
from aft_core.tracks import primary_track_for_tool, track_label
```

Wrapped in `src/mef/aft_track.py`, which exposes two constants:

| Name              | Value                                  |
|-------------------|----------------------------------------|
| `MEF_TRACK`       | `Track.CAPITAL_APPRECIATION` (int = 4) |
| `MEF_TRACK_LABEL` | `"Track 4 — Capital Appreciation"`     |

`src/mef/aft_track.py` is the single source of truth inside MEF for
the Track 4 string. `commands/status.py` and `email_render.py` both
import from it.

## Where it shows up

### `mef status` (and bare `mef`) header

```
MEF — Muse Engine Forecaster
Investing Track: Track 4 — Capital Appreciation
Report: 2026-05-21 15:24 EDT · market data through 2026-05-19 · universe 305 stocks / 20 ETFs
```

The "Investing Track" line is new in M2.

### Daily email — subject

```
Subject: MEF daily report — Track 4 — Capital Appreciation — 2026-05-21
```

The leading `"MEF daily report"` is preserved verbatim, so existing
external filters / search rules that match on the old prefix continue
to work.

### Daily email — body header

```
MEF daily report — Track 4 — Capital Appreciation
=================================================
```

The underline auto-adjusts to the new prefix length.

## What did NOT change

- No scoring, ranker, gating, lifecycle, LLM, or routing logic.
- No `mef.recommendation` schema column — Track 4 is the universal MEF
  identity, not per-row metadata. A future per-rec track column may
  matter when MEF emits across multiple tracks; M2 does not.
- No cron change. MEF cron continues to fire from `~/repos/mef/.venv`.

## Runtime requirement

`aft_core` must be installed (editable) in whatever venv MEF runs in.
That includes:

- **Cron / per-tool venv:** `~/repos/mef/.venv` — install with
  `~/repos/mef/.venv/bin/pip install -e ~/repos/aft-platform`. This
  was done as part of M2 land.
- **Shared dev venv:** `~/repos/aft-platform/.venv` — already has
  `aft_core` installed editable (it lives there).

Cron has **not** been switched to the shared venv. Cron still uses
`~/repos/mef/.venv`. That migration is a separate, later milestone.

If MEF's per-tool venv ever gets recreated, `aft_core` must be
reinstalled into it before `mef` will import — `aft_core` is intentionally
**not** declared in `pyproject.toml` because it is editable-install
only (no PyPI / no private index).

## Backwards compatibility

- `test_email_render.py` assertions of the form
  `email.subject.startswith("MEF daily report")` continue to pass.
- The `[STALE DATA]` prefix continues to work — it is prepended ahead
  of the new Track 4 segment.
- The `when_kind` parameter still has no effect on subject/body
  wording (single-run model unchanged).
