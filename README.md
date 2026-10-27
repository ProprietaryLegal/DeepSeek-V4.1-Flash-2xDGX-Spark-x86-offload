# DeepSeek-V4.1-Flash on two DGX Spark / GB10 nodes with x86 RTX 3090 offload

Keep the target on two DGX Spark nodes while an x86 host supplies Engram tables from RAM and speculative drafts from an RTX 3090. Spend the freed Spark memory on KV capacity, and use a separate CPU proxy process to overlap remote drafting with engine work. This overview links the independently usable code repositories and distinguishes deployed behavior from research candidates.

**Hugging Face:** [Card and files](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload) · **Collection:** [All entries](https://huggingface.co/collections/ProprietaryLegal/deepseek-v41-flash-on-2x-dgx-spark-x86-offload-6adab604a517b426ded3916e)

<!-- pli:blurb:start -->

> Published by [PLI Labs](https://proprietarylegal.ai/labs.html), the open research arm of [Proprietary Legal Intelligence](https://proprietarylegal.ai). PLI builds AI systems around a legal organization's own work product, combining retrieval, staged workflows, validation, and attorney review. Visit [proprietarylegal.ai](https://proprietarylegal.ai) to explore our work and discuss what your organization needs.

<!-- pli:blurb:end -->

<!-- pli:update:2026-10-27:start -->

**Update 2026-10-27:** the full DSV41 source is now public — [dsv41-offload](https://github.com/ProprietaryLegal/dsv41-offload) (every component; `production`, `main` and per-experiment `lane/*` branches), with focused repos for the [measurement harness](https://github.com/ProprietaryLegal/dsv41-window-harness) and [sampled drafting](https://github.com/ProprietaryLegal/dsv41-sampled-drafting). Status and lessons: [2026-10-27 post](https://github.com/ProprietaryLegal/pli-labs/blob/main/research/dgx-spark-offload/2026-10-27-status-and-code.md).

<!-- pli:update:2026-10-27:end -->


## Status

2026-10-23 — production: remote Engram, one-card remote EXL3 drafting, expanded KV, and async process handoff; the two-card NVLink worker is opt-in, with production promotion pending.

The one-card async switch passed startup, greedy-output, and watchdog checks. The two-card configuration passed supervised GB10 fault drills. Later independent review cleared its ownership/window fixes for integration; that clearance does not itself establish deployment. Native drafter fidelity, packed KV, larger context, prefix storage, prefill ordering, self-distillation, and further upstream adoption remain separately gated.

## What it is

The served target is the public [DeepSeek-V4.1-Flash-1017 EXL3 2.75 bpw legal-weighted build](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-LegalWeighted-DGX-Spark). It is a re-quantization, not a weight fine-tune. This release contains documentation and configuration examples; obtain implementation code from the standalone components below. No weights or private trajectories are bundled.

| component | placement | production role |
|---|---|---|
| target model, 40 layers | both GB10 nodes, tensor parallel | target verification, sampling and token generation |
| KV cache | both GB10 nodes | retains the extra capacity released by drafter offload |
| Engram tables, layers 1 and 14 | x86 host RAM, about 189 GiB resident | independent RDMA link to each Spark; local NVMe reader retained as fallback |
| EXL3 speculative drafter, three layers plus Markov head | one host RTX 3090 | capacity policy keeps the drafter off the Sparks |
| async proxy | separate CPU process on the engine host | torch-free remote round, shared-memory host flags, watchdog and bounded respawn |
| optional tensor-parallel drafter | NVLinked RTX 3090 pair | opt-in test variant; promotion pending |

### Component repositories

The standalone repositories are canonical. The older hub folders are snapshots. Every row has a GitHub source repository and a Hugging Face entry.

| component | GitHub | Hugging Face | status at source snapshot |
|---|---|---|---|
| Async host-flag handoff | [source](https://github.com/ProprietaryLegal/dsv41-async-hostflag-handoff) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-async-hostflag-handoff) | Production, one-card worker |
| Remote RTX 3090 drafter | [source](https://github.com/ProprietaryLegal/dsv41-remote-dspark-drafter-3090) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-remote-dspark-drafter-3090) | Production; capacity mode |
| NVLink two-card drafter | [source](https://github.com/ProprietaryLegal/dsv41-dspark-drafter-tp2-nvlink) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-dspark-drafter-tp2-nvlink) | Opt-in; GB10 measured and reviewed; promotion pending |
| Remote Engram | [source](https://github.com/ProprietaryLegal/dsv41-remote-engram-rdma) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-remote-engram-rdma) | Production; exact local fallback |
| ofl transport | [source](https://github.com/ProprietaryLegal/ofl-rdma-transport) | [entry](https://huggingface.co/ProprietaryLegal/ofl-rdma-transport) | Production |
| Native 1017 drafter | [source](https://github.com/ProprietaryLegal/dsv41-native-1017-drafter-sm86) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-native-1017-drafter-sm86) | Merged opt-in only; strict fidelity gate fails; not serving |
| KV page packing | [source](https://github.com/ProprietaryLegal/dsv41-kv-page-packing-1m) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-kv-page-packing-1m) | KV page packing validated on GB10 at 327,680 (production promotion pending); 524,288 serves correctly but is held for a prefill regression under investigation. 1M untested on GB10. |
| Long-context tools | [source](https://github.com/ProprietaryLegal/dsv41-longctx-bench-tools) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-longctx-bench-tools) | Measured benchmark tooling |
| Exact acceptance ceiling | [source](https://github.com/ProprietaryLegal/dsv41-exact-acceptance-ceiling) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-exact-acceptance-ceiling) | Research-only; method and aggregates |
| Full stack | [source](https://github.com/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload) | [entry](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload) | Production configuration overview |
| Findings | [source](https://github.com/ProprietaryLegal/dsv41-spark-offload-findings) | [entry](https://huggingface.co/ProprietaryLegal/dsv41-spark-offload-findings) | Research findings and limitations |

## Why

The capacity trade lets the target retain more simultaneous long contexts. Engram offload shortens long-prompt prefill; drafter offload releases memory. Synchronous remote drafting costs single-stream decode time because engine CPU preparation loses overlap. The process handoff recovers part of that cost while keeping prefill near the synchronous control.

## When to use it

Use this architecture when simultaneous long requests exceed the stock KV pool, host RAM and RDMA are available, and a separate GPU can draft. Components can also be deployed independently. Measure both first-token latency and whole-task time for your workload.

## When not to use it

It is a poor trade if short single-stream decoding is the only priority and the extra capacity is unused. The source snapshot does not qualify native drafting, prefix restoration, scheduler changes, or larger-context operation for production. A host failure preserves fallback service but reduces performance.

## Requirements

| item | tested configuration |
|---|---|
| serving nodes | two NVIDIA DGX Spark / GB10, 121 GiB unified memory each; TP2 over ConnectX-7 200 Gb/s fabric |
| offload host | x86 AMD EPYC 7302P, 16 cores / 32 threads, one NUMA node, 503 GiB RAM |
| host links | ConnectX-5 Ex, PCIe Gen4 x16, one 40 Gb/s DAC per Spark, MTU 9000, RoCE v2 |
| drafter GPUs | RTX 3090 24 GB; optional NV4 NVLink pair; 325 W cap per drafter card |
| serving software | `ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5`, vLLM `0.31.1.dev0+g6e517b15.dsv41gb10`, upstream patches 0022–0050; exllamav3 1.6.0 |
| production context/configuration | maximum length 327,680; four sequences; KV 6.0 GiB/rank; five draft tokens with batch-aware depth |

The upstream image is based on HeNryous revision `b1726644`; the tested launcher is based on sudoingX revision `cc59c36`. Our [image/offload fork](https://github.com/ProprietaryLegal/deepseek-v41-1017-dgx-spark) carries the offload implementation beside the image patch set. Our [launcher fork](https://github.com/ProprietaryLegal/dgx-spark-deepseek-v41) adds optional environment and read-only mount hooks, inert when unset. Configure actual addresses and GPU identifiers locally.

## Measured effect

Historical baseline suite, 2026-10-22: same target, two GB10 nodes and x86 RTX 3090 host; `T = 1`, `top_p = 1`, high thinking effort, fresh cache salts unless stated, 1,500-token budgets. A = stock local Engram/drafter; B = remote Engram; D = both offloads, synchronous one-card drafting and KV 6.0 GiB/rank. Cold summary rows below contain three observations each, including the cold priming request from the warm-cache test. They are historical synchronous results; the current async deployment has separate checks below. Means use sample standard deviation.

| metric / context | A stock | B Engram only | D synchronous offload | concurrency; repeats / scope |
|---|---|---|---|---|
| KV pool, tokens | 989,460 | 989,460 | 1,604,926 | allocation report; +62% capacity |
| short stream, tok/s | 55.96 ± 1.65 | — | 51.07 ± 0.78 | one; three repeats |
| 32K cold TTFT, s | 15.53 ± 0.12 | 14.70 ± 0.07 | 14.81 ± 0.54 | one; three cold observations, including priming |
| 32K cold stream, tok/s | 64.57 ± 0.80 | — | 60.82 ± 2.30 | one; three cold observations, including priming |
| 150K cold TTFT, s | 73.62 ± 0.11 | 69.44 ± 0.04 | 68.79 ± 0.14 | one; three cold observations, including priming |
| 150K task time, s | 100.35 ± 0.55 | 95.17 ± 1.61 | 96.46 ± 1.11 | one; three cold observations, including priming |
| 256K / 300K TTFT, s | — | — | 118.7 / 140.3 | one; one observation at each context |
| 256K / 300K stream, tok/s | — | — | 51.6 / 52.2 | one; one observation at each context |
| 32K aggregate, tok/s | 40.59 / 47.21 | — | 40.81 / 47.36 | two / three concurrent; two groups per configuration |
| 300K capacity | does not fit | does not fit | all four complete | four concurrent; one capacity drill |
| available memory per Spark, GiB | 5–7 | — | 5–8 | selected serving snapshots; not suite minima or memory guarantees |

In this suite, D improved TTFT by 4.6% at 32K and 6.6% at 150K, and completed the 150K task 3.9% sooner than A. Synchronous remote rounds still cost 3–9% single-stream decode speed. Engram alone improved TTFT by 5.4% / 5.7% at 32K / 150K; its decode effect was within spread. Offloading the drafter freed about 2.5 GiB of model load and 3–5 GiB available memory per rank before spending it on KV. Under concurrency the synchronous drafter penalty was at most 2% in the measured groups.

### Separate-process async handoff, 2026-10-23

Same hardware, target and budget; direct SSE-gap step timer, `T = 1`. The control is one-card synchronous D. The candidate is the two-card worker plus a napping process proxy with default lazy module loading. The synchronous control was already serving; the process-proxy engine started separately and ran one-card checks before this two-card set. Listed values are per-request step p50, not means of token throughput. The paired timings are shown directly; no aggregate percentage is inferred from them. Repetition counts are explicit in each row.

| workload; concurrency; repeats | synchronous one-card step, ms | two-card async step, ms |
|---|---|---|
| short; one; three requests | 39.6 / 40.1 / 39.4 | 37.1 / 37.4 / 36.9 |
| 32K; one; three requests | 41.2 / 42.2 / 42.3 | 39.6 / 39.5 / 40.2 |
| 32K; three concurrent; one group | 75.9 / 76.1 / 76.1 | 72.8 / 73.5 / 73.0 |
| 150K; one; two requests | 41.5 / 42.2 | 39.6 / 39.8 |
| 32K / 150K TTFT; one; three / two requests | 14.56–14.59 / 69.10–69.11 s | 14.49–14.63 / 68.89–69.09 s |
| serving drafter memory; same suite snapshots | one card ~8.1 GiB | 5,862 + 5,222 MiB |

Host-memory RDMA probes on 2026-10-22 used 64 MiB transfers over the same host links. These link probes do not measure inference throughput.

| link scope | measured bandwidth | repetitions / scope |
|---|---|---|
| one link | about 39.2 Gb/s | iteration-count read/write probes; not a repeat-run mean |
| both links simultaneously | 78.38 Gb/s aggregate | four read/write direction cases, overlapping three-second windows |

The one-card process proxy also lowered step p50 on each matched workload against the synchronous control. Two cards alone with synchronous rounds showed smaller step-time reductions than the combined async variant in both synchronous comparison sets. Nap and spin process variants were within run-to-run noise. The merged, hardened runtime repeated the performance without a measurable cost.

| additional check, 2026-10-23; same two-GB10 / x86 hardware | observation | conditions / repeats |
|---|---|---|
| two-card async, 32K four concurrent | 51.7 tok/s overall; about 119 tok/s combined decode; step p50 87.1–88.2 ms | one four-request group; overall includes prefill, decode estimate sums stream rates |
| stream speed in initial async A/B | 32K 57.6 → 62.2 tok/s; 150K 51.0 → 54.4 tok/s | one concurrent; means of three / two runs; acceptance-sensitive |
| production one-card async startup | ready in 363 s; short TTFT 0.37 / 0.38 s; short step 38.4 / 38.5 ms | one restart; two short checks |
| production one-card async, 32K | first TTFT 16.24 s versus about 14.5 s warm; step 40.5 ms | one first-long-request check; lazy-load cost remains |
| production greedy output check | 6/6 identical | fixed prompts; temperature zero, thinking off; pre-switch reference |
| production steady counters | 2,048 rounds OK; zero failed; zero watchdog fires | one post-switch snapshot, not a long-term reliability bound |

The standalone component cards carry the detailed fault-drill and boundary-exactness evidence. Acceptance changes stochastically between runs, so direct step timing is the primary runtime comparison. Do not add the isolated percentages together or describe a per-round change as an equal whole-task improvement.

## Upstream claims

HeNryous reports restoring a 75K prefix across a restart in 1.3–2.1 s versus 33.8 s. That is an upstream result, not our prefix-store measurement. Its applicability to this offload stack still needs engine tests. See the [upstream image fork](https://github.com/ProprietaryLegal/deepseek-v41-1017-dgx-spark).

DeepSeek documents model support for 1,048,576 positions. Our larger-context GB10 correctness tests are pending. Upstream KV-packing or kernel speed claims do not substitute for measured performance here.

## Deploy

Follow the [launcher fork](https://github.com/ProprietaryLegal/dgx-spark-deepseek-v41) for the two-node image setup, then install each standalone component in this order:

1. Run the stock target and establish a cold-cache, fixed-settings baseline. Record target and tokenizer identities, image and source versions, cache allocation and sampling settings.
2. Build the [ofl transport](https://github.com/ProprietaryLegal/ofl-rdma-transport) for the host and Spark architectures. Qualify each host link and exact Engram rows before enabling [remote Engram](https://github.com/ProprietaryLegal/dsv41-remote-engram-rdma). Keep local disk fallback.
3. Install the matching [remote drafter worker and Spark overlay](https://github.com/ProprietaryLegal/dsv41-remote-dspark-drafter-3090). Match drafter and Markov identities. Verify shadow parity, then select capacity mode before raising KV.
4. Start from the [sanitized historical D configuration](config/production-D.env.example), replacing all placeholders. Apply the [async delta](config/production-async.env.example) using the [handoff component procedure](https://github.com/ProprietaryLegal/dsv41-async-hostflag-handoff). It requires the host-flag helper built for GB10, matching read-only mounts, and the full process-proxy package.
5. Confirm async self-test, successful memory locking, a separate torch-free process, worker identity/connection, fresh watchdog and fallback counters, and the expected KV pool. Warm short and long-prefill paths. Re-run matched cold/warm, concurrent and long-context checks before accepting the capacity trade.
6. Treat the [NVLink worker](https://github.com/ProprietaryLegal/dsv41-dspark-drafter-tp2-nvlink) as a separate change with pair safety, owned capture streams, prebuilt peer extension, lifetime GPU locks, supervised fault drills and rollback rehearsal.

These examples are not a one-command installer. The older component staging scripts retain assumptions about their original directory layout and pinned build locations; adapt and verify those explicitly. Use the [benchmark tools](https://github.com/ProprietaryLegal/dsv41-longctx-bench-tools) with your own prompts; this release excludes benchmark inputs and raw output rows.

## Rollback

| change to remove | persistent configuration change, then engine restart | resulting behavior |
|---|---|---|
| async handoff | unset `VLLM_DSPARK_REMOTE_ASYNC` on both ranks | synchronous remote rounds |
| two-card worker | replace the pair worker with the known-good one-card worker, preserving identities | same protocol; reconnect after worker readiness |
| remote drafter | remove remote drafter environment and overlay mounts; restore KV to 3.75 GiB/rank before local drafting | local drafter with the baseline cache budget |
| remote Engram | remove remote Engram endpoint and overlay environment | local NVMe Engram reader |

Changing a shell variable alone does not reconfigure the running engine. Keep the worker GPU hold until in-window compute has ended. If the host is unavailable, Engram falls back to disk and drafting fails closed to target-only decoding; this preserves requests at reduced performance. Capacity mode does not recreate a local drafter automatically.

## Limits and known issues

- The combined package is an overview and configuration index. Implementation trees live in the standalone repositories; the historical hub folders are snapshots.
- The first long request after restart can still pay lazy-loading cost despite a short warm-up. Production counters cover a bounded check, not extended availability.
- KV page packing validated on GB10 at 327,680 (production promotion pending); 524,288 serves correctly but is held for a prefill regression under investigation. 1M untested on GB10.
- Prefix storage: cleared for gated GB10 testing only.
- Prefill ordering: an independent check found a scheduler liveness bug; it is fixed (45 CPU tests) and under a second independent check.
- Native drafter fidelity: online-block attention and FP32 head corrections are implemented in a development candidate, but the strict stage-zero attention gate still fails. Historical speed figures predate that correction and are not a qualified gain for the corrected worker.
- Drafter self-distillation: a fast training path is built, but it does not yet match the exact reference math closely enough, so it is not used for training yet.
- Further upstream adoption is offline, opt-in work: target MoE row splitting, replay/upload changes, Engram lookahead, and separate configuration candidates. It has no GB10 performance qualification and should be tested independently before combination.
- One x86 host is a shared performance dependency. Recovery and target-only behavior must be tested under your own operational constraints.

## Repository layout

| path / repository | purpose |
|---|---|
| [README.md](README.md) | architecture, evidence and component index |
| [config/production-D.env.example](config/production-D.env.example) | historical synchronous D settings with placeholders |
| [config/production-async.env.example](config/production-async.env.example) | persistent async process-proxy delta |
| [NOTICE](NOTICE) | licence and distribution boundary |
| [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt) | complete licence for the overview and configuration examples |
| standalone components above | Engram server/overlay, transport, Spark handoff, one/two-card worker, native research kernels, benchmarks and analysis |

There is no combined `code/` tree in this package. Use each component's code map and tests from its own repository.

## Tests

Run CPU suites from each standalone component root, using its documented environment:

```bash
# Async handoff or remote-drafter entry:
PYTHONPATH=code/dspark/spark python3 -B -m pytest -q -p no:cacheprovider code/dspark/spark/tests
# Two-card worker entry (GPU tests skip on a CPU-only machine):
PYTHONPATH=code/dspark/worker python3 -B -m pytest -q -p no:cacheprovider code/dspark/worker/tests --ignore=code/dspark/worker/tests/test_fused.py
# Benchmark entry:
python3 -B -m pytest -q -p no:cacheprovider code/bench/test_bench2.py code/bench/test_s1_links.py
```

Recorded publication-copy checks on 2026-10-23: Spark suite 221 passed / 2 skipped; worker suite 64 passed / 40 skipped, with the fused GPU suite excluded. Earlier publication checks recorded Spark 167 passed / 2 skipped, worker 39 passed, TP2 29 passed and benchmark 20 passed. These describe different snapshots and test scopes, not one combined test count. The current combined package has no executable CPU suite. See each component for its latest count and required contract file; passing CPU checks does not qualify GB10 deployment.

## Credits and licences

PLI Labs integration and analysis code is Apache-2.0. Credits: DeepSeek for the [target and drafter](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017); HeNryous for the Spark image, patches and EXL3 build; sudoingX for the two-node recipe; turboderp for [exllamav3](https://github.com/turboderp-org/exllamav3); [vLLM](https://github.com/vllm-project/vllm) for the serving engine. Upstream software and model weights retain their own licences. The native-kernel repository includes component-specific attributions; consult its NOTICE and licence files before redistribution.

## Related

- `dsv41-async-hostflag-handoff`: [GitHub](https://github.com/ProprietaryLegal/dsv41-async-hostflag-handoff) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-async-hostflag-handoff).
- `dsv41-remote-dspark-drafter-3090`: [GitHub](https://github.com/ProprietaryLegal/dsv41-remote-dspark-drafter-3090) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-remote-dspark-drafter-3090).
- `dsv41-dspark-drafter-tp2-nvlink`: [GitHub](https://github.com/ProprietaryLegal/dsv41-dspark-drafter-tp2-nvlink) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-dspark-drafter-tp2-nvlink).
- `dsv41-remote-engram-rdma`: [GitHub](https://github.com/ProprietaryLegal/dsv41-remote-engram-rdma) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-remote-engram-rdma).
- `ofl-rdma-transport`: [GitHub](https://github.com/ProprietaryLegal/ofl-rdma-transport) · [Hugging Face](https://huggingface.co/ProprietaryLegal/ofl-rdma-transport).
- `dsv41-native-1017-drafter-sm86`: [GitHub](https://github.com/ProprietaryLegal/dsv41-native-1017-drafter-sm86) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-native-1017-drafter-sm86).
- `dsv41-longctx-bench-tools`: [GitHub](https://github.com/ProprietaryLegal/dsv41-longctx-bench-tools) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-longctx-bench-tools).
- `dsv41-exact-acceptance-ceiling`: [GitHub](https://github.com/ProprietaryLegal/dsv41-exact-acceptance-ceiling) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-exact-acceptance-ceiling).
- `DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload`: [GitHub](https://github.com/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload) · [Hugging Face](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload).
- `dsv41-spark-offload-findings`: [GitHub](https://github.com/ProprietaryLegal/dsv41-spark-offload-findings) · [Hugging Face](https://huggingface.co/ProprietaryLegal/dsv41-spark-offload-findings).

Upstream forks: [Spark image and offload integration](https://github.com/ProprietaryLegal/deepseek-v41-1017-dgx-spark) · [two-node launcher](https://github.com/ProprietaryLegal/dgx-spark-deepseek-v41). [HF collection](https://huggingface.co/collections/ProprietaryLegal/deepseek-v41-flash-on-2x-dgx-spark-x86-offload-6adab604a517b426ded3916e) · [hub snapshot](https://github.com/ProprietaryLegal/pli-labs/tree/main/research/dgx-spark-offload).

<!-- pli:footer:start -->

---

## About PLI Labs

“Your proprietary work product is your proprietary intelligence.” PLI Labs is the open research arm of Proprietary Legal Intelligence. We publish legal model prunes, serving recipes for owned hardware, and open-source tools so readers can inspect our methods and test our claims before hiring us.

Founded by a practicing trial lawyer, PLI builds AI systems around a legal organization's own work product: retrieval, staged workflows, validation, and attorney review. The approach grew from systems running on live matters in a litigation practice. Our consulting work supports deployment through approved frontier APIs, private cloud, or open-weight models on hardware you own. Explore the research or contact us about your organization's work.

[Website](https://proprietarylegal.ai) · [PLI Labs](https://proprietarylegal.ai/labs.html) · [Research](https://proprietarylegal.ai/research/index.html) · [GitHub](https://github.com/ProprietaryLegal) · [Hugging Face](https://huggingface.co/ProprietaryLegal) · [Contact](https://proprietarylegal.ai/contact.html)

Proprietary Legal Intelligence LLC is a technology consultancy, not a law firm, and does not provide legal services or legal advice.

<!-- pli:footer:end -->
