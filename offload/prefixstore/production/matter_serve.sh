# PROMO-MATTER: the production matter tier (MC1 Tier 1), sourced by serve.sh after SPEC and before EXTRA (never run alone).
# matter_block sets MATTER_STATE (ON|OFF), MATTER_REASON, and the three additions serve.sh splices in when ON:
#   MATTER_EXTRA        "--kv-transfer-config '<json>'"   (appended to EXTRA, as serve_exp.sh appends EXP_EXTRA_ARGS)
#   MATTER_DOCKER_ENV   " VLLM_DSV41_KV_CRC=1 ..."        (the nine MC1 switches, appended after OFFLOAD_DSPARK_ENV)
#   MATTER_DOCKER_ARGS  " -v $HOME/dsv41-prefixstore/<id>/<path>:<container path>:ro" x 13 (after OFFLOAD_DOCKER_ARGS)
# When OFF all three are empty and serve.sh serves exactly the pre-matter production (tests: test_production.py).
# Every start, ON or OFF, first removes the CPU-tier regions stopped engines left in /dev/shm (shm_clean.py; one
# "MATTER SHM:" line per Spark; never fails the start).
# OFF, with one loud "MATTER OFF (<reason>)" line and logs/matter-state, whenever a precondition fails: the MATTER-OFF
# switch file in the checkout root, K1 not active at the 327680 profile (K1's own start fallback restores the pre-K1
# files; the matter tier never rides on them), no offload launcher, the generated config missing, the model manifest or
# the staged exclusion list/pin missing, mis-moded or not matching, the staging of the 13 files failing, the reviewed
# config refusing the values, or a Spark without the tier bound + 50 GiB of free disk (L2B; one "MATTER DISK:" line per
# Spark). A start never fails because of the matter tier: production keeps serving without it.
# Privacy: the two pins are read from files on the head Spark into function locals; neither is printed. The launcher's
# output is redacted (64-hex runs) by serve.sh while the tier is ON.

matter_off() {
  MATTER_STATE=OFF MATTER_REASON=$1 MATTER_EXTRA= MATTER_DOCKER_ENV= MATTER_DOCKER_ARGS=
  echo "MATTER OFF ($1): serving without the matter tier (the pre-matter production form)"
  matter_state "OFF $1"
}

matter_state() {
  mkdir -p "$MATTER_ROOT/logs" && printf '%s %s\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MATTER_ROOT/logs/matter-state"
}

matter_mode() {  # matter_mode PATH: "<octal mode>:<own|foreign>" or "absent"
  if [ -e "$1" ] || [ -L "$1" ]; then
    [ -L "$1" ] && { echo symlink; return 0; }
    local m o; m=$(stat -c '%a' "$1") o=$(stat -c '%u' "$1")
    [ "$o" = "$(id -u)" ] && echo "$m:own" || echo "$m:foreign"
  else
    echo absent
  fi
}

matter_shm_clean() {  # every Spark: remove stopped engines' CPU-tier regions (shm_clean.py), only with no container up
  local n out
  for n in "$HEAD" "$WORKER"; do
    if ! out=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$n" "if [ -n \"\$(docker ps -q)\" ]; then echo BUSY; else \
        docker run --rm -i --pull never --network none --ipc host --entrypoint python3 $IMAGE - '/dev/shm/vllm_offload_*.mmap'; fi" \
        < "$MATTER_ROOT/offload/prefixstore/production/shm_clean.py" 2>&1); then
      echo "MATTER SHM: $n cleanup failed; stale /dev/shm regions may remain"
    elif [ "$out" = BUSY ]; then
      echo "MATTER SHM: $n has a running container; stale /dev/shm regions left in place"
    else
      echo "MATTER SHM: $n $out"
    fi
  done
}

MATTER_DISK_HEADROOM_GB=50   # L2B: free disk each Spark keeps beyond the tier bound (the tier never fills a disk)

