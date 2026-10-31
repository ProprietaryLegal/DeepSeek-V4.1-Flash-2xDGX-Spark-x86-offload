# Credits

This stack is mostly other people's work, adapted and combined. Every project below is credited where its code or
ideas are used; licence texts are in [LICENSES/](LICENSES/) and [NOTICE](NOTICE). If you build on this repository,
please credit them too. If we have missed or misdescribed anyone's contribution, please open an issue and we will
correct it.

## Model

- **DeepSeek** ([deepseek-ai/DeepSeek-V4.1-Flash-1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017),
  MIT): the model, the DSpark speculative drafter and the Engram design and tables. Base revision `1bae0e10`.
- **HeNryous** ([HeNryous/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark](https://huggingface.co/HeNryous/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark),
  revision `86f85253`, MIT): the 2.75 bpw EXL3 build that `download.sh` fetches. The legal-weighted allocation we serve
  re-encodes 1,414 of its routed experts at the same total size and keeps every other byte of it, so every quality
  number in this repository is, in substance, a measurement of HeNryous's work.

## Engine, image and launcher

- **vLLM** ([vllm-project/vllm](https://github.com/vllm-project/vllm), Apache-2.0): the serving engine. The overlay files
  under `offload/**/overlay/vllm/` are modified vLLM sources and keep their SPDX headers; the top-k kernels come from
  vLLM at `3090266d8`.
- **HeNryous** ([HeNryous/deepseek-v41-1017-dgx-spark](https://github.com/HeNryous/deepseek-v41-1017-dgx-spark),
  Apache-2.0): the serving image `ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v5` and the patch series we adopted
  (0051 indexer defer, 0064 smoe split, 0067 fused VOR/SWA, 0075 replay skip, 0085b idle cache release, 0091 vLLM fixes
  and top-k fix). Its NOTICE is reproduced in LICENSES/. HeNryous's speed tables used Elevatormusic's TensorFold test
  scripts ([Elevatormusic/DeepSeek-V4.1-Flash-1017-EXL3-TensorFold-2x-DGX-Spark](https://github.com/Elevatormusic/DeepSeek-V4.1-Flash-1017-EXL3-TensorFold-2x-DGX-Spark)).
- **sudoingX** ([sudoingX/dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41), Apache-2.0): the
  two-Spark launcher (we run it at `cc59c36`) and the `vllm_exl3_moe` plugin lineage.
- **turboderp** ([turboderp-org/exllamav3](https://github.com/turboderp-org/exllamav3), MIT): the EXL3 format and trellis
  decoding used by the drafter worker; compared against `da68d57` (v1.6.4), built on v1.6.0. FLA kernels are vendored
  inside exllamav3.
- **TensorFold** (original by ashhart; the [bertholomus/TensorFold](https://github.com/bertholomus/TensorFold) fork,
  Apache-2.0): `offload/kvpack/overlay/vllm_exl3_moe/tf_experts.py` builds TensorFold's expert sources from branch
  `deepseek-v41-tp2`, commit `90b68e06`, unchanged; the RDMA all-reduce ring and paced L2 prefetch reach us through the
  HeNryous and sudoingX work. [MiaAI-Lab](https://github.com/MiaAI-Lab/DeepSeek-v4.1-Flash-1017-2x-DGX-Sparks)'s recipe,
  on the TensorFold engine, set the conditions our `--profile mia` reproduces.

## Kernel donors for the drafter

Pinned in `offload/dspark/worker/tools/donors.lock.json` and `offload/dspark/kernels/mxfp4/donors.lock.json` by
revision and file digest. Fetched at build time, not vendored, except where stated.

- **sybil-solutions/trellis-serve** ([a1f72be](https://github.com/sybil-solutions/trellis-serve/tree/a1f72be2ff6319b9b2ea9bf6768c99664b1ca892)):
  MIT; its Marlin-derived C++ is Apache-2.0 (its `cuda/NOTICE`).
- **Zeuss5/cuda-exl3** ([6a1ffc3](https://github.com/Zeuss5/cuda-exl3/tree/6a1ffc34866e23f484574ce1922a8bca93eb33b2)):
  MIT, with ExLlamaV3 attribution.
- **ro99/strata** ([015b075](https://github.com/ro99/strata), Apache-2.0): portions adapted in
  `offload/dspark/kernels/mxfp4/regfed.cu`; its licence is `offload/dspark/kernels/mxfp4/LICENSE.strata` and the
  changes are listed in that directory's NOTICE.
- **Marlin** ([IST-DASLab/marlin](https://github.com/IST-DASLab/marlin), Apache-2.0), through trellis-serve and vLLM.
- **NVIDIA CUTLASS** (v3.9.2 headers, BSD-3-Clause) for the grouped-kernel experiments.

## Measurement

- **MiaAI-Lab/sparkDash** ([MiaAI-Lab/sparkDash](https://github.com/MiaAI-Lab/sparkDash), Apache-2.0, commit
  `b96244a2`): the decode and prefill protocol and the lab prompts that `tools/sparkbench.py` re-implements in Python
  (`server/collectors/DecodeBench.js`, `PrefillBench.js`, `LlmStreaming.js`, `contextFill.js`,
  `src/shared/llmPrompts.js`). The prompt strings are sparkDash's; the code is a re-implementation.
- **bertholomus** ([model card](https://huggingface.co/bertholomus/DeepSeek-V4.1-Flash-TensorFold-TP2-2xGB10)): the
  design of the short-request-behind-a-long-prompt test (a short chat 1 s behind a cold 93,335-token prompt) that
  `tools/sparkbench.py --interference` follows.
- **sudoingX** ([sudoingX/dgx-spark-deepseek-v41](https://github.com/sudoingX/dgx-spark-deepseek-v41), Apache-2.0):
  `p4_kld.py`, the KL-divergence tool, and the 199-conversation general panel (including its agentic tool-call domain)
  behind every quality number here.
- The definitions in `tools/bench.py` (TTFT, prefill tok/s, per-stream decode tok/s) follow MiaAI-Lab's `tools/bench.py`
  so that the columns mean the same thing. Its code is not copied.
- The published numbers we quote in the README and `docs/comparison.md` are MiaAI-Lab's, bertholomus's, sudoingX's,
  HeNryous's and the other listed builds' own.

## PLI Labs

The x86 offload (Engram server and transport, remote drafter, async proxy), KV page packing, the persistent prefix tier,
the PP4 sampled-drafting verifier, the promotion and verification tooling and `tools/` are by PLI Labs
([ProprietaryLegal](https://github.com/ProprietaryLegal)), Apache-2.0.
