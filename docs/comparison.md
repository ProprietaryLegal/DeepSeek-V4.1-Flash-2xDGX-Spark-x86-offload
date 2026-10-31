# Comparison with other DGX Spark recipes

Other public recipes serve DeepSeek-V4.1-Flash-1017 on two DGX Sparks. Each is good work and each publishes its own
numbers. This page lists what each one measured and under which conditions, with sources, and says which of our numbers
were measured the same way. Numbers below are quoted from each project's README or model card as of 2026-10-31; follow
the links for their current versions.

## Same-protocol numbers

On 2026-10-31 we ran MiaAI's sparkDash protocol (commit `b96244a2`, re-implemented in
[tools/sparkbench.py](../tools/sparkbench.py)) on production `ebc29ed8`: both Sparks at a 2,300 MHz cap, drafter GPUs at
a 400 W cap, 4 sequences, 3 repeats ([full tables](measurements.md#sparkdash-protocol-2026-10-31), raw
[JSON](../runs/2026-10-31-sparkdash-protocol-ebc29ed8.json)). Those rows are directly comparable with MiaAI's sparkDash
table below, apart from the clock (2,300 against 2,200 MHz) and the hardware (our x86 host and 2 RTX 3090s).

| Total tok/s | 1 stream | 2 streams | 3 streams | 4 streams |
|-|-|-|-|-|
| prose T=0, ours / MiaAI | 66.0 / **80.7** | 90.5 / **110.6** | 112.4 / **133.6** | 130.1 / **154.0** |
| code T=0, ours / MiaAI | 110.5 / **118.1** | 147.9 / **149.4** | **174.8** / 171.0 | **192.0** / 166.1 |
| prose T=0.7 thinking, ours / MiaAI | 55.9 / **63.9** | 72.0 / **93.3** | 90.8 / **107.8** | 105.3 / **120.6** |

| Prefill tok/s | 4K | 8K | 16K | 32K | 64K | 128K | 256K |
|-|-|-|-|-|-|-|-|
| ours | **2,826.5** | **2,812.7** | **2,605.6** | **2,667.2** | **2,641.3** | **2,650.3** | **2,617.9** |
| MiaAI (sparkDash) | 2,105.9 | 2,152.0 | 2,154.8 | 2,153.6 | 2,136.2 | 2,077.1 | 2,065.0 |
| bertholomus (own tool) | | 2,439 | | 2,568 | 2,550 | 2,523 | |

The short-request test follows bertholomus's published design (a short chat sent 1 s behind a cold 93,335-token
prompt): our short chat's first token came after 34.3 s, bertholomus's after 38.6 s.

## Published numbers and their conditions

### MiaAI-Lab, TensorFold engine

Source: [MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks)
(Apache-2.0), README "Performance" and `docs/measurements.md`.

Conditions: TensorFold (Zig engine), EAQ 2.9 bpw weights, both GPUs capped at 2,200 MHz, `CONTEXT=524288`, up to 4
streams, drafts on, "real prose and code prompts", numbers as reported by sparkDash. The head also ran a desktop and
about 18 small containers.

| Decode tok/s | 1 stream | 2 streams | 3 streams | 4 streams |
|-|-|-|-|-|
| prose, T=0, thinking off | 80.7 (TTFT 133 ms) | 110.6 total, 56.0 each | 133.6 total, 45.4 each | 154.0 total, 39.9 each |
| prose, T=0.7, thinking on | 63.9 (TTFT 214 ms) | 93.3 total, 48.6 each | 107.8 total, 38.0 each | 120.6 total, 32.0 each |
| code, T=0, thinking off | 118.1 (TTFT 213 ms) | 149.4 total, 76.4 each | 171.0 total, 58.8 each | 166.1 total, 45.0 each |

Prefill: 2,105.9 / 2,152.0 / 2,154.8 / 2,153.6 / 2,136.2 / 2,077.1 / 2,065.0 tok/s at 4K / 8K / 16K / 32K / 64K / 128K /
256K-token prompts (TTFT 2.13 s to 127.13 s). Its own `tools/bench.py` (temperature 0, thinking off, random-word prompts)
reads lower decode, 55-61 tok/s at one stream; the README attributes the gap to the prompts, since a drafter accepts
fewer tokens on random words.

