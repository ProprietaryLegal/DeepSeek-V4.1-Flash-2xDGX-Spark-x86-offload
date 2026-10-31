#!/usr/bin/env bash
# Stop only this deployment's containers (name dsv41-serve) on both nodes.
set -euo pipefail; cd "$(dirname "$0")"; set -a; . ./dsv41.env; set +a
HEAD=$HEAD WORKER=$WORKER bash "$RECIPE/scripts/launch/dsv41_tp2.sh" down
# PROMO-MATTER: remove the stopped engines' CPU-tier /dev/shm regions on both Sparks (only where no container runs;
# never fails the stop): offload/prefixstore/production/shm_stop.sh, PRODUCTION.md
bash offload/prefixstore/production/shm_stop.sh || true
