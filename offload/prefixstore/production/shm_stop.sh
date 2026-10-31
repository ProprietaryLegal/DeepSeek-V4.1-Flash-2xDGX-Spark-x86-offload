#!/usr/bin/env bash
# PROMO-MATTER: the production STOP path for the CPU tier's /dev/shm regions (MC1-PROMOTION.plan.md 2.3; PRODUCTION.md).
# stop.sh runs this after `down`, with dsv41.env sourced (HEAD, WORKER, IMAGE). On each Spark where `docker ps -q` is
# empty (no process can map a region any more) it removes /dev/shm/vllm_offload_*.mmap in a throwaway container of the
# serving image (shm_clean.py; one "MATTER SHM:" line per Spark), so a stopped production never holds 256 MiB of
# MemAvailable per Spark through a window or an idle period. The start-time sweep in serve.sh's matter block stays.
# Never fails the stop: every outcome is one line and exit 0.
set -uo pipefail
cd "$(dirname "$0")/../../.."
MATTER_ROOT=$PWD
if [ -z "${HEAD:-}" ] || [ -z "${WORKER:-}" ] || [ -z "${IMAGE:-}" ]; then
  echo "MATTER SHM: HEAD/WORKER/IMAGE not set (dsv41.env); stale /dev/shm regions left in place"
  exit 0
fi
. offload/prefixstore/production/matter_serve.sh
matter_shm_clean
exit 0
