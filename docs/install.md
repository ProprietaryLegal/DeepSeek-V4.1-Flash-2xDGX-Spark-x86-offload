# Install: the full build, step by step

This is how DGX sPLIce is put together in production, in the order it has to happen. Machine names are roles:
`sparkhead` (rank 0, runs the API), `sparkworker` (rank 1) and `x86host` (Engram server and drafter worker). The
addresses are the ones in [dsv41.env](../dsv41.env); replace them with your own. Every component README under
`offload/` has more detail and its own rollback; this page links to them where they matter.

Allow a day for the first build. Most of it is downloads (about 400 GB per Spark) and the x86 host's two copies.

## 0. What you need

| Item | Tested configuration |
|-|-|
| serving nodes | 2 x NVIDIA DGX Spark (GB10, 121 GiB unified memory), DGX OS, Docker with the NVIDIA runtime |
| Spark-to-Spark link | one QSFP cable between the ConnectX-7 ports, 200 Gb/s |
| offload host | x86_64 with about 220 GiB of RAM to spare for the Engram tables (the server's budget is 215 GiB); ours is an AMD EPYC 7302P, 16 cores, 503 GiB |
| host links | a ConnectX-5 Ex (or any RoCE v2 NIC) with one 40 Gb/s DAC to each Spark |
| drafter GPUs | 2 x RTX 3090 24 GB with an NVLink bridge (one card also works, slower); driver with CUDA 12.6 or newer |
| software on the x86 host | CUDA toolkit 12.6, `libibverbs` and its headers, `uv` (or any Python 3.12 venv tool), systemd user units |

Without the x86 host, DGX sPLIce runs as a plain two-Spark serve: skip steps 4-6 and see the last section.

## 1. Cabling and addresses

| Link | Interface (ours) | Addresses in `dsv41.env` | Used for |
|-|-|-|-|
| sparkhead <-> sparkworker | `enp1s0f1np1`, RoCE `rocep1s0f1` and `roceP2p1s0f1` (both PCIe functions of the port) | `10.202.26.2` / `10.202.26.1`, second function `10.202.27.x` | NCCL and the plugin's RDMA ring |
| x86host <-> sparkhead | port f0 of each Spark, 40 Gb/s DAC, MTU 9000 | `10.202.28.1` (x86host) / `10.202.28.2` | Engram rows, draft rounds |
| x86host <-> sparkworker | as above | `10.202.29.1` / `10.202.29.2` | Engram rows |

Check that every link comes up with RoCE v2 (`ibv_devinfo`, and `ofl_probe` from step 5) before going further. sparkhead needs key-based ssh to
sparkworker and to x86host, under the aliases you will put in `dsv41.env` (`HEAD`, `WORKER`).

## 2. The image (both Sparks)

Production runs HeNryous's image unmodified. Pull it on both Sparks and check that the digest is the one we run:

```bash
docker pull ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5
docker image inspect --format '{{json .RepoDigests}} {{.Architecture}}' ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5
# ["ghcr.io/henryous/deepseek-v41-1017-dgx-spark@sha256:8fc2c99a3562e99d81d2a05b8345d12726def0a027410d14d0eb0763de8309e4"] arm64
```

If the tag has moved, pull by digest and tag it, because the scripts name the tag:

```bash
docker pull ghcr.io/henryous/deepseek-v41-1017-dgx-spark@sha256:8fc2c99a3562e99d81d2a05b8345d12726def0a027410d14d0eb0763de8309e4
docker tag ghcr.io/henryous/deepseek-v41-1017-dgx-spark@sha256:8fc2c99a3562e99d81d2a05b8345d12726def0a027410d14d0eb0763de8309e4 \
    ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5
```

There is no second image. Our changes are overlays: `start.sh` copies each one from this checkout into a
content-addressed folder on both nodes, checks every staged file against its pinned sha256, and the launcher
bind-mounts them read-only into the container. The overlays are `offload/upstream_all/` (the upstream patch set),
`offload/pp4_prod/` (sampled drafting), `offload/kvpack/` (KV page packing), `offload/engram/spark/` (remote Engram
reader) and `offload/dspark/spark/` (remote drafter client and async proxy). The staging scripts also check that the
image's own files are the ones each overlay was made from, so a different image is refused rather than half-patched.

## 3. Launcher and weights (Spark side)

On sparkhead, clone the launcher at the commit we run and apply our one change to it (where each node keeps its
generated launch file; the default `/tmp` is wiped at reboot):

```bash
git clone https://github.com/sudoingX/dgx-spark-deepseek-v41 ~/dgx-spark-deepseek-v41
git -C ~/dgx-spark-deepseek-v41 checkout cc59c36
git -C ~/dgx-spark-deepseek-v41 apply ~/dsv41-deploy/recipe-servedir.patch
```

Clone this repository to `~/dsv41-deploy` on sparkhead. On **both** Sparks, download the weights with
[download.sh](../download.sh): HeNryous's 2.75 bpw quant at revision `86f85253` plus DeepSeek's two Engram shards
(`model-00047` and `model-00048` of `deepseek-ai/DeepSeek-V4.1-Flash-1017` at `1bae0e10`), with a size check for each
shard. It expects the `hf` CLI in `~/.venvs/hfcli`. Then point `/srv/dsv41/model` at the download (a symlink is fine).
sparkworker needs its own copy on local NVMe; a network mount is too slow to load from.

```bash
bash download.sh                                     # about 400 GB; prints DONE with the file count and size
sudo mkdir -p /srv/dsv41 && sudo ln -sfn ~/models/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark /srv/dsv41/model
python3 verify_hashes.py /srv/dsv41/model            # optional: every file's sha256 against the HF tree at the pinned revisions
```

The legal-weighted allocation we serve is the same size and format: download its Hugging Face repository into a
directory of its own on both Sparks and set `MODEL_DIR` to it. `start.sh` refuses to start unless `config.json` and the
last weight shard are present on both nodes.

## 4. Drafter layers and Engram tables onto the x86 host

Nothing extra is downloaded for the x86 host. Its two jobs use parts of the same checkpoint:

- **Drafter**: the checkpoint's DSpark layers (3 layers plus the Markov head), 4,755 tensors repacked into eight
  safetensors files with their original names, shapes and dtypes (5,774,545,892 bytes), plus the config, the EXL3 plan,
  the tokenizer and the live `markov_top_tokens.json` from the Sparks' cache. No conversion is applied.
- **Engram**: DeepSeek's two Engram shards, whole, with the original index.

[offload/dspark/TRANSFER.md](../offload/dspark/TRANSFER.md) is the exact procedure:
`offload/dspark/inventory_source.py` and `build_inventory.py` record every tensor's source byte range and sha256, and
`copy_to_x86host.py` copies with direct reads and paced writes, checks every hash and writes the ready markers
`DSPARK_COPY_DONE` and `ENGRAM_COPY_DONE` under `/opt/dsv41/x86host-data/`. The services below wait for those markers.

## 5. x86 host: the Engram server

```bash
make -C offload/engram/server OUT=$HOME/dsv41-offload/prod/bin          # engram_server and engram_check; needs libibverbs
make -C offload/transport OUT=$HOME/dsv41-offload/prod/bin              # libofl.so, ofl_pingpong, ofl_probe
```

Install [offload/engram/server/dsv41-engram.prod.service](../offload/engram/server/dsv41-engram.prod.service) as a
systemd user unit (edit `--listen` to your two link addresses; `--budget-gib 215` caps its RAM) and start it. Loading
the two tables takes about 70 s, with a sha256 check of each; the unit's stats file
(`~/dsv41-offload/prod/run/engram_server.stats.json`) then shows it ready, both tables verified and both listeners. [offload/engram/INTEGRATION.md](../offload/engram/INTEGRATION.md) has the checks.

## 6. x86 host: the drafter worker

1. Build the worker's venv exactly as [offload/dspark/worker/ENV.md](../offload/dspark/worker/ENV.md) says: CPython
   3.12, torch `2.10.0+cu126`, exllamav3 1.6.0 at `151539c7` built for `sm_86`, and the second module
   `exllamav3_ext_facc` (the same commit with fp32 accumulation, from `offload/dspark/worker/exl3/exllamav3_facc.patch`).
   `requirements.e.lock` pins the rest.
2. Pin the transport for the worker: `offload/dspark/worker/run/pin_ofl.sh` (copies `libofl.so` and `ofl.py` and records
   their sha256s).
3. Lay out the production tree and the unit with [offload/dspark/worker/run/prod_tp2.sh](../offload/dspark/worker/run/prod_tp2.sh):
   `stage <commit>`, `build-p2p <commit>`, `install-unit`, then `check <commit>`, then point `current` at the commit.
4. Edit the unit's `CUDA_VISIBLE_DEVICES` to your two cards' UUIDs (`nvidia-smi -L`) and `--ofl` to x86host's head-link
   address, then `systemctl --user enable --now dsv41-dspark-worker-tp2-prod`. One card: use
   `dsv41-dspark-worker.prod.service` instead.
5. Production caps both cards at 325 W (`sudo nvidia-smi -i <ids> -pl 325`); they draw far less in normal use.

The worker checks what it loads against the copy receipt. `python3 offload/dspark/worker/identity.py
/opt/dsv41/x86host-data/dspark` prints `drafter_identity`; it has to equal `VLLM_DSPARK_REMOTE_IDENTITY` in
`dsv41.env`, which is the value for HeNryous's checkpoint at `86f85253`.

## 7. Spark side: transport builds and `dsv41.env`

The remote drafter client loads two small aarch64 libraries. Build them on sparkhead; `start.sh` stages them to both
nodes with the rest of the drafter overlay:

```bash
mkdir -p $HOME/dsv41-offload-prod/pinned
cd ~/dsv41-deploy/offload/transport && make OUT=$HOME/dsv41-offload-prod/pinned $HOME/dsv41-offload-prod/pinned/libofl.so
cc -O2 -Wall -shared -fPIC -o $HOME/dsv41-offload-prod/pinned/libdsv41_hostflag.so \
    ~/dsv41-deploy/offload/dspark/spark/remote_dspark/hostflag.c -lpthread
sha256sum $HOME/dsv41-offload-prod/pinned/*.so
```

[offload/dspark/spark/stage_overlay.sh](../offload/dspark/spark/stage_overlay.sh) pins the sha256 of our builds
(`OFL_SO_SHA`, `HOSTFLAG_SO_SHA`). A build with a different compiler gives different bytes; the script then refuses to
stage, and you put your own build's sha256 in those two lines.

Then edit [dsv41.env](../dsv41.env):

| Variable | Set it to |
|-|-|
| `HEAD`, `WORKER` | your ssh aliases for the two Sparks |
| `FAB_IF`, `FAB_HCA` | the Spark-to-Spark netdev and its RoCE device (also in `serve.sh`, `NCCL_IB_HCA`, `EXL3_RDMA_DEVICES`) |
| `MODEL_DIR` | `/srv/dsv41/model`, or the legal-weighted allocation's directory |
| `OFFLOAD_DOCKER_ENV` | x86host's two link addresses in `VLLM_ENGRAM_REMOTE` |
| `OFFLOAD_DSPARK_ENV` | x86host's head-link address and port in `VLLM_DSPARK_REMOTE`, sparkhead's in `VLLM_DSPARK_REMOTE_BIND` |
| `GPU_CLOCK_CAP` | `start.sh` sets 2,150 MHz by default; every 2026-10-31 number used 2,300 (`GPU_CLOCK_CAP=2300`) |

Leave the rest as shipped: `PROD_KV_BYTES` (6 GiB per rank), `PROD_MAX_LEN` (327,680), `PROD_K1`, `PROD_UPSTREAM_ALL`
and `PROD_PP4` name the exact overlay stages the numbers were measured with.

## 8. First start and checks

With the Engram server ready and the drafter worker running, on sparkhead:

```bash
cd ~/dsv41-deploy
./start.sh       # checks model and image on both nodes, sets the clock cap, stages and verifies every overlay,
                 # prebuilds the JIT kernels, starts both ranks, runs the KV-packing check, sends one warm-up request
./status.sh      # both nodes, free memory, temperature and clock, API health, key /metrics
```

The first start builds the JIT kernels and takes longer; later starts take several minutes. Then check, as
[docs/operations.md](operations.md#checks-after-a-start) lists: the engine log reports `GPU KV cache size: 1,934,490 tokens`,
the `engram_remote` lines show lookups and 0 fallbacks, `/metrics` shows speculative rounds and accepted tokens rising,
and the three `verify` scripts match the running containers to the staged bytes. Without the prefix tier's
configuration, `serve.sh` prints `MATTER OFF (config-missing)` once; that is expected in this commit.

## 9. Measure

```bash
sudo nvidia-smi -lgc 0,2300          # on both Sparks, if start.sh did not
python3 -I tools/sparkbench.py --url http://<head>:8000 --out runs/my-sparks.json --reps 3 \
    --suites prose-t0,code-t0,structured-t0,prose-t07-think,prose-t1-think,prefill \
    --deep 32768:1,32768:4,131072:1 --interference 2
```

Compare with [runs/2026-10-31-sparkdash-protocol-ebc29ed8.json](../runs/2026-10-31-sparkdash-protocol-ebc29ed8.json)
and send yours as a performance report issue.

## A plain two-Spark serve

Without the x86 host: comment out `OFFLOAD_DOCKER_ENV`, `OFFLOAD_DSPARK_ENV`, `OFFLOAD_DOCKER_ARGS` and
`PROD_KV_BYTES` in `dsv41.env`. The KV pool goes back to 3.75 GiB per rank (989,460 tokens) and the drafter runs on the
Sparks. `serve.sh` refuses a larger pool without the remote drafter, and refuses a half-enabled drafter block. What
each offload bought when it was added (context, concurrency, decode cost) is in
[docs/measurements.md](measurements.md#configuration-history-2026-10-22-and-2026-10-23).
