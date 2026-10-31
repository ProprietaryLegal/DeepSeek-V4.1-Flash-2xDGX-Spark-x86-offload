# Architecture

The target model runs on two DGX Sparks in tensor parallel (TP2), as in the upstream recipes. Two of its memory and
time costs move to a third machine, an x86 server with plenty of RAM and two RTX 3090s, connected to each Spark by its
own 40 Gb/s RDMA link. The Spark memory this frees becomes KV cache. A persistent tier on the Sparks' NVMe keeps
long-prompt KV across restarts.

## Target: two Sparks, TP2

- Image `ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5` (vLLM 0.31.1.dev0+g6e517b15), started by the sudoingX launcher
  (`offload/launch/dsv41_tp2_offload.sh` wraps it with read-only overlay mounts).
- Rank 0 runs the OpenAI API on port 8000; the ranks talk NCCL over the direct ConnectX-7 200 Gb/s link.
- Context limit 327,680, 4 sequences, prefill chunk 8,192, priority scheduling, prompt-token details on.
- Upstream fixes adopted from the HeNryous patch series (0051 indexer defer, 0064 smoe split, 0067 fused VOR/SWA, 0075
  replay skip, 0085b idle cache release, 0091 vLLM fixes with the top-k fix), staged as one content-addressed overlay
  (`offload/upstream_all/`).
- KV page packing (`offload/kvpack/`, promoted by `offload/promote/k1/`) at the unchanged 327,680 limit.
- KV 6 GiB per rank: 46,603 blocks, 1,934,490 admissible tokens.

## Engram tables in x86 RAM

DeepSeek-V4.1's Engram layers (1 and 14) look up rows in large tables. Upstream reads them from the Sparks' NVMe. Here
an x86 server holds both tables in RAM (about 189 GiB, verified by sha256 when it loads, about 70 s) and answers row
requests over RDMA (`offload/engram/server/`, transport `offload/transport/`, the `ofl` library).

- Each Spark has its own link to the server; the client keeps the local NVMe reader as an exact fallback.
- `VLLM_ENGRAM_REMOTE_REQUIRED=0`: if the server is down, the serve boots and reads locally, then attaches when the
  server returns (retry every 5 s, 100 ms request timeout).
- Measured effect: cold TTFT 5.4 % / 5.7 % faster at 32K / 150K, outputs identical (2026-10-22).

## DSpark drafter on two RTX 3090s

The DSpark drafter (3 layers plus a Markov head) proposes tokens that the target verifies in one pass. Here it runs on
the x86 host (`offload/dspark/worker/`): EXL3 weights, tensor parallel over an NVLinked RTX 3090 pair, with its own
CUDA decode kernels adapted from exllamav3 and the donors in CREDITS.md.

- Rounds go over the same RDMA links (`o1rdma://`, 50 ms timeout).
- The worker's identity and the Markov head's identity are pinned by sha256 on the Spark side; a mismatched worker is refused.
- Capacity policy: no drafter on the Sparks at all, so its memory goes to KV.
- Sampled drafting with a fixed 5-token window (`offload/pp4_prod/`): the drafter proposes from its sampled top-32 and the
  target's verifier accepts or rejects them.
- If the worker is down, rounds fail closed to target-only decoding: the outputs are unchanged, only slower. Reconnects
  back off to at most 5 s.

## Async round proxy

A synchronous remote round makes rank 0 wait on the network. The async mode moves the remote round into a separate,
torch-free CPU process (`offload/dspark/spark/`) that exchanges flags with the engine through shared memory. A
watchdog respawns it up to 3 times per hour of service; after that, rounds are target-only. Measured: 3.9-6.5 % lower
step time than synchronous rounds, TTFT at parity, no watchdog fires (2026-10-23).

## Persistent prefix tier

The tier adds a secondary KV tier on each Spark's NVMe behind vLLM's offloading connector (patches 0100-0106). Its code
(`offload/prefixstore/`) follows in the next push, byte for byte as it runs ([why](publication.md#prefix-tier-code));
this commit carries the launcher glue, which serves without the tier when the tier's configuration is absent. It is
built so that one tenant's long documents never reach another:

- **Opt in.** A request is stored or read only when its `kv_transfer_params` carry a 64-hex namespace and
  `persist: true`. Untagged requests are never stored and bypass the connector entirely (patch 0106).
- **Isolation.** Each namespace has its own directory tree (mode 0700); lookups are keyed by namespace, so two
  namespaces never share a file or a lookup result, even for identical prompts.
- **Exclusions.** A hash-only exclusion file, pinned by sha256 in the engine config, lists namespaces that must never
  be stored or read.
- **Fail closed.** A missing, malformed, mismatched or loosely permissioned exclusion file, or an audit log that cannot be
  written, closes the gate: nothing is stored or read.
- **Audit and purge.** An append-only audit log records counts only (no names, no content); a namespace can be purged
  at once.
- **Bounds.** 64 GiB in total, 8 GiB per namespace, files unused for 30 days expire.
- **Integrity.** Every block has a CRC; a bad block is recomputed, never served.

Measured: a 150K prompt's first token in 2.58 s from the tier against 58.59 s cold (2026-10-30).

## What happens when something fails

| Failure | Effect | Recovery |
|-|-|-|
| x86 host down | Engram reads from local NVMe; drafting target-only; API keeps serving, slower | automatic reattach when the host returns |
| drafter worker restarts | target-only rounds | reconnect within 5 s of the worker being ready |
| async proxy dies or stalls | respawned, at most 3 per hour; then synchronous target-only | engine restart |
| prefix tier block corrupt | recomputed (`load_failed` counted) | none needed |
| exclusion file changed or unreadable | tier closed: nothing stored or read | engine restart with a valid file |

## Configuration

All of it is in [dsv41.env](../dsv41.env) and [serve.sh](../serve.sh); `start.sh` stages every overlay on both nodes,
verifies the staged bytes, starts both ranks and sends one warm-up request (the first request otherwise pays CUDA's
lazy module loads). Each `offload/*` component has a README with its own rollback.
