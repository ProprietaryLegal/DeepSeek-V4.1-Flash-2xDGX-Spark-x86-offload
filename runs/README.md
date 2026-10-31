# runs

One JSON file per `tools/bench.py run`, named `<label>.json`, with a `*-nodes.jsonl` file from `tools/node_watch.py`
beside it when one was recorded. Each file records the tool's sha256, the server URL and model id, the start and end
times, the profiles, the seed and a free-text note with the commit and the clock. It holds token counts, timings and a
sha256 of each reply, never prompt or generated text.

Read one with `python3 -I tools/bench.py table runs/<label>.json`, or compare two with
`python3 -I tools/bench.py compare runs/<a>.json runs/<b>.json`.

`tools/sparkbench.py` writes its own format: one record per decode wave (rates, TTFT, token counts, spec-decode
counter deltas), the prefill samples with the overhead correction, deep-context waves and short-behind-long runs.

| File | Tool | Date | Conditions |
|-|-|-|-|
| [2026-10-31-sparkdash-protocol-ebc29ed8.json](2026-10-31-sparkdash-protocol-ebc29ed8.json) | `sparkbench.py` (sparkDash `b96244a2` protocol) | 2026-10-31 03:51-04:09 UTC | production `ebc29ed8`, served weights legal-weighted allocation of HeNryous 2.75 bpw, both Sparks at a 2,300 MHz cap, drafter GPUs at a 400 W cap, `max-num-seqs` 4, 3 repeats; server URL replaced by `<head>` |

Tables built from it: [docs/measurements.md](../docs/measurements.md#sparkdash-protocol-2026-10-31).
