# MEF — Muse Engine Forecaster

Daily forecasting and recommendation tool over a curated universe of
**305 US stocks + 15 core US ETFs**. Advisory only — never trades.

- **Build spec:** [`docs/README_mef.md`](docs/README_mef.md)
- **Design spec:** [`docs/mef_design_spec.md`](docs/mef_design_spec.md)
- **Source notes:** [`notes/`](notes/)

## Quickstart

```bash
cd ~/repos/mef
python3 -m venv venv
source venv/bin/activate
pip install -e .
mef --help
mef status
```

Initial database bootstrap (once, as postgres superuser):

```bash
sudo -u postgres psql -f sql/mef_bootstrap.sql
mef init-db
```

Then see [`docs/README_mef.md`](docs/README_mef.md) for the full build order.
