#!/usr/bin/env bash
# PP4-INSTALL (2026-10-28): stage the PP4 overlay on both Sparks (start.sh runs it when dsv41.env sets PROD_PP4). Run
# from the repo root on the head node:
#   offload/pp4_prod/stage.sh HEAD WORKER
# Copies this checkout's offload/pp4_prod/overlay/ (every byte pinned by MANIFEST.json: the composed 0075 + PP4
# remote_dspark package and PP4's verifier files) to NODE:~/dsv41-pp4/<id>/ (id = MANIFEST sha256[:12]; never
# overwritten, read-only once staged), then verifies every copy on every node. dsv41.env's OFFLOAD_DOCKER_ARGS bind-mounts
# those paths read-only. Remove: ssh NODE 'chmod -R u+w ~/dsv41-pp4/<id> && rm -rf ~/dsv41-pp4/<id>' (only while no
# dsv41.env mounts it).
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$#" = 2 ] && [ "$1" != "$2" ] || { echo 'PP4 staging requires two distinct nodes' >&2; exit 1; }
here=offload/pp4_prod
id=$(sha256sum "$here/MANIFEST.json" | cut -c1-12)
[ "${PROD_PP4:-$id}" = "$id" ] || { echo "dsv41.env PROD_PP4=$PROD_PP4 but this checkout's manifest is $id" >&2; exit 1; }
sums=$(python3 - "$here/MANIFEST.json" <<'EOF'
import json, sys
for r in json.load(open(sys.argv[1]))["files"]:
    print(f"{r['sha256']}  {r['path']}")
EOF
)
# this checkout's overlay == MANIFEST, and nothing else in it
(cd "$here/overlay" && sha256sum -c --quiet - <<<"$sums") \
  || { echo "this checkout's offload/pp4_prod/overlay differs from MANIFEST.json" >&2; exit 1; }
[ "$(cd "$here/overlay" && find . -type f | wc -l)" = "$(wc -l <<<"$sums")" ] \
  || { echo "offload/pp4_prod/overlay holds files MANIFEST.json does not name" >&2; exit 1; }
paths=$(cut -c67- <<<"$sums")
for n in "$@"; do
  dst="\$HOME/dsv41-pp4/$id"
  if ssh -o BatchMode=yes "$n" "test -d $dst"; then
    echo "$n: ~/dsv41-pp4/$id exists (staged before); verifying"
  else
    ssh -o BatchMode=yes "$n" "rm -rf $dst.tmp && mkdir -p $dst.tmp"
    (cd "$here/overlay" && tar cf - $paths) | ssh -o BatchMode=yes "$n" "tar xf - -C $dst.tmp"
    ssh -o BatchMode=yes "$n" "cd $dst.tmp && sha256sum -c --quiet - && chmod -R a-w . && cd .. && mv $id.tmp $id" <<<"$sums" \
      || { echo "$n: staged copies differ from MANIFEST" >&2; exit 1; }
  fi
  ssh -o BatchMode=yes "$n" "cd $dst && sha256sum -c --quiet - && test \$(find . -type f | wc -l) = $(wc -l <<<"$sums")" <<<"$sums" \
    || { echo "$n: ~/dsv41-pp4/$id differs from MANIFEST" >&2; exit 1; }
  echo "$n: staged $(wc -l <<<"$sums") files at ~/dsv41-pp4/$id, sha256 verified"
done
