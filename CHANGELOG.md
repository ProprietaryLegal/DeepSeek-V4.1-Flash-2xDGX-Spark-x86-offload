# Changelog

Dates are UTC. "Production" is the commit serving on our two Sparks at the time.

## 2026-10-31: flagship repository

- MEASURED: MiaAI's sparkDash protocol on production `ebc29ed8` (2,300 MHz cap, drafter GPUs at 400 W, 4 sequences, 3
  repeats): prefill 2,606-2,827 tok/s from 4K to 256K; code 110.5 / 192.0 tok/s at 1 / 4 streams; structured 138.3 /
  322.1; prose 66.0 / 130.1; thinking prose 55.9 / 105.3; decode after 128K 61.9; short chat behind a cold 93K prompt
  34.3 s. Raw file in `runs/`, tables in `docs/measurements.md`.
- New `tools/sparkbench.py`, a Python re-implementation of the sparkDash protocol (credited in CREDITS.md).
- README: quality section first (KLD and top-1 against the original model, with both the served weights and HeNryous's),
  a head-to-head with MiaAI-Lab and bertholomus that lists our losses, and a table of other two-Spark builds.
- Corrected: earlier text called the served weights a re-quantization of our own without saying how little of
  HeNryous's build it changes; the README now names HeNryous's weights next to every quality number.
- This repository now carries the full production tree (exported from production `ebc29ed8`), not only an overview and
  configuration examples. The previous README and `config/*.env.example` files are replaced by the real `dsv41.env`,
  `serve.sh` and launcher scripts.
- New `tools/bench.py`: MiaAI-conditions and our-conditions profiles, synthetic prompts, JSON output, `compare` mode;
  `tools/node_watch.py` and `tools/fake_server.py`, with CPU tests.
- New `docs/measurements.md`, `docs/comparison.md`, `docs/architecture.md`, `docs/operations.md`, `CREDITS.md`,
  issue and pull-request templates.
- New `docs/install.md`: the full build in order (cabling, the image by digest, launcher, weights, the x86 host's
  drafter and Engram files and services, `dsv41.env`, first start, checks). README: hero numbers, server limits and
  memory table.
- Not in this commit: the persistent prefix tier's code (`offload/prefixstore/` except the launcher glue). Three of its
  overlay files need a source-side fix and new pins before they can be published byte for byte; it follows in the next
  push. Its measurements are published now. See `docs/publication.md`.

## 2026-10-30: persistent prefix tier bounds raised (production `ebc29ed8`)

- Tier bounds 64 GiB total, 8 GiB per namespace, 30-day expiry.
- MEASURED: 150K prompt TTFT 2.58 s from the tier against 58.59 s cold (6 trials).

## 2026-10-29 to 2026-10-30: persistent prefix tier

- Opt-in per-namespace KV tier on the Sparks' NVMe (patches 0100-0106); untagged requests bypass it.

## 2026-10-28 to 2026-10-29: PP4 sampled drafting

- The drafter proposes from its sampled top-32 with a fixed 5-token window; verifier changes in `offload/pp4_prod/`.

## 2026-10-28: upstream install (production `a0006fc`)

- HeNryous patches 0051, 0064, 0067, 0075, 0085b, 0091; dual RDMA ring; 5 drafts at 3-4 streams; prefill chunk 8192;
  CPU pinning; GPU clock cap 2,300 MHz.
- MEASURED: prompt reading 14-20 % faster in every cell; decode 8 % faster at 4 streams and 24-28 % faster while a
  long prompt is read; single-stream decode unchanged within noise.

## 2026-10-23 to 2026-10-27

- Async round proxy and the two-card NVLink drafter worker in production; KV page packing at 327,680 tokens.
- 2026-10-27: the source of every component published in [dsv41-offload](https://github.com/ProprietaryLegal/dsv41-offload).

## 2026-10-22: offload configurations B and D

- B: Engram tables from x86 RAM over RDMA. D: the drafter on an x86 RTX 3090, freed memory spent on KV (+62 % tokens).

## 2026-10-21

- Served weights switched to the 2.75 bpw legal-weighted re-quantization.
