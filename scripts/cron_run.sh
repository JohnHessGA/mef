#!/usr/bin/env bash
# MEF cron entry point. Pure plumbing.
# See ~/repos/aft-platform/docs/conventions/cron-conventions.md.
set -euo pipefail
mkdir -p /mnt/aftdata/logs/mef
cd /home/johnh/repos/mef
source .venv/bin/activate
exec mef "$@"
