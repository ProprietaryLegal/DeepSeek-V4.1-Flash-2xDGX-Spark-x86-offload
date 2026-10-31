# PP4 production layer (sampled K2 drafting)

NDM 2026-10-28: "INSTALL IT WITHOUT DOING TESTING. We will test after install. Just save a ROLLBACK so that if it
performs terribly, we can roll back to a setting withotu it." Plan: `documents/plans/2026-10-28_pp4-install.md`.

PP4 = the qualified Round 18 `76e2e21` (admission `PP4-76e2e21c-admission-W-20261028T034416Z`): the x86host drafter
samples top-32 proposals from q, the Sparks verify them with standard rejection sampling, at a fixed verify window of 5
(the remote speculator refuses sampled mode under a dynamic schedule or the confidence depth policy).

## Files

| File | What |
|-|-|
| `build.py` | composes `overlay/` + `MANIFEST.json` from git objects: remote_dspark = three-way merge of the 0075 package (a0006fc) and PP4's (base 596ba1c), no conflicts; PP4's verifier files prepared exactly as the admission did, pinned to its sha256 |
| `MANIFEST.json` | every byte (25 files), the PP4 switches, `remove_env` (NOUT-TRIM), `supersedes`, the x86host worker pins; stage id = its sha256[:12] |
| `compose_env.py` | puts the layer into a production dsv41.env by exact anchors (`apply`/`check --base-commit`) |
| `stage.sh` / `verify_running.sh` | stage `overlay/` to `~/dsv41-pp4/<id>/` on both Sparks (from start.sh); prove the files, switches and fixed-5 argv on both ranks (from K1's verify.sh) |
| `worker.py` | the x86host drop-in `50-pp4.conf`, the runtime attestation, the runtime staging and the running-worker check (PP4-PROMOTE's reviewed texts) |
| `audit.py` | composition audit: env delta = the PP4 switches, mounts delta = the PP4 files; `DELTA-AUDIT.md` |
| `greedy_near_tie.py`, `start_check.py` | the install's start gate: six greedy vs K1-post under the 1.1-nat near-tie rule (x3), T=1 smoke with accepted drafts, worker drafting |
| `watch.py` | 15-minute auto-rollback watch (hard failures only, never speed) |
| (W8) | every layer's W8 restore is rendered by `$C/PP4-INSTALL/RENDER-W8.sh` from `restore-prod.sh.in`, pinned by sha256 |
| `BASE` | the production commit this layer is composed on |

Glue in production files, inert without `PROD_PP4`: `serve.sh` (SPEC 5), `start.sh` (stage), `offload/promote/k1/verify.sh`
(declared PP4 runner + PP4 verify), `offload/kvpack/stage_overlay.sh` (`KVPACK_PP4_RUNNER_SHA256`),
`offload/upstream_all/verify_running.sh` (leaves the superseded items to PP4), `offload/promote/k1/start_checked.sh`
(a failed PP4 start names PP4-INSTALL/ROLLBACK.sh).

## Install, rollback, re-pin (campaign `$C/PP4-INSTALL/`, Controller)

Two stacked layers, each with its own backup and rollback: L1 `nout` = P + NOUT-TRIM (`prod/nout`, composed with P's
compose.py), L2 `pp4` = L1 + PP4 (`prod/pp4`). Per layer L on base B with commit R:
`RENDER-W8.sh --prod B --label <b>` -> `BACKUP.sh --execute --layer L --w8 <B's W8>` -> window open ->
`INSTALL.sh --preflight --layer L --base B R` -> `INSTALL.sh --execute --layer L --base B R` (in tmux; the gates and
the watch run from a frozen clone of this directory's commit) -> after the watch PASS, `REPIN.sh --layer L R [G]`.
Rollback at any time: `ROLLBACK.sh --execute --layer L` (target commit, K1 record and W8 from the backup; top layer
first). `DRY-GUARDS.sh R` evaluates every start guard read-only on both Sparks. Every script has `--dry-run`.

## Tests

`python3 -m pytest offload/pp4_prod/tests` (CPU; fake Spark hosts for the shell checks), `mypy --strict` on the modules.