matter_disk_ok() {  # matter_disk_ok TIER_GB: every Spark's ~/.cache/dsv41-serve filesystem has TIER_GB + 50 GiB free
  local n free need=$(( $1 + MATTER_DISK_HEADROOM_GB )) ok=0
  for n in "$HEAD" "$WORKER"; do
    free=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$n" \
        'd=$HOME/.cache/dsv41-serve; [ -d "$d" ] || d=$HOME; df -B1 --output=avail "$d" | tail -n 1' 2>/dev/null) || free=
    free=${free//[[:space:]]/}
    if [[ ! $free =~ ^[0-9]+$ ]]; then
      echo "MATTER DISK: $n free disk unmeasured; the tier needs $need GiB (bound $1 GiB + $MATTER_DISK_HEADROOM_GB GiB)"
      ok=1
    elif [ "$free" -lt $(( need << 30 )) ]; then
      echo "MATTER DISK: $n $(( free >> 30 )) GiB free < $need GiB (bound $1 GiB + $MATTER_DISK_HEADROOM_GB GiB)"
      ok=1
    else
      echo "MATTER DISK: $n $(( free >> 30 )) GiB free >= $need GiB (bound $1 GiB + $MATTER_DISK_HEADROOM_GB GiB)"
    fi
  done
  return $ok
}

matter_render() {  # matter_render MODEL_PIN EXCLUSION_PIN: source the generated config in a scope that drops on return
  local PREFIX_MODEL_SHA256=$1 PREFIX_MATTER_EXCLUDED_SHA256=$2 EXP_EXTRA_ARGS= EXP_DOCKER_ENV=
  local PREFIX_ENABLE PREFIX_CPU_BYTES PREFIX_LOAD_FRACTION PREFIX_IO_CPUS PREFIX_MN_VERIFY PREFIX_MATTER_ROOT
  local PREFIX_MATTER_EXCLUDED PREFIX_MATTER_AUDIT PREFIX_MATTER_MAX_GB PREFIX_MATTER_NS_MAX_GB PREFIX_MATTER_TTL_DAYS
  local PREFIX_STREAM PREFIX_STREAM_MB PREFIX_HASH_DUMP PREFIX_HASH_SEGMENT PREFIX_TRANSFER_JSON v
  . "$MATTER_ROOT/offload/prefixstore/production/matter-prod.env" >/dev/null || return 1
  [ "$PREFIX_ENABLE" = 1 ] && [ -n "$EXP_EXTRA_ARGS" ] && [ -n "$EXP_DOCKER_ENV" ] || return 1
  MATTER_EXTRA=$EXP_EXTRA_ARGS MATTER_DOCKER_ENV=$EXP_DOCKER_ENV MATTER_TIER_GB=$PREFIX_MATTER_MAX_GB
}

matter_block() {
  MATTER_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
  MATTER_STATE=OFF MATTER_REASON= MATTER_EXTRA= MATTER_DOCKER_ENV= MATTER_DOCKER_ARGS= MATTER_TIER_GB=
  local cfg="$MATTER_ROOT/offload/prefixstore/production/matter-prod.env"
  local dir="$HOME/.cache/dsv41-serve/dsv41-matter" list=matter-cache-excluded-ns.txt
  local manifest="${MODEL_DIR:-}/CANDIDATE_MANIFEST.json" model_pin excl_pin got pair src dst args v
  # The production stop path for the CPU-tier regions (MC1-PROMOTION.plan.md 2.3): at every start, ON or OFF.
  matter_shm_clean
  # Inherited PREFIX_* knobs never reach production: the generated defaults are the reviewed configuration.
  for v in $(compgen -v PREFIX_ || true); do unset "$v"; done
  if [ -e "$MATTER_ROOT/MATTER-OFF" ]; then matter_off switched-off; return 0; fi
  if [ "${PROD_K1:-0}" != 1 ] || [ "${PROD_K1_PROFILE:-}" != 327680 ]; then matter_off k1-inactive; return 0; fi
  if [ -z "${OFFLOAD_DOCKER_ARGS:-}" ]; then matter_off no-offload-launcher; return 0; fi
  if [ ! -f "$cfg" ]; then matter_off config-missing; return 0; fi
  if [ ! -f "$manifest" ]; then matter_off model-manifest-missing; return 0; fi
  model_pin=$(sha256sum < "$manifest" | cut -c1-64)
  if [ "$(matter_mode "$dir")" != 700:own ] || [ "$(matter_mode "$dir/$list")" != 600:own ] \
     || [ "$(matter_mode "$dir/$list.sha256")" != 600:own ]; then
    matter_off exclusion-list-unstaged; return 0
  fi
  excl_pin=$(cut -c1-64 < "$dir/$list.sha256")
  got=$(sha256sum < "$dir/$list" | cut -c1-64)
  if [[ ! $excl_pin =~ ^[0-9a-f]{64}$ ]] || [ "$got" != "$excl_pin" ]; then matter_off exclusion-pin-differs; return 0; fi
  # shellcheck source=/dev/null
  . <(grep -E '^MATTER_(OVERLAY_ID|LAYOUT_SHA256|MOUNTS)=' "$cfg")
  if [[ ! ${MATTER_OVERLAY_ID:-} =~ ^[0-9a-f]{12}$ ]] || [ -z "${MATTER_MOUNTS:-}" ]; then matter_off config-malformed; return 0; fi
  if ! bash "$MATTER_ROOT/offload/prefixstore/production/stage.sh" stage "$HEAD" "$WORKER"; then
    matter_off stage-failed; return 0
  fi
  if ! matter_render "$model_pin" "$excl_pin"; then matter_off config-refused; return 0; fi
  if ! matter_disk_ok "$MATTER_TIER_GB"; then matter_off disk-headroom; return 0; fi
  args=
  for pair in $MATTER_MOUNTS; do
    src=${pair%%=*} dst=${pair#*=}
    case "$src" in offload/prefixstore/overlay/?*) ;; *) matter_off config-malformed; return 0 ;; esac
    args="$args -v \$HOME/dsv41-prefixstore/$MATTER_OVERLAY_ID/${src#offload/prefixstore/overlay/}:$dst:ro"
  done
  MATTER_DOCKER_ARGS=$args MATTER_STATE=ON MATTER_REASON=
  echo "MATTER ON: matter tier (MC1 Tier 1) from ~/dsv41-prefixstore/$MATTER_OVERLAY_ID, layout ${MATTER_LAYOUT_SHA256:0:12}; persistence is opt-in per request"
  matter_state "ON $MATTER_OVERLAY_ID ${MATTER_LAYOUT_SHA256:0:12}"
}
