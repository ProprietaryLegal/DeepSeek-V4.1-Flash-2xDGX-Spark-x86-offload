#!/usr/bin/env python3
"""UPSTREAM-INSTALL delta audit: the effective serve configuration of two commits, compared item by item.

CPU only; reads git objects, never a host. For each commit it sources dsv41.env and serve.sh's variable block (up to the
JIT step, which is never run) in a scratch directory and reads back: the container env (serve.sh DOCKER_ENV, then
dsv41.env's OFFLOAD_DOCKER_ENV and OFFLOAD_DSPARK_ENV; a later key wins, as with docker -e), the launch knobs (SPEC,
MAX_BATCH, MAX_SEQS, MAX_LEN, KV_BYTES, EXTRA) and the bind mounts (target -> source). Every difference must be
claimed by a declared item, else the audit fails:

    python3 offload/upstream_all/audit.py [--base 596ba1c] [--head HEAD] [--markdown OUT.md]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DIST = "/usr/local/lib/python3.12/dist-packages/"
PROBE = r'''
set -euo pipefail
set -a; . ./dsv41.env; set +a
export HEAD=spark WORKER=sparkworker
eval "$(sed -n '/^set -euo pipefail$/,/^JIT=/p' serve.sh | sed '$d')"
python3 - <<'EOF'
import json, os
print(json.dumps({k: os.environ.get(k, "") for k in
    ("DOCKER_ENV", "SPEC", "MAX_BATCH", "MAX_SEQS", "MAX_LEN", "KV_BYTES", "EXTRA", "OFFLOAD_DOCKER_ARGS",
     "GPU_CLOCK_CAP", "MODEL_DIR", "IMAGE", "PROD_K1", "PROD_K1_PROFILE", "PROD_UPSTREAM_ALL")}))
EOF
'''

# Every allowed difference: key -> item
ENV_ITEMS = {
    "VLLM_DSV41_INDEXER_DEFER": "1 (0051)",
    "EXL3_RDMA_DEVICES": "2 (dual ring)",
    "VLLM_DSV41_TOPK_FIX": "5 (top-k fix)",
    "VLLM_DSV41_TOPK_FIX_SO": "5 (top-k fix)",
    "VLLM_DSV41_REPLAY_SKIP": "6 (0075)",
    "VLLM_EXL3_MOE_SPLIT_MAX_TOKENS": "7 (0064)",
    "EXL3_CPU_PIN": "8 (CPU pinning)",
    "VLLM_DSV41_VOR_FUSED": "9 (0067)",
    "VLLM_DSV41_RELEASE_TOKENS": "10 (0085b)",
    "VLLM_DSPARK_REMOTE_N_OUT": "11 (NOUT-TRIM)",
}
KNOB_ITEMS = {"SPEC": "3 (K5)", "MAX_BATCH": "4 (chunk 8192)", "EXTRA": "4 (threshold literal 1024, same value)",
              "PROD_UPSTREAM_ALL": "install marker (stage/verify switch)"}


def materialize(commit: str, where: Path) -> dict[str, str]:
    for name in ("dsv41.env", "serve.sh"):
        data = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{name}"], check=True,
                              stdout=subprocess.PIPE).stdout
        (where / name).write_bytes(data)
    out = subprocess.run(["bash", "-c", PROBE], cwd=where, check=True, stdout=subprocess.PIPE, text=True,
                         env={"PATH": "/usr/bin:/bin", "HOME": "/home/x"}).stdout
    value: dict[str, str] = json.loads(out)
    return value


def env_of(cfg: dict[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for kv in cfg["DOCKER_ENV"].split():
        key, val = kv.split("=", 1)
        env[key] = val
    return env


def mounts_of(cfg: dict[str, str]) -> dict[str, str]:
    args = shlex.split(cfg["OFFLOAD_DOCKER_ARGS"])
    assert all(a == "-v" for a in args[::2]), "OFFLOAD_DOCKER_ARGS must be -v pairs"
    out: dict[str, str] = {}
    for spec in args[1::2]:
        src, dst, mode = spec.rsplit(":", 2)
        assert mode == "ro" and dst not in out, spec
        out[dst] = src
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="596ba1cf4e3b11be29b41a57e7f69a5d8efa4799")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--markdown", type=Path)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        base, head = materialize(a.base, Path(t1)), materialize(a.head, Path(t2))
    manifest = json.loads((ROOT / "offload/upstream_all/MANIFEST.json").read_text())
    rows: list[tuple[str, str, str, str]] = []
    bad: list[str] = []
    eb, eh = env_of(base), env_of(head)
    for key in sorted(set(eb) | set(eh)):
        if eb.get(key) != eh.get(key):
            item = ENV_ITEMS.get(key)
            rows.append(("env", key, f"{eb.get(key)!r} -> {eh.get(key)!r}", item or "UNDECLARED"))
            if item is None:
                bad.append(f"env {key}")
    for key in ("SPEC", "MAX_BATCH", "MAX_SEQS", "MAX_LEN", "KV_BYTES", "EXTRA", "GPU_CLOCK_CAP", "MODEL_DIR", "IMAGE",
                "PROD_K1", "PROD_K1_PROFILE", "PROD_UPSTREAM_ALL"):
        if base[key] != head[key]:
            item = KNOB_ITEMS.get(key)
            if key == "EXTRA" and base[key] != head[key]:
                item = None  # the rendered argv must not change; only the source text may
            rows.append(("knob", key, f"{base[key]!r} -> {head[key]!r}", item or "UNDECLARED"))
            if item is None:
                bad.append(f"knob {key}")
    mb, mh = mounts_of(base), mounts_of(head)
    declared = {r["container_path"]: r["item"] for r in manifest["files"] if r["path"].startswith("dist/")}
    declared[manifest["library"]["container_path"]] = "5 (top-k library)"
    remote = manifest["remote_dspark_mount"]
    for dst in sorted(set(mb) | set(mh)):
        if mb.get(dst) == mh.get(dst):
            continue
        if dst == remote and dst in mb and dst in mh:
            item = "6 (0075 remote_dspark package replaces production's)"
        elif dst not in mb and dst in declared:
            item = declared[dst]
        else:
            item = None
        rows.append(("mount", dst, f"{mb.get(dst)} -> {mh.get(dst)}", item or "UNDECLARED"))
        if item is None:
            bad.append(f"mount {dst}")
    for dst, src in mb.items():
        if dst in mh and mh[dst] != src and dst != remote:
            bad.append(f"production mount source changed: {dst}")
    lines = [f"# UPSTREAM-ALL delta audit: {a.base[:12]} -> {a.head}", "",
             f"Rendered from git objects by offload/upstream_all/audit.py. {len(rows)} differences; "
             f"{len(bad)} undeclared.", "", "| Kind | Key / target | Change | Item |", "|-|-|-|-|"]
    for kind, key, change, item in rows:
        short = change.replace("\\$HOME", "~").replace(DIST, "P/").replace("$HOME", "~")
        lines.append(f"| {kind} | `{key.replace(DIST, 'P/')}` | {short} | {item} |")
    lines += ["", f"Unchanged production mounts: {sum(1 for d in mb if mb.get(d) == mh.get(d))} of {len(mb)}; "
              f"env keys unchanged: {sum(1 for k in eb if eb.get(k) == eh.get(k))} of {len(eb)}.",
              "", "RESULT: " + ("PASS (every difference is a declared item)" if not bad else "FAIL: " + "; ".join(bad))]
    text = "\n".join(lines) + "\n"
    if a.markdown:
        a.markdown.write_text(text)
    print(text)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
