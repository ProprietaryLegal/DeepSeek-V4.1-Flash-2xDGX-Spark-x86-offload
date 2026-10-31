#!/usr/bin/env bash
# PP4-INSTALL (2026-10-28): after a start, prove PP4 sampled drafting is in force on BOTH ranks (K1's verify.sh runs it
# when dsv41.env sets PROD_PP4). Run from the repo root on the head node:
#   offload/pp4_prod/verify_running.sh HEAD WORKER
# Checks inside the running dsv41-serve on each node: sha256 of every PP4 file == MANIFEST.json (the remote_dspark mount
# holds exactly the manifest's package files, no more), the PP4 switches in the container environment, the removed keys
# absent (NOUT-TRIM), no experiment-only PP4 setting, and the launch argv (/serve.sh) carries the fixed-5 verify window.
# Prints one line per check; the last line is "PP4 VERIFIED on ..." or a failure.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$#" -ge 1 ] || { echo 'usage: verify_running.sh NODE...' >&2; exit 2; }
M=offload/pp4_prod/MANIFEST.json
id=$(sha256sum "$M" | cut -c1-12)
rc=0
want=$(python3 -c '
import json, sys
for r in json.load(open(sys.argv[1]))["files"]:
    print(r["sha256"], r["container_path"])' "$M")
mount=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["remote_dspark_mount"])' "$M")
nremote=$(grep -c " $mount/" <<<"$want")
for n in "$@"; do
  got=$(ssh -o BatchMode=yes "$n" "docker exec dsv41-serve sha256sum $(cut -d' ' -f2 <<<"$want" | tr '\n' ' ')" | awk '{print $1, $2}') \
    || { echo "$n: docker exec dsv41-serve sha256sum failed" >&2; rc=1; continue; }
  have=$(ssh -o BatchMode=yes "$n" "docker exec dsv41-serve find $mount -maxdepth 1 -name '*.py' -type f" | wc -l) \
    || { echo "$n: docker exec dsv41-serve find failed" >&2; rc=1; continue; }
  if [ "$got" != "$want" ]; then
    diff <(echo "$want") <(echo "$got") >&2 || true
    echo "$n: PP4 running files differ from MANIFEST" >&2; rc=1
  elif [ "$have" != "$nremote" ]; then
    echo "$n: PP4 remote_dspark mount holds $have package files, MANIFEST names $nremote" >&2; rc=1
  else
    echo "$n: PP4 $(wc -l <<<"$want") mounted files == MANIFEST ($id)"
  fi
  envs=$(ssh -o BatchMode=yes "$n" "docker inspect dsv41-serve --format '{{range .Config.Env}}{{println .}}{{end}}'")
  argv=$(ssh -o BatchMode=yes "$n" "docker exec dsv41-serve cat /serve.sh")
  python3 - "$M" "$n" <(echo "$envs") <(echo "$argv") <<'EOF' || rc=1
import json, shlex, sys
m = json.load(open(sys.argv[1])); node = sys.argv[2]
env = {}
for line in open(sys.argv[3]).read().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        env[k] = v  # docker keeps the last -e of a key
argv = shlex.split(open(sys.argv[4]).read().replace("\\\n", " "))
bad = []
for k, v in m["switches"].items():
    if env.get(k) != v:
        bad.append(f"env {k}={env.get(k)!r}, expected {v!r}")
for k in m["remove_env"] + m["forbidden_env"]:
    if k in env:
        bad.append(f"env {k}={env[k]!r} must be absent")
got = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--speculative-config"]
if len(got) != 1 or json.loads(got[0]) != json.loads(m["spec"]):
    bad.append(f"argv --speculative-config {got!r}, expected {m['spec']!r}")
if bad:
    print(f"{node}: PP4 switches REFUSED: " + "; ".join(bad), file=sys.stderr)
    sys.exit(1)
print(f"{node}: PP4 switches in force: " + " ".join(f"{k}={v}" for k, v in m["switches"].items())
      + f" | absent {' '.join(m['remove_env'])} | argv --speculative-config {m['spec']}")
EOF
done
[ $rc = 0 ] && echo "PP4 VERIFIED on $*" || { echo "PP4 verification FAILED" >&2; exit 1; }
