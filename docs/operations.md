# Operations

How the production tree is laid out on the machines, and how to start, stop, check and roll back. Machine names in
this repository are roles: `sparkhead` (rank 0, runs the API), `sparkworker` (rank 1) and `x86host` (Engram server and
drafter worker). Replace them, the link addresses and the home directories (`rank0user`, `operator`) with your own.

## Layout

| Where | What |
|-|-|
| sparkhead `~/dsv41-deploy` | this repository, checked out; `start.sh` and the other scripts run from here |
| sparkhead and sparkworker `/srv/dsv41/<model>` | the weights (`MODEL_DIR`); the worker needs its own local copy |
| sparkhead `~/dgx-spark-deepseek-v41` | the launcher (`RECIPE`) at `cc59c36` |
| both Sparks `~/dsv41-upstream-all/<id>/`, `~/dsv41-pp4/<id>/`, `~/dsv41-kvpack/<id>/` | content-addressed overlay stages, written by `start.sh` and mounted read-only (the prefix tier adds `~/dsv41-prefixstore/<id>/` once its code is published) |
| both Sparks `~/.cache/dsv41-serve/` | the container's `/root/.cache`: JIT builds (and, with the tier on, its store and audit log) |
| x86host | `dsv41-engram.service` (Engram server) and `dsv41-dspark-worker-tp2.prod.service` (drafter worker), systemd user units |

## Start, stop, check

```bash
./start.sh     # refuses if the model or image is missing or a GPU workload already runs (FORCE=1 overrides the last)
./status.sh    # container state, free memory, GPU temperature and clock on both nodes, API health, key /metrics
./stop.sh      # stops this deployment's containers on both nodes only
./logs.sh      # follows the engine logs
```

`start.sh` order: model and image checks on both nodes; clock cap (`GPU_CLOCK_CAP`, `nvidia-smi -lgc`, not persistent);
firewall rule for the API port (`firewall.sh`); stage the Engram overlay and prebuild its JIT; stage the drafter overlay,
the upstream overlay and the PP4 overlay; `serve.sh` (both ranks); the KV-packing start check; one warm-up request.
A start takes several minutes; the first long request after a start can still be slower than later ones.

On the x86 host:

```bash
systemctl --user status dsv41-engram.service dsv41-dspark-worker-tp2-prod.service
```

The Engram server listens only on the two link addresses. The drafter worker holds its GPUs for its whole life.

## Checks after a start

- The engine log reports the expected KV pool (`GPU KV cache size: 1,934,490 tokens` with the shipped settings).
- `engram_remote` log lines (one per table per 60 s) show lookups and 0 fallbacks.
- `/metrics` shows speculative rounds and accepted tokens rising, and no `fallback` or watchdog counts.
- `offload/promote/k1/verify.sh`, `offload/upstream_all/verify_running.sh` and `offload/pp4_prod/verify_running.sh`
  compare the running containers' mounts and environment with the staged bytes.
- `tools/bench.py run --profile ours --only ours/short-b1 --reps-ours 1` for a quick speed check.

## Benchmarks without disturbing a production server

`tools/bench.py` sends only synthetic prompts, never tags a request for the prefix tier (so nothing is stored), uses a
fresh `cache_salt` per request, and refuses to start a group unless `/metrics` shows no running or waiting requests.
Stop other clients first. Run `tools/node_watch.py` beside it to log clocks and free memory and to stop the run
below a memory floor:

```bash
python3 -I tools/node_watch.py --node sparkhead --node sparkworker --min-gib 4.5 \
    --out runs/x-nodes.jsonl --stop-file runs/x.STOP --until-file runs/x.DONE &
python3 -I tools/bench.py run --profile all --url http://127.0.0.1:8000 --exact-size \
    --stop-file runs/x.STOP --label x --note "commit ..., clock ..." --out runs/x.json
touch runs/x.DONE
```

The full run is about 31 minutes on this hardware (`bench.py plan` prints the estimate). Try it first against
`tools/fake_server.py`, which needs no GPU.

## Rollback, piece by piece

Each change is a line or a block in `dsv41.env`, followed by `./stop.sh && ./start.sh`:

| To remove | Change | Result |
|-|-|-|
| async rounds | use the synchronous `OFFLOAD_DSPARK_ENV` line kept below the async one | synchronous remote rounds |
| remote drafter | empty `OFFLOAD_DSPARK_ENV`, and set the KV back to 3.75 GiB per rank | local drafter, the stock KV budget |
| remote Engram | remove the `VLLM_ENGRAM_REMOTE*` and overlay entries from `OFFLOAD_DOCKER_ENV` | local NVMe Engram reader |
| PP4 sampled drafting | unset `PROD_PP4` and restore the previous depth policy | the upstream-install drafting |
| prefix tier | off in this commit: without its configuration, `matter_serve.sh` prints `MATTER OFF (config-missing)` and adds nothing (a `MATTER-OFF` file in the checkout root also turns it off, and so does any failed precondition) | exactly the serve without the tier |

Changing a shell variable alone does not reconfigure a running engine. More detail for each component is in its README
and in `offload/RUNBOOK-offload.md`.
