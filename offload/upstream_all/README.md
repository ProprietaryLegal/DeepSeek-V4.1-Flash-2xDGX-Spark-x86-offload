# UPSTREAM-ALL: every author-proven upstream optimization, installed together (NDM 2026-10-28)

Plan: `documents/plans/2026-10-28-UPSTREAM-INSTALL.md` (e74e59d on offload-x86host). Branch `prod/upstream-all`, built on
production 596ba1c. NDM: "Flip them all on, install them, and run them. I trust the upstream documentation."

| # | Item (author's serve_example.sh line) | Where | Switch / value |
|-|-|-|-|
| 1 | 0051 indexer defer (U:74) | K1 overlay `attention.py` (already mounted) | `VLLM_DSV41_INDEXER_DEFER=1` (dsv41.env); K1_EXPECT updated |
| 2 | Dual ring (U:64) | image | `EXL3_RDMA_DEVICES=rocep1s0f1,roceP2p1s0f1` (serve.sh; our f1 port) |
| 3 | K5 (U:27, 4 slots) | image | SPEC `[[1,4,5]]` (serve.sh) |
| 4 | Prefill chunks 8192 (prod/chunk8192 e922091 + ec6dae0) | image | `--max-num-batched-tokens 8192`, threshold stays 1024 |
| 5 | 0091 vLLM fix bundle + top-k fix (offload/upfix 08b9d8a) | overlay `dist/` + `lib/dsv41_topk.so` | `VLLM_DSV41_TOPK_FIX=1`, `VLLM_DSV41_TOPK_FIX_SO` |
| 6 | 0075 replay skip (UP2 qualified package ad3dc5be5eaf) | overlay `dist/` + `remote_dspark/` (replaces production's remote mount) | `VLLM_DSV41_REPLAY_SKIP=1` |
| 7 | 0064 smoe split (U:74) | overlay `forward.py`, `smoe.py` | `VLLM_EXL3_MOE_SPLIT_MAX_TOKENS=63` |
| 8 | CPU pinning (U:74) | image | `EXL3_CPU_PIN=5-9,15-19` (serve.sh); the RDMA poller still self-pins to CPU 14 |
| 9 | 0067 VOR/SWA fused (U:75) | overlay `swa_fused.py`, `sparse_swa.py`, `model_state.py` | `VLLM_DSV41_VOR_FUSED=1` |
| 10 | 0085b idle cache release (README:581/598) | overlay `engine/core.py`, `worker/gpu_worker.py` | `VLLM_DSV41_RELEASE_TOKENS=131072` |
| 11 | NOUT-TRIM: remote form of 0066 MARKOV_TRIM (NDM /goal item 3, `offload/nout_trim`) | overlay `remote_dspark/` (6 files) + the `worker/gpu_worker.py` hand-off | `VLLM_DSPARK_REMOTE_N_OUT=window` (OFFLOAD_DSPARK_ENV) |

Shared files: `scheduler.py` = 0091 on 0075 (`offload/upfix/overlay-0075`, 079986917d); `model_state.py` = 0067 + 0075
(1e0ce91d: the three-way merge of UP3's vor and UP2's replay files differs only by the two import lines, both kept).
No K1 file is replaced; K1's 13 mounts are production's.

## Files

- `build.py write|check|id|mounts`: composes `overlay/` from pinned git objects (every sha256 pinned) and writes
  `MANIFEST.json`; the stage id is `sha256(MANIFEST.json)[:12]` (= `PROD_UPSTREAM_ALL` in dsv41.env).
- `stage.sh HEAD WORKER`: start.sh stages `~/dsv41-upstream-all/<id>/` on both nodes (read-only; library from
  `~/dsv41-upstream-all/pinned/dsv41_topk.so` on the head node, sha256 pinned).
- `verify_running.sh HEAD WORKER`: K1's verify.sh proves every file, switch and argv value inside both running containers.
- `rebase_k1_record.py`: rebases `logs/k1-promotion/files.json` (K1's start guard) onto this dsv41.env/start.sh.
- `audit.py`: the delta audit vs 596ba1c (every rendered env/argv/mount difference must be a declared item).
- K1 guard edits: `start_checked.sh` never restores the pre-K1 backup over an upstream-all start (it stops and refers to
  the rollback); `verify.sh` runs `verify_running.sh`; `constants.sh` K1_EXPECT includes the 0051 switch.

## Rollback

Controller: `/opt/dsv41/campaigns/DSV41-OFFLOAD/INSTALL-ALL/ROLLBACK.sh` (sparkhead back to main @ 596ba1c, the K1
record byte for byte from `/opt/dsv41/data/backups/pre-upstream-20261028/`, then the strict W8 start/check/close).

Licences: overlay files are vLLM sources (Apache-2.0, SPDX headers kept) with henryous patches (Apache-2.0); see
`offload/upfix/NOTICE`, `offload/upx/NOTICE` and `offload/upstream_adopt/NOTICE` on their source branches.