### sudoingX

Source: [sudoingX/dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41) (Apache-2.0), README.

Conditions: vLLM with its patch series and EXL3 MoE plugin (`dsv41-serve:v5`), its own EXL3 2.8 bpw build (v2.0),
`kit_bench.py` set b: one stream, greedy, thinking off, 384-token replies, a 64-token warm-up, then 9 repeats per
prompt, median. DSpark on with k = 5 and per-round depth. Same-box comparison against TensorFold on alternating boots.

| tok/s, median of 9 | code | prose | structured |
|-|-|-|-|
| TensorFold `8e0966e2`, same setup | 97.7 | 57.5 | 140.4 |
| sudoingX v2.0 | 103.7 | 57.8 | 144.4 |

Quality (README, `p4_kld.py` on its 199-conversation panel): v2.0 KLD 0.0198 / top-1 95.94 %, agentic domain KLD
0.0175; HeNryous 2.75 bpw 0.0201 / 95.96 %, agentic 0.0183. We use the same tool and panel; our figures for the
HeNryous build match these.

### HeNryous

Source: [HeNryous/deepseek-v41-1017-dgx-spark](https://github.com/HeNryous/deepseek-v41-1017-dgx-spark) (Apache-2.0), README.

Conditions: vLLM image v5 (the image this repository serves), EXL3 2.75 bpw, Elevatormusic's TensorFold test scripts
(`tests/v41_suite.py` speed group, `tests/v41_bench.py`) unchanged, temperature 1 and top_p 1, medians of three suite
runs or two bench runs.

| tok/s, median | v5, 2,000 MHz | v5, 2,400 MHz | v12, 2,400 MHz |
|-|-|-|-|
| prose, 1 stream (suite) | 54.6 | 56.6 | 56.0 |
| code, 1 stream (suite) | 91.5 | 88.9 | 91.1 |
| prose, aggregate 2 / 3 / 4 streams (bench) | 71.9 / 85.3 / 94.4 | not clean (thermal cap) | 71.5 / 85.1 / 95.3 |
| code, aggregate 2 / 3 / 4 streams (bench) | 112.6 / 136.1 / 155.9 | not clean (thermal cap) | 117.0 / 135.4 / 154.0 |
| prefill, cold 8K | 2,203 | | 2,470 |
| decode with thinking on, prose / code (suite) | 52.8 / 78.8 | 54.6 / 59.2 | 52.2 / 64.6 |

Its README notes that single-stream code at T=1 moves by up to ±10 % between runs.

### bertholomus, TensorFold engine

Source: [bertholomus/DeepSeek-V4.1-Flash-TensorFold-TP2-2xGB10](https://huggingface.co/bertholomus/DeepSeek-V4.1-Flash-TensorFold-TP2-2xGB10)
(model card, v0.7.3, 2026-10-24; recipe [bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10),
Apache-2.0) and the weights card [bertholomus/DeepSeek-V4.1-Flash-1017-EXL3-2.5bpw](https://huggingface.co/bertholomus/DeepSeek-V4.1-Flash-1017-EXL3-2.5bpw)
(revision `b8054f70`).

Conditions: TensorFold branch `deepseek-v41-zig-tp2`, EXL3 2.5 bpw routed experts (2.52 bpw overall, about 185 GB),
`--context 1048576 --parallel 8`, a shared window of 2,097,152 positions, greedy, DSpark drafting, median of 3 unless
noted, its own prompt sets a and b. Clock not stated.

| Row | tok/s |
|-|-|
| decode, set a (512 tokens): code / prose / structured | 106.0 / 60.5 / 118.3 |
| decode, set b (384 tokens): code / prose / structured | 112.7 / 67.5 / 159.5 |
| 2 / 4 streams, set b, aggregate (median of 9) | 95.3 / 134.0 |
| 4 / 8 streams sustained 90 s, set b, aggregate | 151.8 / 168.3 |
| prefill 8K / 32K / 64K / 128K | 2,439 / 2,568 / 2,550 / 2,523 |
| prefill 93,335 tokens | 2,364 |
| decode after a 128K prompt (three fixed prompts: 53.5 / 114.4 / 99.2) | 99.2 |
| short chat 1 s behind a cold 93,335-token prompt, first token | 38.6 s |

Quality (weights card): KL(original || quant) over the full vocabulary and top-1 agreement on its own 122-row set
(294,481 tokens): short rows 0.1305 / 92.01 %, long rows 0.2876 / 87.07 %, wiki 0.1558 / 87.41 %; by kind, code
0.0494 / 95.22 %, math 0.1425 / 91.51 %, prose 0.1254 / 91.77 %, creative 0.0623 / 91.09 %, tool calls 0.5948 /
79.43 %. Gates: 1M-context needles 3/3, tool calls 16/16, structured output 11/11.

### This repository

Same-protocol rows: above. Our own conditions (temperature 1, thinking on, 512 tokens, court-opinion prompts up to
150K): [measurements.md](measurements.md#speed-record-2026-10-28-production-a0006fc). Quality on sudoingX's panel:
0.0204 / 95.91 % (served), agentic 0.0184 / 95.88 %; see [measurements.md](measurements.md#quality-kl-divergence-against-the-original-model).

## Why numbers from different protocols cannot be ranked

| Factor | Effect |
|-|-|
| temperature and thinking | greedy decoding without thinking lets a drafter accept far more tokens than T=1 with reasoning text; MiaAI's own rows show 80.7 (T=0, off) against 63.9 (T=0.7, on) |
| prompt content | code drafts better than prose; random words draft worst (MiaAI: 55-61 against 80.7) |
| output length | a natural end stops at different points; a fixed 512 or 384 tokens measures a fixed amount of decoding |
| GPU clock cap | 2,000 to 2,400 MHz across the recipes; the two ranks wait for the slower GPU |
| extra hardware | this repository uses an x86 host and two RTX 3090s; the others use the two Sparks only |
| weights | 2.52, 2.75, 2.8 and 2.9 bpw builds with different calibration |
| context limit | 327,680 here, 524,288 for MiaAI, 1,048,576 for bertholomus; it changes the memory left for KV and the engine's scheduling |

## How to measure the same conditions

`tools/sparkbench.py` runs sparkDash's protocol with sparkDash's own lab prompts (from its `src/shared/llmPrompts.js`)
against any OpenAI-compatible server, so its numbers sit on the same basis as MiaAI's sparkDash table:

```bash
python3 -I tools/sparkbench.py --url http://<head>:<port> --out runs/<recipe>-<date>.json --reps 3 \
    --suites prose-t0,code-t0,structured-t0,prose-t07-think,prefill --deep 32768:1,131072:1 --interference 2
```

`tools/bench.py` is our own tool. `--profile ours` runs the cells in measurements.md on synthetic records instead of
court opinions; `--profile mia` approximates MiaAI's headline conditions on synthetic prompts fixed by `--seed` (512
tokens at most, natural end allowed), so its absolute numbers differ from sparkDash's. For a server that does not accept
vLLM's `cache_salt` or `priority` fields, add `--no-cache-salt` or `--no-priority`; every prompt still starts with a
unique line, so the prefix cache cannot be hit.

```bash
python3 -I tools/bench.py run --profile all --url http://<head>:<port> --exact-size \
    --label <recipe>-<date> --note "<engine, commit, clock>" --out runs/<recipe>-<date>.json
python3 -I tools/bench.py compare runs/<ours>.json runs/<recipe>-<date>.json
```

Lock and record the GPU clock (`tools/node_watch.py` logs it) and state it with the result. We are porting the other
builds' benchmarks (bertholomus's sets a and b, tool-call evaluations, 8-32 stream sweeps, 1M needles) into
`sparkbench.py`; results will land in `runs/` with their dates, commits and clocks. If you maintain one of these recipes
and want a number corrected or a condition stated differently, please open an issue.
