#!/usr/bin/env bash
# UPSTREAM-INSTALL (2026-10-28): stage the composed upstream overlay on both Sparks (start.sh runs it when dsv41.env sets
# PROD_UPSTREAM_ALL). Run from the repo root on the head node:
#   offload/upstream_all/stage.sh HEAD WORKER
# Copies this checkout's offload/upstream_all/overlay/ (every byte pinned by MANIFEST.json) and the pinned top-k library
# ($HOME/dsv41-upstream-all/pinned/dsv41_topk.so on the head node) to NODE:~/dsv41-upstream-all/<id>/ (id = MANIFEST
# sha256[:12]; never overwritten, read-only once staged), then verifies every copy on every node. dsv41.env's
# OFFLOAD_DOCKER_ARGS bind-mounts those paths read-only. Remove: ssh NODE 'chmod -R u+w ~/dsv41-upstream-all/<id> &&
# rm -rf ~/dsv41-upstream-all/<id>' (only while no dsv41.env mounts it).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$#" = 2 ] && [ "$1" != "$2" ] || { echo 'upstream-all staging requires two distinct nodes' >&2; exit 1; }
here=offload/upstream_all
id=$(sha256sum "$here/MANIFEST.json" | cut -c1-12)
[ "${PROD_UPSTREAM_ALL:-$id}" = "$id" ] || { echo "dsv41.env PROD_UPSTREAM_ALL=$PROD_UPSTREAM_ALL but this checkout's manifest is $id" >&2; exit 1; }
LIB_SRC=$HOME/dsv41-upstream-all/pinned/dsv41_topk.so
sums=$(python3 - "$here/MANIFEST.json" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
for r in m["files"]:
    print(f"{r['sha256']}  {r['path']}")
print(f"{m['library']['sha256']}  lib/dsv41_topk.so")
EOF
)
# this checkout's overlay == MANIFEST
(cd "$here/overlay" && grep -v '  lib/' <<<"$sums" | sha256sum -c --quiet -) \
  || { echo "this checkout's offload/upstream_all/overlay differs from MANIFEST.json" >&2; exit 1; }
lib_sha=$(grep '  lib/dsv41_topk.so$' <<<"$sums" | cut -c1-64)
[ "$(sha256sum < "$LIB_SRC" | cut -c1-64)" = "$lib_sha" ] || { echo "$LIB_SRC is not the pinned top-k library ($lib_sha)" >&2; exit 1; }
paths=$(cut -c67- <<<"$sums" | grep -v '^lib/')
for n in "$@"; do
  dst="\$HOME/dsv41-upstream-all/$id"
  if ssh -o BatchMode=yes "$n" "test -d $dst"; then
    echo "$n: ~/dsv41-upstream-all/$id exists (staged before); verifying"
  else
    ssh -o BatchMode=yes "$n" "rm -rf $dst.tmp && mkdir -p $dst.tmp/lib"
    (cd "$here/overlay" && tar cf - $paths) | ssh -o BatchMode=yes "$n" "tar xf - -C $dst.tmp"
    ssh -o BatchMode=yes "$n" "cat > $dst.tmp/lib/dsv41_topk.so" < "$LIB_SRC"
    ssh -o BatchMode=yes "$n" "cd $dst.tmp && sha256sum -c --quiet - && chmod -R a-w . && cd .. && mv $id.tmp $id" <<<"$sums" \
      || { echo "$n: staged copies differ from MANIFEST" >&2; exit 1; }
  fi
  ssh -o BatchMode=yes "$n" "cd $dst && sha256sum -c --quiet -" <<<"$sums" || { echo "$n: ~/dsv41-upstream-all/$id differs from MANIFEST" >&2; exit 1; }
  echo "$n: staged $(wc -l <<<"$sums") files at ~/dsv41-upstream-all/$id, sha256 verified"
done
