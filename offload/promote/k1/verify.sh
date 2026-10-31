#!/usr/bin/env bash
# Coordinator-only, after the launcher answers, before start.sh warm-up/success.
set -euo pipefail
cd "$(dirname "$0")/../../.."
set -a; . ./dsv41.env; set +a
. offload/promote/k1/constants.sh
k1_select_profile "${PROD_K1_PROFILE:?missing applied K1 profile}"
for key in ${!KVPACK_TEST_@}; do
  echo "K1 production verification refuses test hook $key" >&2; exit 1
done
python3 offload/promote/k1/manage.py verify --profile "${PROD_K1_PROFILE:?missing applied K1 profile}"
# PP4-INSTALL (2026-10-28): PP4's verifier replaces exactly K1's model_runner.py. K1's running check takes that one sha
# from the PP4 MANIFEST, which must be the one dsv41.env selects (inert without PROD_PP4).
pp4_runner=
if [ -n "${PROD_PP4:-}" ]; then
  [ "$(sha256sum offload/pp4_prod/MANIFEST.json | cut -c1-12)" = "$PROD_PP4" ] \
    || { echo "K1 verification: PROD_PP4=$PROD_PP4 is not this checkout's PP4 manifest" >&2; exit 1; }
  pp4_runner=$(python3 -c 'import json, sys; print(*[r["sha256"] for r in json.load(open(sys.argv[1]))["files"]
    if r["container_path"].endswith("/vllm/v1/worker/gpu/model_runner.py")])' offload/pp4_prod/MANIFEST.json)
fi
KVPACK_PP4_RUNNER_SHA256=$pp4_runner offload/kvpack/stage_overlay.sh verify-running --expect "$K1_EXPECT" "$HEAD" "$WORKER"
# Fresh files only, obtained from this container (docker rm/run resets its logs).
evidence=$(mktemp -d logs/k1-runtime.XXXXXXXX)
ssh -o BatchMode=yes -o ConnectTimeout=10 "$HEAD" 'docker logs dsv41-serve 2>&1' > "$evidence/engine.log"
# The launched argv names the prefill chunk; the engine's reported KV figure depends on it (check_runtime.py).
ssh -o BatchMode=yes -o ConnectTimeout=10 "$HEAD" 'docker exec dsv41-serve cat /serve.sh' > "$evidence/serve.sh"
curl --fail --silent --show-error --max-time 15 "http://localhost:$PORT/v1/models" > "$evidence/models.json"
python3 offload/promote/k1/check_runtime.py --profile "$PROD_K1_PROFILE" --log "$evidence/engine.log" --models "$evidence/models.json" --served "$SERVED" --serve "$evidence/serve.sh"
echo "K1 runtime evidence: $evidence"
# UPSTREAM-INSTALL (2026-10-28): every upstream item's files, switches and argv in force on both ranks
if [ -n "${PROD_UPSTREAM_ALL:-}" ]; then
  offload/upstream_all/verify_running.sh "$HEAD" "$WORKER"
fi
# PP4-INSTALL (2026-10-28): the PP4 files, switches and fixed-5 argv in force on both ranks
if [ -n "${PROD_PP4:-}" ]; then
  offload/pp4_prod/verify_running.sh "$HEAD" "$WORKER"
fi
