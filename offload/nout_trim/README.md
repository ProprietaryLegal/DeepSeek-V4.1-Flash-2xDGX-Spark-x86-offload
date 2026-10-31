# NOUT-TRIM: ask the x86host drafter for only the drafts the next step verifies

NDM /goal item 3 (coordinator 17:05Z, 2026-10-28; PERSIST-1 report §5.4 item 1). The remote form of the donor's 0066
`VLLM_DSV41_MARKOV_TRIM`: with `VLLM_DSPARK_REMOTE_N_OUT=window` the Spark sends each STEP entry
`n_out = min(cap[n], num_spec_tokens_to_schedule)` instead of the full K5 cap.

## Why

K5 (`[[1,4,5]]`, live since prod/upstream-all a0006fc) makes every round ask x86host for 5 drafts at 3-4 requests. At 4
requests 4 x 5 = 20 head rows exceed the worker's 16-row head kernel, so the head runs twice: TP2 graph p50 3.60 ms
against 3.17 ms at n_out 4 (MEASURED, `offload/results/e/e7_bench_pair.json`, head 651 vs 327 us). The 0047 window
verifies 2-3 drafts in prose rounds, so most of those positions are never read.

## What changes

| File | Change |
|-|-|
| `overlay/dist/vllm/v1/worker/gpu_worker.py` | production's 0085b file + the donor's 0066 hand-off, guarded by `VLLM_DSPARK_REMOTE_N_OUT=window`: before `model_runner.execute_model`, `speculator.dsv41_set_next_drafts(scheduler_output.num_spec_tokens_to_schedule)` |
| `overlay/remote_dspark/speculator.py` | `_NextDrafts` mixin on both remote speculators: the count is consumed once by this step's `propose` and passed to the round; the window cut is decided at start (`config.n_out_window`) |
| `overlay/remote_dspark/config.py` | `VLLM_DSPARK_REMOTE_N_OUT=auto|window|0`; `n_out_window(cfg, async_scheduling)`: on only with async scheduling and capacity/resilience |
| `overlay/remote_dspark/roundcore.py` | `BatchView.next_window`; `n_out_for(n, window)` = min(table cap or N, window); counters `n_out_window_rounds`, `n_out_window_missing`, `n_out_sent_b<n>_o<k>`; histogram `worker_us_b<n>_o<k>` |
| `overlay/remote_dspark/round.py` | `run(..., next_window=)` through the synchronous, thread-proxy and process-proxy paths |
| `overlay/remote_dspark/shmregion.py` | descriptor header word 5 = the window (written in every descriptor; region VERSION 2) |
| `overlay/remote_dspark/proxy_proc.py` | the process proxy reads it and gets `n_out_window` in its init (a respawn keeps it) |

Every other file of the package is production's byte for byte (commit b1b25e7 is the verbatim copy).

## Why it is exact

- Under async scheduling, `AsyncScheduler._update_after_schedule` gives every request scheduled in step t exactly
  `num_spec_tokens_to_schedule(t)` draft placeholders, and step t + 1 schedules at most that many
  (`scheduler.py` spec-token block: `spec_token_ids[:num_scheduled_spec_tokens]`). The engine core issues
  `execute_model(t)`, then `sample_tokens(t)` (where `propose` runs), then `execute_model(t + 1)` (`core.py`
  `step_with_batch_queue`, also on the deferred structured-output path), so the count set before step t's forward is
  the one step t's drafts serve.
- So positions >= the window are never verified. Positions below it are the full-block drafts bit for bit (CONTRACT
  1.3; the worker's graphs exist for n_out 1-5 at B1-B4). Every emitted token is decided by the target's
  verification: T=0 output is unchanged and T=1 keeps its distribution.
- One thing can differ, as with the donor's TRIM ("changes no verified draft, only the depth choice in rounds where the
  policy wanted more drafts than the window has"): production's conf depth policy sees zero confidence past the window,
  so in a round where it would have chosen a depth above the window it picks the best depth inside the window instead
  of the window itself. Its depth equals production's live depth whenever production's choice is inside the window
  (test `test_verified_drafts_and_accepted_counts_are_unchanged`, with the image's own `DSparkDepthPolicy`).
- No count reaches the speculator (dummy/profile runs, a gpu_worker.py without the hand-off): the round sends the
  table's n_out, as today (`n_out_window_missing`).

## Tests (CPU, no vLLM)

    python3 -m pytest -q offload/nout_trim/tests --basetemp <scratch>        # 15 tests (+1 after the install commit)
    offload/nout_trim/spark_suite.sh offload/nout_trim/overlay/remote_dspark <scratch>/spark-trim
    (cd <scratch>/spark-trim && python3 -m pytest -q tests --basetemp <scratch>/bt)   # the remote DSpark suite

The window values in the tests come from production's own `_dsv41_adaptive_k` (sha256-pinned scheduler overlay,
executed) under serve.sh's AK settings; the regression suite is run against both packages and compared.

## Install and rollback

The install commit re-pins `offload/upstream_all/build.py` to this directory's files (new stage id), adds
`VLLM_DSPARK_REMOTE_N_OUT=window` to dsv41.env's remote drafter env and to the manifest's switches
(`verify_running.sh` checks it in both containers and the rank-0 n_out log line), and declares it in the delta audit.
Rollback: the previous production commit a0006fc (stage c1e72298e5b1) through `W8/restore.sh` (pinned to a0006fc;
INSTALL-ALL `arm.sh prod` first). `VLLM_DSPARK_REMOTE_N_OUT=auto` alone is NOT a verified rollback: MANIFEST.json's
switches require `window`, so `verify_running.sh` refuses the start on both nodes. Turning only the trim off is a
new stage (switch removed from build.py SWITCHES, new id in dsv41.env).
