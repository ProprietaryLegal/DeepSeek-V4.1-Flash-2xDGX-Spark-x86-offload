#!/usr/bin/env python3
"""UPSTREAM-INSTALL (NDM 2026-10-28): compose the upstream overlay files into ONE content-addressed tree.

CPU only. Reads git objects of the pinned source commits (never a working tree, never GIT_DIR & co.), checks every
file against its pinned sha256, and writes `overlay/` + `MANIFEST.json` beside this file:

    python3 offload/upstream_all/build.py write    # (re)generate overlay/ and MANIFEST.json
    python3 offload/upstream_all/build.py check    # overlay/ and MANIFEST.json equal a fresh build

The K1 overlay (13 files, offload/kvpack) stays as production mounts it; nothing here replaces a K1 file.
The top-k library (dsv41_topk.so, an SM121 build product, never in git) is pinned by sha256 only; stage.sh copies it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIST = "/usr/local/lib/python3.12/dist-packages/"
REMOTE = "vllm/v1/worker/gpu/spec_decode/remote_dspark"

# Source commits (Controller, git hub): the reviewed overlay builds of the owning lanes.
UPFIX = "08b9d8a0ca2bac388b0fe5c7d334e3db80ed6d95"   # offload/upfix: 0091 overlays, 0091-on-0075 scheduler, top-k overlay
UPX = "5aad62527879f2c22a44367fdd503c4a91cc7d21"     # offload/upx: 0085b port; upstream_adopt composed 0067+0075 model_state
UP2 = "67894521fe61565913da1a71f4c55ba6f9ee7eda"     # offload/up2-adopt: UP3 replay arm = UP2 qualified package ad3dc5be5eaf
UP3 = "6c345ad213e78515b634fe0e0b2a0e2d25e20033"     # offload/up3-win2: production-exact 0064 split and 0067 vor arms
NOUT = "08574bdc2b5f5ad8bc906565d47624b94c3b7c66"    # exp/NOUT-TRIM: drafter request trim (offload/nout_trim, item 11)

# (item, container path relative to DIST, source commit, source path, sha256)
FILES: tuple[tuple[str, str, str, str, str], ...] = (
    ("0091", "vllm/distributed/device_communicators/shm_broadcast.py", UPFIX,
     "offload/upfix/overlay/vllm/distributed/device_communicators/shm_broadcast.py",
     "bcd86fd49e3fd4072d78533193d7d13afd088e8e1c239896ebf1311e6e8e6a1b"),
    ("0091", "vllm/v1/kv_offload/tiering/async_lookup.py", UPFIX,
     "offload/upfix/overlay/vllm/v1/kv_offload/tiering/async_lookup.py",
     "7c04c46385a2b0f7796f2e4c194a3107a91e22e160193e4f2d961fa44e236750"),
    ("0091", "vllm/v1/worker/gpu/block_table.py", UPFIX,
     "offload/upfix/overlay/vllm/v1/worker/gpu/block_table.py",
     "9de6fa6d9ce0964b879abc7f2a6f00715b5c8d5947fdd16f5ea7cafd2528c742"),
    ("0091+0075", "vllm/v1/core/sched/scheduler.py", UPFIX,
     "offload/upfix/overlay-0075/vllm/v1/core/sched/scheduler.py",
     "079986917de3505a29e13bba3837a8b756bac3928598de01258018a4cc1d4e71"),
    ("topk", "vllm/model_executor/layers/indexer_topk.py", UPFIX,
     "offload/upfix/topk/overlay/vllm/model_executor/layers/indexer_topk.py",
     "706816bc69525167a3e17174742e918695ebb6b542651fabfb3f861b48407407"),
    ("0075+0067", "vllm/models/deepseek_v41/nvidia/model_state.py", UPX,
     "offload/upstream_adopt/overlay/vllm/models/deepseek_v41/nvidia/model_state.py",
     "1e0ce91d2a810255b287e44d7e9f3c8f996c5cd32f00e20f0910bb93bdad069f"),
    ("0075", "vllm/models/deepseek_v41/replay_skip.py", UP2,
     "offload/up3/overlay/replay/vllm/models/deepseek_v41/replay_skip.py",
     "cc6dcd79884d6726cd3b8cd0bd13f263408bd95289c2303dc823423a6b922b65"),
    ("0075", "vllm/v1/worker/gpu/input_batch.py", UP2,
     "offload/up3/overlay/replay/vllm/v1/worker/gpu/input_batch.py",
     "056f7eec511c71f25f82e6acb660fa5f405615efbf6d096ec8753f2f1c91462f"),
    ("0064", "vllm_exl3_moe/forward.py", UP3, "offload/up3/overlay/split/vllm_exl3_moe/forward.py",
     "c06ba9b66e6349fc4c0bad93a74e62c22d489f1a9d54596a5d10fd0fcb7c8966"),
    ("0064", "vllm_exl3_moe/smoe.py", UP3, "offload/up3/overlay/split/vllm_exl3_moe/smoe.py",
     "954976235fb0064204112b4b5388a6b04a1f0ebf092bf6ce6666584ac99b1497"),
    ("0067", "vllm/models/deepseek_v41/common/ops/swa_fused.py", UP3,
     "offload/up3/overlay/vor/vllm/models/deepseek_v41/common/ops/swa_fused.py",
     "3deeeb8cd82b49acaa405bff7a1827c97984ea12e75c71af5986cdc46f1bc5be"),
    ("0067", "vllm/v1/attention/backends/mla/sparse_swa.py", UP3,
     "offload/up3/overlay/vor/vllm/v1/attention/backends/mla/sparse_swa.py",
     "1995997b763d57fcbb4b1028dc6f5831dd26294d6911a4c485801856f2321173"),
    ("0085b", "vllm/v1/engine/core.py", UPX, "offload/upx/overlay/vllm/v1/engine/core.py",
     "dc7b3fec51b84256567fd58b21d6bb6ede6e3335b12974de88917ec08fb8db0f"),
    # 0085b (UPX 837e3e89) + the NOUT-TRIM hand-off of the scheduler's next-step draft count (item 11)
    ("0085b+trim", "vllm/v1/worker/gpu_worker.py", NOUT, "offload/nout_trim/overlay/dist/vllm/v1/worker/gpu_worker.py",
     "10ab55642238131bfb8b2ce60b347d4bba896b89b3a49aa45afe01bc8a3efe66"),
)
# The remote-DSpark package with 0075's taps: the UP2 qualified package (production's package + gather/round/roundcore/
# speculator changes + suffix_provenance.py). Mounted as ONE directory in place of production's remote_dspark mount.
# Item 11 (NOUT-TRIM): that package with the drafter request trim (config, proxy_proc, round, roundcore, shmregion,
# speculator changed; offload/nout_trim/README.md); the other 14 files are UP2's byte for byte.
REMOTE_SRC = (NOUT, "offload/nout_trim/overlay/remote_dspark")
REMOTE_FILES: dict[str, str] = {
    "__init__.py": "9467a2214fb05bc8a10a63d4dc2faa8c646af949d730c9e3613978a66c2b09cc",
    "breaker.py": "78bcc9c0504bc9c6dba3f48925408c48749a9ee88dba3498ac42d67e711e3887",
    "client.py": "a9222d4aab14abcf960c99dec0e37c80088210a532f5f91d6058583cc9cb3bd4",
    "config.py": "e4308418e92b066c2410268bff97dd27904c80428f789541d18652480956f66b",
    "fused_gather.py": "6c42c28e5d6f1918081d939c1b31d6895af54ca5328ea346903a3f0ad3a98c6f",
    "gather.py": "31eb8151aa5c7928dcfbd006a554fc5204dfefd26a90230be6ba227d1cfd40e7",
    "hostflag.py": "7e1ce6e645c1c25c8f33e305ca35a05379a8c6a85920c1e3f75462a9fa76b130",
    "mock_worker.py": "09dabb928d5f6c659553a1beac0259ab6590958683bb1800c37ac016af0013db",
    "o1_adapter.py": "ee0c171c2aadfd0cbc80d5cf036087b6a94fabbbe0e441e60c68b8c690943e38",
    "proxy_proc.py": "97d862f236ee9f316a85fd8ab896b5147e6df3959cc690b38d0fa90c385c1b61",
    "round.py": "4517dc5cdc869745bad5a184457aba3f884822c8008b1c4a730b5e88a76ba817",
    "roundcore.py": "7fddb63bb34e689466ae0ca419de16a3bf08397a820a8c94548457eb34aba65e",
    "shmregion.py": "e029ac36ff39a5fc9cc1108514c499962770bd28965b9d10d988d4f6b5a93612",
    "speculator.py": "a8d9cfbb07dc82eaa5ccb7e147dc5787bb6c3c6e99df7c1a59560d68b3ac8450",
    "state.py": "647b887e432911f81aee8adf153d9240e58dffc5140cbdbda17de288d3fb6d62",
    "stats.py": "9a58853a6254614918d0d2b2756cbca7e3d41ecae7c7b37c7d85a96959e20e61",
    "streamsync.py": "4d26e408f562659ed143405ef6e8977fcbda6735e192c941fa023db3cdc46cab",
    "suffix_provenance.py": "f45966212bdb01ad71b219a8a97082c58b3074af9c1edbb9679c070d791c2c22",
    "transport.py": "4b59d0764cb364103a2e3cb3ddf2b04108891a092a0269edd1d3e24be5e4977b",
    "wire.py": "bdcf6340f8f42fca4940889e18d3a80b652342e82eaa887dd25a29c47778ec2a",
}
# Built by the upf-topk window's T1 inside the serving image (SM121), bit-compare v3 PASS 149/149 on a GB10.
TOPK_SO = {"container_path": "/opt/dsv41-upfix/dsv41_topk.so",
           "sha256": "7e03af0d46a1de497987209aba65d96a7e44d5d26a7c829cd805971302e74171",
           "pinned_source": "~/dsv41-offload-prod/pinned/dsv41_topk.so (sparkhead; copied from the upf-topk T1 build)"}
# Every switch this package turns on (dsv41.env OFFLOAD_DOCKER_ENV, next to its mounts; item 11 in OFFLOAD_DSPARK_ENV,
# the remote drafter's env).
SWITCHES = {
    "VLLM_DSV41_INDEXER_DEFER": "1",          # item 1, 0051 (code in the K1 overlay's attention.py)
    "VLLM_DSV41_TOPK_FIX": "1",               # item 5, top-k
    "VLLM_DSV41_TOPK_FIX_SO": TOPK_SO["container_path"],
    "VLLM_DSV41_REPLAY_SKIP": "1",            # item 6, 0075
    "VLLM_EXL3_MOE_SPLIT_MAX_TOKENS": "63",   # item 7, 0064
    "VLLM_DSV41_VOR_FUSED": "1",              # item 9, 0067
    "VLLM_DSV41_RELEASE_TOKENS": "131072",    # item 10, 0085b (the author's threshold, README:598)
    "VLLM_DSPARK_REMOTE_N_OUT": "window",     # item 11, NOUT-TRIM (remote form of 0066 MARKOV_TRIM)
}
# Config-only items in serve.sh (image code, the author's serve_example.sh values): the container env and launch argv.
SERVE_ENV = {
    "EXL3_RDMA_DEVICES": "rocep1s0f1,roceP2p1s0f1",   # item 2, dual ring (our f1 port's two PCIe functions)
    "EXL3_CPU_PIN": "5-9,15-19",                       # item 8 (the RDMA poller still self-pins to EXL3_RDMA_CPU=14)
}
SERVE_ARGV = {
    "--speculative-config": '{"method":"dspark","num_speculative_tokens":5,"num_speculative_tokens_per_batch_size":[[1,4,5]]}',
    "--max-num-batched-tokens": "8192",                # item 4
    "--long-prefill-token-threshold": "1024",
}
STAGE = "$HOME/dsv41-upstream-all"


def git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{path}"], check=True,
                          stdout=subprocess.PIPE).stdout


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> tuple[dict[str, bytes], bytes]:
    out: dict[str, bytes] = {}
    rows: list[dict[str, str]] = []
    for item, rel, commit, src, want in FILES:
        data = git_blob(commit, src)
        if sha(data) != want:
            raise SystemExit(f"{commit[:12]}:{src} sha256 {sha(data)} != pinned {want}")
        out[f"dist/{rel}"] = data
        rows.append({"item": item, "path": f"dist/{rel}", "container_path": DIST + rel, "sha256": want,
                     "source": f"{commit}:{src}"})
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "--name-only", f"{REMOTE_SRC[0]}:{REMOTE_SRC[1]}"],
                            check=True, stdout=subprocess.PIPE, text=True).stdout.split()
    if sorted(listed) != sorted(REMOTE_FILES):
        raise SystemExit(f"remote package file set differs: {sorted(set(listed) ^ set(REMOTE_FILES))}")
    for name, want in sorted(REMOTE_FILES.items()):
        data = git_blob(REMOTE_SRC[0], f"{REMOTE_SRC[1]}/{name}")
        if sha(data) != want:
            raise SystemExit(f"remote_dspark/{name} sha256 {sha(data)} != pinned {want}")
        out[f"remote_dspark/{name}"] = data
        rows.append({"item": "0075+trim", "path": f"remote_dspark/{name}", "container_path": f"{DIST}{REMOTE}/{name}",
                     "sha256": want, "source": f"{REMOTE_SRC[0]}:{REMOTE_SRC[1]}/{name}"})
    manifest = {
        "schema": "dsv41-upstream-all-v1",
        "plan": "documents/plans/2026-10-28-UPSTREAM-INSTALL.md",
        "base": "596ba1cf4e3b11be29b41a57e7f69a5d8efa4799",
        "image": "ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5",
        "k1_overlay": "offload/kvpack MANIFEST 559c5867ba42 (unchanged, mounted as in production)",
        "remote_dspark_mount": DIST + REMOTE,
        "files": rows,
        "library": TOPK_SO,
        "switches": SWITCHES,
        "serve_env": SERVE_ENV,
        "serve_argv": SERVE_ARGV,
    }
    return out, (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()


def docker_args(manifest_id: str) -> list[str]:
    """The -v pairs dsv41.env adds (dist files + library); the remote_dspark directory replaces production's mount."""
    rows = json.loads((HERE / "MANIFEST.json").read_text())["files"]
    root = f"{STAGE}/{manifest_id}"
    pairs = [f"{root}/{r['path']}:{r['container_path']}:ro" for r in rows if r["path"].startswith("dist/")]
    pairs.append(f"{root}/lib/dsv41_topk.so:{TOPK_SO['container_path']}:ro")
    return pairs


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "id":
        print(sha((HERE / "MANIFEST.json").read_bytes())[:12])
        return
    if mode == "mounts":
        print(" ".join(f"-v {m}" for m in docker_args(sha((HERE / "MANIFEST.json").read_bytes())[:12])))
        return
    files, manifest = build()
    overlay = HERE / "overlay"
    if mode == "write":
        for rel, data in files.items():
            path = overlay / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (HERE / "MANIFEST.json").write_bytes(manifest)
    elif mode != "check":
        raise SystemExit("usage: build.py write|check")
    on_disk = {str(p.relative_to(overlay)) for p in overlay.rglob("*") if p.is_file()}
    if on_disk != set(files):
        raise SystemExit(f"overlay/ file set differs from a fresh build: {sorted(on_disk ^ set(files))}")
    for rel, data in files.items():
        if (overlay / rel).read_bytes() != data:
            raise SystemExit(f"overlay/{rel} differs from a fresh build")
    if (HERE / "MANIFEST.json").read_bytes() != manifest:
        raise SystemExit("MANIFEST.json differs from a fresh build")
    print(f"upstream-all overlay: {len(files)} files + library, id {sha(manifest)[:12]} ({mode} ok)")


if __name__ == "__main__":
    main()
