#!/usr/bin/env bash
# UPSTREAM-INSTALL (2026-10-28): after a start, prove every upstream item is in force on BOTH ranks (K1's verify.sh runs
# it when dsv41.env sets PROD_UPSTREAM_ALL). Run from the repo root on the head node:
#   offload/upstream_all/verify_running.sh HEAD WORKER
# Checks inside the running dsv41-serve on each node: sha256 of every mounted overlay file and of the top-k library ==
# MANIFEST.json; every switch and serve.sh env value in the container environment; the launch argv (/serve.sh) carries
# the K5 schedule, chunk 8192 and threshold 1024. Prints one line per item.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$#" -ge 1 ] || { echo 'usage: verify_running.sh NODE...' >&2; exit 2; }
M=offload/upstream_all/MANIFEST.json
# PP4-INSTALL (2026-10-28): while dsv41.env selects PP4 (PROD_PP4, exported by K1's verify.sh), the files under the
# remote_dspark mount, the verify-window argv and the switches PP4's MANIFEST supersedes carry PP4's values; they are
# checked by offload/pp4_prod/verify_running.sh. Every other item is checked here exactly as before.
P=
if [ -n "${PROD_PP4:-}" ]; then
  P=offload/pp4_prod/MANIFEST.json
  [ "$(sha256sum "$P" | cut -c1-12)" = "$PROD_PP4" ] || { echo "PROD_PP4=$PROD_PP4 is not this checkout's PP4 manifest" >&2; exit 1; }
fi
rc=0
for n in "$@"; do
  want=$(python3 -c '
import json, sys
m = json.load(open(sys.argv[1]))
skip = json.load(open(sys.argv[2]))["supersedes"]["mount"] + "/" if sys.argv[2] else None
for r in m["files"]:
    if skip is None or not r["container_path"].startswith(skip):
        print(r["sha256"], r["container_path"])
print(m["library"]["sha256"], m["library"]["container_path"])' "$M" "$P")
  got=$(ssh -o BatchMode=yes "$n" "docker exec dsv41-serve sha256sum $(cut -d' ' -f2 <<<"$want" | tr '\n' ' ')" | awk '{print $1, $2}') \
    || { echo "$n: docker exec dsv41-serve sha256sum failed" >&2; rc=1; continue; }
  if [ "$got" != "$want" ]; then
    diff <(echo "$want") <(echo "$got") >&2 || true
    echo "$n: UPSTREAM-ALL running files differ from MANIFEST" >&2; rc=1
  else
    echo "$n: UPSTREAM-ALL $(wc -l <<<"$want") mounted files == MANIFEST ($(sha256sum "$M" | cut -c1-12))${P:+; remote_dspark superseded by PP4 $PROD_PP4}"
  fi
  envs=$(ssh -o BatchMode=yes "$n" "docker inspect dsv41-serve --format '{{range .Config.Env}}{{println .}}{{end}}'")
  argv=$(ssh -o BatchMode=yes "$n" "docker exec dsv41-serve cat /serve.sh")
  python3 - "$M" "$n" <(echo "$envs") <(echo "$argv") "$P" <<'EOF' || rc=1
import json, shlex, sys
m = json.load(open(sys.argv[1])); node = sys.argv[2]
sup = json.load(open(sys.argv[5]))["supersedes"] if sys.argv[5] else {"switches": [], "argv": []}
m["switches"] = {k: v for k, v in m["switches"].items() if k not in sup["switches"]}
m["serve_argv"] = {k: v for k, v in m["serve_argv"].items() if k not in sup["argv"]}
env = {}
for line in open(sys.argv[3]).read().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        env[k] = v  # docker keeps the last -e of a key
argv = shlex.split(open(sys.argv[4]).read().replace("\\\n", " "))
bad = []
for k, v in {**m["switches"], **m["serve_env"]}.items():
    if env.get(k) != v:
        bad.append(f"env {k}={env.get(k)!r}, expected {v!r}")
for flag, v in m["serve_argv"].items():
    got = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]
    if flag == "--speculative-config":
        ok = len(got) == 1 and json.loads(got[0]) == json.loads(v)
    else:
        ok = got == [v]
    if not ok:
        bad.append(f"argv {flag} {got!r}, expected {v!r}")
if bad:
    print(f"{node}: UPSTREAM-ALL switches REFUSED: " + "; ".join(bad), file=sys.stderr)
    sys.exit(1)
print(f"{node}: UPSTREAM-ALL switches in force: " + " ".join(f"{k}={v}" for k, v in {**m['switches'], **m['serve_env']}.items())
      + " | argv " + " ".join(f"{f} {v}" for f, v in m["serve_argv"].items()))
EOF
done
# item 11 (NOUT-TRIM): the switch alone is not enough; the remote speculator decides at start (async scheduling,
# capacity/resilience) and logs it once on rank 0 (the first node)
nout=$(python3 -c 'import json, os, sys
arm = dict(kv.split("=", 1) for kv in os.environ.get("UPSTREAM_ALL_ARM", "").split())
print(arm.get(sys.argv[2], json.load(open(sys.argv[1]))["switches"].get(sys.argv[2], "")))' "$M" VLLM_DSPARK_REMOTE_N_OUT)
if [ "$nout" = window ] && [ -z "$P" ]; then  # PP4 removes VLLM_DSPARK_REMOTE_N_OUT (MANIFEST supersedes)
  line=$(ssh -o BatchMode=yes "$1" "docker logs dsv41-serve 2>&1 | grep -a 'remote DSpark n_out:' | tail -1") || line=
  if grep -q 'next-step window cut on' <<<"$line"; then
    echo "$1: UPSTREAM-ALL item 11 NOUT-TRIM in force: ${line##*remote DSpark n_out: }"
  else
    echo "$1: UPSTREAM-ALL item 11 NOUT-TRIM NOT in force (rank-0 n_out line: ${line:-none})" >&2; rc=1
  fi
fi
[ $rc = 0 ] && echo "UPSTREAM-ALL VERIFIED on $*" || { echo "UPSTREAM-ALL verification FAILED" >&2; exit 1; }
