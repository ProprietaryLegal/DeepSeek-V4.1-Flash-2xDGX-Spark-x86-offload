# What this tree is, and what was left out

This repository is a cleaned export of our private production repository at commit `ebc29ed8` (branch
`prod/matter-l2b`), made with `git archive` and published as one new commit. `.publication/SOURCE.json` lists exactly
what was taken, dropped and rewritten, by count and path.

## Left out

| What | Why |
|-|-|
| `documents/` | internal plans, task briefs and reviews: process, not code |
| `offload/results/` | raw result files from the first phase (575 MB); the numbers are summarised in docs/measurements.md |
| `offload/spark_leads/` | reading notes and upstream metadata dumps, not used by production |
| `RUNBOOK.md`, `BENCHMARKS.md`, `PHASE1_DONE`, backup copies | an internal runbook (replaced by docs/operations.md), stale numbers, a marker file, backups |
| benchmark prompts and outputs | never published; `tools/bench.py` generates synthetic prompts and `tools/sparkbench.py` uses sparkDash's public lab prompts instead |
| model weights | on Hugging Face, see the README |
| `offload/prefixstore/` except its launcher glue | the persistent prefix tier follows in the next push; see [below](#prefix-tier-code) |

## Rewritten

- Machine names, login names and home directories became role names (`sparkhead`, `sparkworker`, `x86host`,
  `controller`, `rank0user`, `operator`), as in our other public repositories.
- Private data paths became `/opt/dsv41/...` placeholders.
- A few files that carried prompt text load it from a file you supply instead (`DSV41_BENCH_SPEC_FILE` and similar).
- Result files in `runs/` have the server's address replaced by `<head>`; nothing else in them was changed.
- Identity values derived from private configuration were zeroed. No prefix-tier namespace, exclusion entry or stored
  KV is published, now or with the tier's code.

## Byte pins and the rewrite

The staging scripts verify every overlay file against a sha256 pinned in its component's `MANIFEST.json`. Every overlay
in this commit is published byte for byte: the upstream, PP4 and KV-packing overlays (all 72 pinned files match), the
Engram and drafter overlays, and the scripts that stage them. Nothing here ships with a pin it fails.

## Prefix tier code

The persistent prefix tier (`offload/prefixstore/`: the overlay for patches 0100-0106, its builder, its configuration and
its tests) is not in this commit. Three of its overlay files carry internal machine and folder names in comments and
in one constant, and the staging script checks each overlay file against a pinned sha256, so publishing them rewritten
would ship a tier that refuses its own pins. The fix is being made at the source; the files are re-pinned there and
the tier is published in the next push, byte for byte.

What is here now: the measurements ([docs/measurements.md](measurements.md#persistent-prefix-tier-2026-10-30-and-2026-10-31-production-ebc29ed8)),
the design ([docs/architecture.md](architecture.md#persistent-prefix-tier)) and the launcher glue that `serve.sh`
sources (`offload/prefixstore/production/matter_serve.sh`, `shm_stop.sh`, `shm_clean.py`). Without the tier's
configuration the glue prints one line, `MATTER OFF (config-missing): serving without the matter tier (the pre-matter
production form)`, and adds nothing to the engine: the serve is then exactly production without the tier.

The point-to-point link addresses (`10.202.x.x`) are private RFC 1918 addresses already shown in our earlier public
repositories; replace them with your own.

## Scan

Before publication the tree was scanned for personal names, client and matter material, private paths and addresses,
credentials and binary files; the scan reports categories, counts and paths only.
