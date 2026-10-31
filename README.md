# DeepSeek-V4.1-Flash on two DGX Sparks with an x86 offload host

[![proprietarylegal.ai](https://img.shields.io/badge/proprietarylegal.ai-website-0B3D91)](https://proprietarylegal.ai) [![PLI Labs](https://img.shields.io/badge/PLI%20Labs-research-1F6FEB)](https://proprietarylegal.ai/labs.html) [![Hugging Face](https://img.shields.io/badge/Hugging%20Face-card-FFD21E)](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE) [![Hardware: 2x DGX Spark + x86](https://img.shields.io/badge/hardware-2x%20DGX%20Spark%20%2B%20x86%20offload-76B900)](#requirements) [![Raw data: runs/](https://img.shields.io/badge/raw%20data-runs%2F-555555)](runs/)

Built by **Nick Mermiges, Esq.**, founder of [PLI Labs](https://proprietarylegal.ai/labs.html) · [proprietarylegal.ai](https://proprietarylegal.ai)

DeepSeek-V4.1-Flash-1017 (EXL3, 2.75 bpw) served by vLLM across two NVIDIA DGX Spark / GB10 nodes in tensor parallel. A third,
ordinary x86 machine does two jobs for them: it holds the Engram tables in RAM and serves them over RDMA, and it runs the
DSpark speculative drafter on a pair of RTX 3090s. The memory this frees on the Sparks goes to KV cache, a pool of 1,934,490
tokens. A persistent prefix tier on the Sparks' NVMe lets a long prompt be read back after a restart instead of prefilled
again.

<table>
<tr>
<td align="center"><h2>2,606&#8209;2,827</h2>tok/s prefill<br><sub>4K to 256K-token prompts; MiaAI 2,065&#8209;2,155</sub></td>
<td align="center"><h2>322</h2>tok/s structured output<br><sub>4 streams; 138 at one</sub></td>
<td align="center"><h2>192</h2>tok/s code<br><sub>4 streams; MiaAI 166.1, same protocol</sub></td>
<td align="center"><h2>95.9&nbsp;%</h2>top-1 agreement with the original<br><sub>real tool-call turns, KLD 0.018</sub></td>
</tr>
</table>

<sub>sparkDash protocol re-implemented in <a href="tools/sparkbench.py">tools/sparkbench.py</a>, production commit <code>ebc29ed8</code>, 2026-10-31, both Sparks at a 2,300 MHz clock cap, 3 repeats, median. Raw file: <a href="runs/2026-10-31-sparkdash-protocol-ebc29ed8.json">runs/</a>. Quality: sudoingX's <code>p4_kld.py</code> panel, agentic domain.</sub>

- **95.9 % top-1 agreement with the original model on real tool-call turns** (KLD 0.018; weights by HeNryous). bertholomus publishes 79.4 % on its own tool-call set; MiaAI publishes none.
  <sub>p4_kld, sudoingX's panel, agentic domain, 2026-10-21 · [quality](#quality)</sub>
- **Prefill 2,606-2,827 tok/s from 4K to 256K tokens**: faster than MiaAI and bertholomus at every prompt size they publish. A 256K prompt's first token in 100 s (MiaAI 127 s).
  <sub>sparkDash protocol, 2,300 MHz, commit `ebc29ed8`, 2026-10-31 · [prefill ladder](docs/measurements.md#prefill-ladder)</sub>
- **322 tok/s of structured output at 4 streams**, 138 tok/s at one.
  <sub>sparkDash "structured" prompt, T=0, 400 tokens, 3 reps · [decode cells](docs/measurements.md#decode-cells-sparkdash)</sub>
- **192 tok/s of code at 4 streams** (MiaAI 166.1 on the same protocol).
  <sub>sparkDash code prompts, T=0, thinking off, 400 tokens, 3 reps · [decode cells](docs/measurements.md#decode-cells-sparkdash)</sub>
- **Long prompts survive a restart**: a 150K-token prompt comes back from the NVMe tier in 2.58 s instead of 58.6 s of
  prefill; in production, the first request after a restart read 95.1 % of its 107,821-token prompt from the tier.
  The tier's code follows in the next push ([why](docs/publication.md#prefix-tier-code)); the measurements are here now.
  <sub>2026-10-30 test store, 6 trials; 2026-10-31 production counts · [prefix tier](docs/measurements.md#persistent-prefix-tier-2026-10-30-and-2026-10-31-production-ebc29ed8)</sub>

We also lose on several rows, and the [head-to-head](#head-to-head) lists them: prose and thinking-mode decode, decode
after a 128K prompt, a short request behind a long prompt, streams beyond 4, and contexts beyond 327,680.

**Image:** `ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5` (linux/arm64,
`sha256:8fc2c99a3562e99d81d2a05b8345d12726def0a027410d14d0eb0763de8309e4`), unmodified; `start.sh` stages our overlays
from this checkout and mounts them read-only. **Install:** [docs/install.md](docs/install.md), step by step. **Numbers:**
[docs/measurements.md](docs/measurements.md). **Raw data:** [runs/](runs/).

This repository is the serving stack as it runs in production, with every number we measured on it, the tools that
measured them, the raw result files and the code for every piece except the prefix tier, which follows in the next
push. Issues, measurements on your own hardware and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

**Hugging Face:** [card](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload) ·
[served weights](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-LegalWeighted-DGX-Spark) ·
[collection](https://huggingface.co/collections/ProprietaryLegal/deepseek-v41-flash-on-2x-dgx-spark-x86-offload-6adab604a517b426ded3916e)
· **Research archive:** [dsv41-offload](https://github.com/ProprietaryLegal/dsv41-offload) (every experiment branch)

<!-- pli:blurb:start -->

> Published by [PLI Labs](https://proprietarylegal.ai/labs.html), the open research arm of [Proprietary Legal Intelligence](https://proprietarylegal.ai). PLI builds AI systems around a legal organization's own work product, combining retrieval, staged workflows, validation, and attorney review. Visit [proprietarylegal.ai](https://proprietarylegal.ai) to explore our work and discuss what your organization needs.

<!-- pli:blurb:end -->

## Quality

How closely the quantized weights follow the original DeepSeek-V4.1-Flash-1017, measured with sudoingX's `p4_kld.py`
(DeepSeek's reference implementation run over the original checkpoint and over the quant, teacher-forced on the same
tokens). KLD is KL(original || quant), lower is better; top-1 is the share of positions where both pick the same token.
The weights are **HeNryous's** 2.75 bpw EXL3 build; we serve a legal-weighted allocation of it that re-encodes 1,414 of
its 15,360 routed experts at the same total size, and both columns are shown.

| Test (scored assistant positions) | Served: legal-weighted allocation | [HeNryous 2.75 bpw](https://huggingface.co/HeNryous/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark) `86f85253` |
|-|-|-|
| **real tool-call turns**: sudoingX's general panel, agentic domain (24 multi-turn conversations with tool definitions, calls and results) | 0.0184 / **95.88 %** | 0.0183 / **95.91 %** |
| sudoingX's general panel, all 199 conversations, 8 domains | 0.0204 / 95.91 % | 0.0201 / 95.96 % |
| our legal panel, 210 sequences (replies sampled from a quant, which favours quants slightly) | 0.0303 / 96.85 % | 0.0329 / 96.70 % |

What the other builds publish, on their own test sets (not directly comparable with the rows above):

| Build | Tool-call turns | General text |
|-|-|-|
| [bertholomus](https://huggingface.co/bertholomus/DeepSeek-V4.1-Flash-1017-EXL3-2.5bpw), EXL3 2.52 bpw | KL 0.5948 / 79.43 % (own set, full vocabulary) | short rows 0.1305 / 92.01 % |
| [MiaAI-Lab](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks), EAQ v1.1 2.9 bpw | not published | not published (indexer-selection agreement 403,560 of 403,560 rows) |
| [sudoingX](https://github.com/sudoingX/dgx-spark-deepseek-v41) v2.0, EXL3 2.8 bpw | KLD **0.0175** on the same panel as ours, closer than ours | 0.0198 / 95.94 %, same panel |

Our KLD keeps the original's top-128 tokens plus a tail bucket, so it is a lower bound; bertholomus scores the full
vocabulary. A same-test run of bertholomus's and MiaAI's weights on our panels is in progress; until then the
[same-test table](docs/measurements.md#quality-kl-divergence-against-the-original-model) says "pending". These numbers
measure the weights. Speculative decoding does not change them at temperature 0 as far as the engine's identity tests
show, and we claim nothing beyond those tests.

## Head-to-head

Three builds of DeepSeek-V4.1-Flash-1017 on two DGX Sparks, every metric any of them publishes. **Same protocol** means
our number was measured with the protocol that produced theirs: MiaAI's numbers come from its
[sparkDash](https://github.com/MiaAI-Lab/sparkDash) dashboard, ours from [tools/sparkbench.py](tools/sparkbench.py), a
re-implementation of sparkDash `b96244a2`. bertholomus uses its own prompt sets, so its decode rows are **not
comparable** with either.

Our conditions for every row: production `ebc29ed8`, 2026-10-31, both Sparks at a 2,300 MHz clock cap, drafter GPUs at a
400 W cap (325 W in production; they drew 22-112 W in the samples taken), `max-num-seqs` 4, 3 repeats, median.

| Metric | **This repository** | [MiaAI-Lab](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks) | [bertholomus](https://huggingface.co/bertholomus/DeepSeek-V4.1-Flash-TensorFold-TP2-2xGB10) v0.7.3 | Basis |
|-|-|-|-|-|
| engine, weights | vLLM 0.31.1.dev0 + overlays, EXL3 2.75 bpw | TensorFold, EAQ 2.9 bpw | TensorFold, EXL3 2.52 bpw (~185 GB) | |
| extra hardware | x86 host, 2 x RTX 3090 | none | none | |
| GPU clock cap | 2,300 MHz | 2,200 MHz | not stated | |
| prefill 4K / 8K / 16K | **2,827 / 2,813 / 2,606** | 2,106 / 2,152 / 2,155 | - / 2,439 / - | same protocol with MiaAI |
| prefill 32K / 64K / 128K / 256K | **2,667 / 2,641 / 2,650 / 2,618** | 2,154 / 2,136 / 2,077 / 2,065 | 2,568 / 2,550 / 2,523 / - | same protocol with MiaAI |
| 256K prompt, first token | **100.4 s** | 127.1 s | - | same protocol |
| code T=0, 1 / 2 / 3 / 4 streams, total | 110.5 / 147.9 / **174.8 / 192.0** | **118.1 / 149.4** / 171.0 / 166.1 | 1 stream 112.7 (set b, 384 tokens) | same protocol with MiaAI |
| prose T=0, 1 / 2 / 3 / 4 streams, total | 66.0 / 90.5 / 112.4 / 130.1 | **80.7 / 110.6 / 133.6 / 154.0** | 1 stream 67.5 (set b) | same protocol with MiaAI |
| prose T=0.7 thinking on, 1-4 streams | 55.9 / 72.0 / 90.8 / 105.3 | **63.9 / 93.3 / 107.8 / 120.6** | not published | same protocol |
| structured T=0, 1 / 4 streams | 138.3 / **322.1** | not published | 1 stream **159.5** (set b) | not comparable |
| 4 streams, mixed set, total | prose 130.1, code 192.0 | see above | 134.0 (set b) | not comparable |
| 8 streams | not supported (4 max) | not published | **168.3** sustained | |
| TTFT, 1 stream: prose / code / thinking | 146 / 215 / 221 ms | **133 / 213 / 214 ms** | - | same protocol |
| decode after a 128K prompt, 1 stream | 61.9 (sparkDash prose) | not published | **99.2** (median of 3 own prompts) | not comparable |
| short chat behind a cold 93K prompt, first token | 34.3 s | **3.84 s** (different test: 8 s into a 70K prompt) | 38.6 s | same design with bertholomus |
| longest context per request | 327,680 | 524,288 | **1,048,576** | |
| tool-call turns, top-1 vs original | **95.9 %** | not published | 79.4 % | different test sets |

**Where we lose.** Prose decode at T=0 is 18 % behind MiaAI at one stream (66.0 against 80.7) and 16 % at four;
thinking-mode prose is 12-23 % behind; code is 6 % behind at one stream and 1 % behind at two. Decode after a 128K prompt is
far below bertholomus's figure (different prompts, but the gap is large). On prose the drafter has 2.1-2.3 of its 5
drafted tokens accepted per round, against 4.2-4.5 on code and 4.96 on structured output
([decode cells](docs/measurements.md#decode-cells-sparkdash)). A short request sent behind a long cold prompt
gets its first token only when the long prefill is almost done (34 s against 35 s for the long prompt); MiaAI's engine
lets such a request in early. We serve at
most 4 streams and 327,680 tokens; bertholomus serves 8 streams and 1M tokens. We have not run 1M context.

**Where we win.** Prefill at every size from 4K to 256K, by 21-34 % over MiaAI and 4-15 % over bertholomus at the sizes
each publishes (even our uncorrected prompt / TTFT rates are higher). Code at 3 and 4 streams (+2 % and +16 % over MiaAI).
Tool-call fidelity against bertholomus, the other build here that publishes it, with the caveat that the test sets
differ; sudoingX's 2.8 bpw pack is slightly closer than ours on our own panel. Structured output reaches 322 tok/s at 4
streams, a row neither other build publishes.

Every cell, every repeat, TTFT, acceptance per draft round, deep-context decode and the clock and temperature log:
[docs/measurements.md](docs/measurements.md#sparkdash-protocol-2026-10-31). The raw file:
[runs/2026-10-31-sparkdash-protocol-ebc29ed8.json](runs/2026-10-31-sparkdash-protocol-ebc29ed8.json). Sources and
conditions for every other build's number: [docs/comparison.md](docs/comparison.md).

## Other 2x DGX Spark builds

Popular public builds of DeepSeek-V4-Flash and V4.1-Flash on DGX Sparks, with GitHub stars as of 2026-10-31. Their
numbers are their own, under their own conditions. **Same-protocol run pending** for every row below: we are porting
each build's benchmark into `tools/sparkbench.py` and will publish the results in [runs/](runs/).

| Repository | Stars | Model | Engine, weights | What it publishes |
|-|-|-|-|-|
| [MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark) | 1,505 | V4-Flash | vLLM, DSpark | earlier model |
| [tonyd2wild/DeepSeek-v4-Flash-Vision-Exp-DSpark-1M-NVFP4-KV-2x-DGX-Spark](https://github.com/tonyd2wild/DeepSeek-v4-Flash-Vision-Exp-DSpark-1M-NVFP4-KV-2x-DGX-Spark) | 494 | V4-Flash | vLLM, DSpark, NVFP4 KV, 1M | earlier model |
| [MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks) | 372 | V4.1-Flash-1017 | TensorFold, EAQ 2.9 bpw | compared above, same protocol |
| [MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks) | 281 | V4.1-Flash | 3-4 Sparks | |
| [MiaAI-Lab/DeepSeek-v4.1-Flash-EXL3-2x-DGX-Sparks](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-EXL3-2x-DGX-Sparks) | 280 | V4.1-Flash | vLLM, EXL3 2.9 bpw | 1 stream at T=0: 40.2 tok/s |
| [tonyd2wild/DeepSeek-V4.1-Flash-TP2-and-TP4-DGX-Sparks](https://github.com/tonyd2wild/DeepSeek-V4.1-Flash-TP2-and-TP4-DGX-Sparks) | 154 | V4.1-Flash-1017 | TensorFold, EXL3 2.9 bpw | 73.1 tok/s at 1 user, 135.8 at 4 (8 categories), 1M |
| [0xSero/DeepSeek-V4.1-Flash-Two-Sparks](https://github.com/0xSero/DeepSeek-V4.1-Flash-Two-Sparks) | 95 | V4.1-Flash | vLLM, EXL3 2.77 bpw | prefill 8K 2,050, 32K 2,061; code 1 stream ~39-41; 262,144 context |
| [bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10) | 58 | V4.1-Flash-1017 | TensorFold, EXL3 2.52 bpw | compared above |
| [sudoingX/dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41) | 45 | V4.1-Flash-1017 | vLLM, EXL3 2.8 bpw | set b code / prose / structured 103.7 / 57.8 / 144.4; KLD 0.0198 |
| [elsung/dgx-spark-deepseek-v4-flash](https://github.com/elsung/dgx-spark-deepseek-v4-flash) | 30 | V4-Flash | vLLM, FP8 | ~41 tok/s 1 stream, ~350 aggregate at 32 |
| [r0b0tlab/deepseek-v4-flash-nvfp4-gb10-benchmark](https://github.com/r0b0tlab/deepseek-v4-flash-nvfp4-gb10-benchmark) | 13 | V4-Flash | vLLM | 38.4 tok/s 1 stream, 144.6 aggregate at 16 |
| [HeNryous/deepseek-v41-1017-dgx-spark](https://github.com/HeNryous/deepseek-v41-1017-dgx-spark) | 6 | V4.1-Flash-1017 | vLLM image v5 (ours), EXL3 2.75 bpw | prose 56.6, code 88.9 (T=1, 2,400 MHz) |
| [hisxo/DeepSeek-V4.1-Flash-2x-DGX-Spark](https://github.com/hisxo/DeepSeek-V4.1-Flash-2x-DGX-Spark) | 1 | V4.1-Flash | TensorFold (patched), EXL3 2.9 bpw | 1 stream code / prose / structured 113.4 / 69.3 / 145.1 |
| [ZackO2o/DeepSeek-V4.1-Flash-TensorFold-DGXSpark-TP2](https://github.com/ZackO2o/DeepSeek-V4.1-Flash-TensorFold-DGXSpark-TP2) | 1 | V4.1-Flash | TensorFold | code 81.8 tok/s 1 stream, 150.5 aggregate at 4 |

Builds that serve more streams (8-32) need a larger `max-num-seqs` than our production uses; those rows will be run in a
separate configuration and labelled as such.

## Reproduce

```bash
# MiaAI's sparkDash protocol (decode 1-4 streams, prefill 4K-256K), plus our deep-context and short-behind-long tests
python3 -I tools/sparkbench.py --url http://<head>:8000 --out runs/my-sparks.json --reps 3 \
    --suites prose-t0,code-t0,structured-t0,prose-t07-think,prose-t1-think,prefill \
    --deep 32768:1,32768:4,131072:1 --interference 2
# our own cells (T=1, thinking on, 512 tokens, synthetic records) and a MiaAI-conditions profile
python3 -I tools/bench.py plan --profile all
python3 -I tools/bench.py run --profile all --url http://<head>:8000 --exact-size \
    --label my-sparks --note "clock 2300, commit ..." --out runs/my-sparks-bench.json
```

Both tools use only the Python standard library and talk to any OpenAI-compatible server. Lock the GPU clock first
(`sudo nvidia-smi -lgc 0,2300` on both Sparks) and record it with the result; `tools/node_watch.py` logs clocks,
temperatures and free memory during a run. Please send results as a
[performance report](https://github.com/ProprietaryLegal/DeepSeek-V4.1-Flash-2xDGX-Spark-x86-offload/issues/new?template=performance_report.yml).

## Our own cells: long legal prompts at T=1, thinking on

The sparkDash numbers above use short prompts at temperature 0. Our production work is long documents with thinking on,
which is the hardest case for a drafter. These cells are measured with temperature 1 (seed 42 + repeat), thinking on
(effort `high`), exactly 512 generated tokens (`ignore_eos`), fresh cache salts, 3 repeats, median; prompts were public
court opinions and filings cut to size. Production `a0006fc`, 2026-10-28, 2,300 MHz cap, drafter GPUs at 325 W.

| Cell | Prompt | Streams | Decode tok/s, per stream | TTFT | Accepted draft tokens per round | Server ms per round |
|-|-|-|-|-|-|-|
| short-b1 | short | 1 | **57.2** | 0.82 s | 1.21 | 38.5 |
| 32k-b1 | 32K, cold | 1 | **56.5** | 12.3 s | 1.15 | 38.2 |
| 32k-b3 | 3 x 32K, cold, together | 3 | **30.2** | 42.0 s | 1.15 | 87.3 |
| 32k-b4 | 4 x 32K, cold, together | 4 | **27.4** | 53.3 s | 1.25 | 99.1 |
| 150k-b1 | 150K, cold | 1 | **52.1** | 57.6 s | 1.04 | 39.3 |
| mixed150k-2decode | 150K prefill while 2 streams decode | 3 | 5.3 | 30.6 s | 1.18 | 299.7 |

The same cells at a 2,150 MHz cap, the persistent prefix tier, capacity (1,934,490 KV tokens; four full-length
requests fit), the configuration history and a decode-round profile are in [docs/measurements.md](docs/measurements.md).
Production `ebc29ed8` adds sampled drafting with a fixed 5-token window and the prefix tier to `a0006fc`; its cold 150K
TTFT (58.59 s) matches the record (57.6 s), and these cells have not yet been re-run on it.

## Server limits and memory

What the shipped configuration admits, and the memory it leaves free. The values are set in [serve.sh](serve.sh) and
[dsv41.env](dsv41.env); the pool size is the engine's own log line.

| Limit | Value | Set by |
|-|-|-|
| longest request (`MAX_LEN`) | 327,680 tokens | `PROD_MAX_LEN` in `dsv41.env` |
| concurrent streams (`MAX_SEQS`) | 4 | `serve.sh` |
| prefill chunk (`MAX_BATCH`) | 8,192 tokens per step | `serve.sh` |
| GPU memory utilization (`UTIL`) | 0.86; only gates the startup check, because the KV pool is set in bytes | `serve.sh` |
| KV pool | 6 GiB per rank (`PROD_KV_BYTES=6442450944`), 46,603 blocks | `dsv41.env` |
| admissible KV tokens | **1,934,490**: four requests at the full 327,680 tokens fit (1,310,720) | engine log, `a0006fc` and `ebc29ed8` |
| speculative decoding | DSpark on the x86 drafter, sampled drafting, fixed window of 5 tokens | `serve.sh`, `dsv41.env` (`PROD_PP4`) |
| lowest free memory seen | 6.3 GB `MemAvailable` on each Spark, during the 2026-10-30 prefix-tier test window | [measurements](docs/measurements.md#persistent-prefix-tier-2026-10-30-and-2026-10-31-production-ebc29ed8) |
| free memory, 150K + three 32K prompts at once | at least 5.6 GiB on each Spark (`a0006fc`, 2026-10-28) | [capacity](docs/measurements.md#capacity-engine-log) |

Without the x86 drafter the KV pool has to go back to 3.75 GiB per rank (989,460 tokens): the local drafter has not been
tested with more, and `serve.sh` refuses the combination.

## Architecture

```
                       +---------------------- x86 offload host ----------------------+
                       |  Engram server: layer 1 + 14 tables in RAM (~189 GiB)        |
                       |  DSpark drafter: 3 layers + Markov head, EXL3, TP2 on an     |
                       |  NVLinked RTX 3090 pair (sampled drafting, window 5)         |
                       +------------+------------------------------+------------------+
                                    | 40 Gb/s RoCE v2              | 40 Gb/s RoCE v2
                                    | (Engram rows, draft rounds)  |
   clients --HTTP :8000-->  +-------+---------+   200 Gb/s   +-----+-----------+
   (OpenAI API)             | DGX Spark  rank0| <==CX-7==>   | DGX Spark rank1 |
                            | vLLM API, TP2   |   NCCL TP    | TP2             |
                            | target 40 layers, KV 6 GiB, persistent prefix tier |
                            +-----------------+              +-----------------+
```

| Piece | Where | What it does | Code |
|-|-|-|-|
| target model | both Sparks, TP2 | verifies drafts, samples, generates | [serve.sh](serve.sh), [dsv41.env](dsv41.env), `offload/upstream_all/` |
| Engram tables | x86 RAM, RDMA | Engram rows for prompt and decode; local NVMe reader kept as exact fallback | `offload/engram/`, `offload/transport/` |
| DSpark drafter | x86 RTX 3090 pair | 5 drafted tokens per round, sent back over RDMA | `offload/dspark/worker/`, `offload/pp4_prod/` |
| async round proxy | CPU process on rank 0 | runs the remote round off the engine thread; watchdog and bounded respawn | `offload/dspark/spark/`, `offload/promote/async-tp2/` |
| KV page packing | both Sparks | packs KV pages at the 327,680 limit | `offload/kvpack/`, `offload/promote/k1/` |
| persistent prefix tier | Spark NVMe | stores long-prompt KV per namespace; requests opt in, untagged requests are never stored | launcher glue in `offload/prefixstore/production/`; the tier itself follows in the next push ([why](docs/publication.md#prefix-tier-code)) |

If the x86 host is down, Engram reads fall back to the Sparks' local disk and drafting fails closed to target-only
rounds: the API keeps serving, slower. [docs/architecture.md](docs/architecture.md) explains each piece, the failure
paths and the measured effect of each.

## Requirements

| Item | Tested configuration |
|-|-|
| serving nodes | 2 x NVIDIA DGX Spark (GB10, 121 GiB unified memory), direct ConnectX-7 200 Gb/s link |
| offload host | x86 AMD EPYC 7302P (16 cores), 503 GiB RAM; about 190 GiB of it holds the Engram tables |
| host links | ConnectX-5 Ex, one 40 Gb/s DAC per Spark, MTU 9000, RoCE v2 |
| drafter GPUs | 2 x RTX 3090 24 GB with an NVLink bridge (one card also works), 325 W cap |
| image | `ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5` (vLLM 0.31.1.dev0+g6e517b15, linux/arm64, `sha256:8fc2c99a3562...8309e4`), unmodified; our overlays are mounted at start |
| launcher | [sudoingX/dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41) at `cc59c36` ([our fork](https://github.com/ProprietaryLegal/dgx-spark-deepseek-v41)) |
| weights | [HeNryous 2.75 bpw](https://huggingface.co/HeNryous/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark) rev `86f85253`, or the [legal-weighted allocation](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-LegalWeighted-DGX-Spark) of it that we serve (same size and format), plus DeepSeek's two Engram shards |
| tools | Python 3.10+ (stdlib only for `tools/`), Docker with the NVIDIA runtime, key-based ssh between the nodes |

Without the x86 host the stack still runs as a plain two-Spark serve: leave `OFFLOAD_DOCKER_ENV` and
`OFFLOAD_DSPARK_ENV` empty in `dsv41.env`, and the KV pool has to go back to 3.75 GiB per rank.

## Full build

Everything the published numbers ran on, and where it is:

| Piece | What we run | Where |
|-|-|-|
| launch scripts and configuration | `start.sh` -> `serve.sh` (both Sparks), `stop.sh`, `status.sh`, `logs.sh`, all set by `dsv41.env` | [start.sh](start.sh), [serve.sh](serve.sh), [dsv41.env](dsv41.env) |
| x86 host services | Engram server and TP2 drafter worker, systemd user units | [dsv41-engram.prod.service](offload/engram/server/dsv41-engram.prod.service), [dsv41-dspark-worker-tp2.prod.service](offload/dspark/worker/dsv41-dspark-worker-tp2.prod.service) |
| base image | `ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5`, `sha256:8fc2c99a3562e99d81d2a05b8345d12726def0a027410d14d0eb0763de8309e4` (linux/arm64), unmodified | [docs/install.md](docs/install.md#2-the-image-both-sparks) |
| overlays (content-addressed stages, every file sha256-pinned) | upstream patch set `e7e8e3f2dd57`, sampled drafting (PP4) `22897accecef`, KV page packing `559c5867ba42`, remote Engram reader, remote drafter client and async proxy | [offload/upstream_all/MANIFEST.json](offload/upstream_all/MANIFEST.json), [offload/pp4_prod/MANIFEST.json](offload/pp4_prod/MANIFEST.json), [offload/kvpack/MANIFEST.json](offload/kvpack/MANIFEST.json), [offload/engram/spark/stage_overlay.sh](offload/engram/spark/stage_overlay.sh), [offload/dspark/spark/stage_overlay.sh](offload/dspark/spark/stage_overlay.sh) |
| launcher | sudoingX's recipe at `cc59c36` plus [recipe-servedir.patch](recipe-servedir.patch) | [sudoingX/dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41) |
| served weights | the legal-weighted allocation of HeNryous's 2.75 bpw build (same size and format); HeNryous's own build at `86f85253` is the drop-in alternative | [ProprietaryLegal ...-LegalWeighted-DGX-Spark](https://huggingface.co/ProprietaryLegal/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-LegalWeighted-DGX-Spark), [HeNryous 2.75 bpw](https://huggingface.co/HeNryous/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark), [download.sh](download.sh) |
| Engram tables | DeepSeek's two Engram shards at `1bae0e10` | [deepseek-ai/DeepSeek-V4.1-Flash-1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017), [download.sh](download.sh) |
| drafter weights | the checkpoint's own DSpark layers, extracted byte for byte (4,755 tensors) for the x86 host; nothing extra to download | [offload/dspark/TRANSFER.md](offload/dspark/TRANSFER.md), [offload/dspark/TENSORS.md](offload/dspark/TENSORS.md) |
| step by step | cabling, image, launcher, weights, x86 services, `dsv41.env`, first start, checks | [docs/install.md](docs/install.md) |

The persistent prefix tier's code follows in the next push ([why](docs/publication.md#prefix-tier-code)); without it
the launcher prints `MATTER OFF (config-missing)` and serves the configuration above unchanged.

## Quick start

This is a production tree, not a one-command installer. [docs/install.md](docs/install.md) is the full build, step by
step: cabling and addresses, the image by digest, the launcher, the weights, the drafter and Engram files on the x86
host, both x86 services, `dsv41.env`, the first start and the checks. In short:

1. Pull the image on both Sparks and check its digest; clone the launcher at `cc59c36` on the head.
2. Download the weights on both Sparks with `download.sh` (pinned revisions, size checks).
3. Copy the drafter layers and the two Engram shards from the same checkpoint to the x86 host
   ([offload/dspark/TRANSFER.md](offload/dspark/TRANSFER.md)); build and start the Engram server and the drafter worker.
4. Edit [dsv41.env](dsv41.env) for your node names, fabric interface, model path and link addresses.
5. On the head Spark: `./start.sh`, then `./status.sh`. Measure with the commands under [Reproduce](#reproduce).

`bench.py` and `sparkbench.py` use only synthetic or lab prompts they generate themselves, a fresh salt per request, and
store token counts and timings, never generated text.

## Repository layout

| Path | What it is |
|-|-|
| `start.sh`, `stop.sh`, `status.sh`, `serve.sh`, `dsv41.env` | the production launcher and its configuration |
| `tools/` | `sparkbench.py` (sparkDash protocol), `bench.py` (our cells and a MiaAI-conditions profile), `node_watch.py`, `fake_server.py` and tests |
| `offload/` | every production component, each with a README: Engram, transport, drafter, async proxy, KV packing, upstream patches; the prefix tier's launcher glue |
| `bench.py`, `quality.py`, `functest.py`, `verify_hashes.py` | the older single-stream bench, output checks, function tests, model hash checks |
| `docs/` | [install](docs/install.md), [measurements](docs/measurements.md), [comparison](docs/comparison.md), [architecture](docs/architecture.md), [operations](docs/operations.md), [publication](docs/publication.md) |
| `runs/` | raw benchmark JSON files, one per run, with their conditions |
| `.publication/SOURCE.json` | what this tree was exported from and what was removed or rewritten for publication |

## Tests

```bash
python3 -I -m unittest discover -s tools/tests -v                                    # bench.py and sparkbench.py, CPU only, ~10 s
PYTHONPATH=offload/dspark/spark python3 -B -m pytest -q offload/dspark/spark/tests     # async proxy and remote drafter client
```

Some component suites need the serving image's Python packages; each component README says which. Every overlay this
commit ships matches its byte pins; see [docs/publication.md](docs/publication.md).

## Related repositories

This repository is the full stack. The research archive and the earlier single-component repositories stay up for their
history and their own tests; their code is included here as it runs in production.

| Repository | What it holds |
|-|-|
| [dsv41-offload](https://github.com/ProprietaryLegal/dsv41-offload) | the research archive: every experiment branch up to 2026-10-27 |
| [dsv41-remote-engram-rdma](https://github.com/ProprietaryLegal/dsv41-remote-engram-rdma), [ofl-rdma-transport](https://github.com/ProprietaryLegal/ofl-rdma-transport) | the Engram server and its RDMA transport |
| [dsv41-remote-dspark-drafter-3090](https://github.com/ProprietaryLegal/dsv41-remote-dspark-drafter-3090), [dsv41-dspark-drafter-tp2-nvlink](https://github.com/ProprietaryLegal/dsv41-dspark-drafter-tp2-nvlink) | the one-card and two-card drafter workers |
| [dsv41-async-hostflag-handoff](https://github.com/ProprietaryLegal/dsv41-async-hostflag-handoff) | the async round proxy |
| [dsv41-kv-page-packing-1m](https://github.com/ProprietaryLegal/dsv41-kv-page-packing-1m) | KV page packing |
| [dsv41-native-1017-drafter-sm86](https://github.com/ProprietaryLegal/dsv41-native-1017-drafter-sm86), [dsv41-exact-acceptance-ceiling](https://github.com/ProprietaryLegal/dsv41-exact-acceptance-ceiling) | research only, not serving |
| [dsv41-longctx-bench-tools](https://github.com/ProprietaryLegal/dsv41-longctx-bench-tools), [dsv41-window-harness](https://github.com/ProprietaryLegal/dsv41-window-harness) | earlier measurement tools |
| [deepseek-v41-1017-dgx-spark](https://github.com/ProprietaryLegal/deepseek-v41-1017-dgx-spark), [dgx-spark-deepseek-v41](https://github.com/ProprietaryLegal/dgx-spark-deepseek-v41) | our forks of the HeNryous image and the sudoingX launcher |

## Credits and licence

This stack stands on other people's work: DeepSeek's model, DSpark drafter and Engram; HeNryous's 2.75 bpw weights,
serving image and patch series; the vLLM project; turboderp's exllamav3; sudoingX's launcher, EXL3 MoE plugin, KLD tool
and panel; TensorFold and bertholomus's fork of it; MiaAI-Lab's sparkDash protocol; and the kernel donors listed in
[CREDITS.md](CREDITS.md). If you build on this repository, please credit those projects as well.

Original code is Apache-2.0 ([LICENSE](LICENSE)). Third-party code keeps its own licence; see [NOTICE](NOTICE) and
[LICENSES/](LICENSES/). No model weights are distributed here.

## Work with PLI Labs

[PLI Labs](https://proprietarylegal.ai/labs.html) is the open research arm of Proprietary Legal Intelligence. PLI builds
AI around an organization's own work product: retrieval over its documents, staged workflows, validation of every output
and attorney review before anything goes out. This stack is how we run that privately, on hardware we own. If you want
private, on-prem LLM serving of your own, from choosing the hardware to the measured stack and the workflows on top, we
consult on exactly that: [proprietarylegal.ai](https://proprietarylegal.ai).
