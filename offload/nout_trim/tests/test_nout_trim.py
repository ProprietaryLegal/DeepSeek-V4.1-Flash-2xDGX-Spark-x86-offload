# SPDX-License-Identifier: Apache-2.0
"""NOUT-TRIM (VLLM_DSPARK_REMOTE_N_OUT=window): the Spark asks the x86host drafter for only the positions the next step
verifies, n_out = min(cap, num_spec_tokens_to_schedule).

Offline, against the reference worker (mock_worker.WorkerCore over TCP) and the simulated engine of the remote DSpark
suite. The window values come from production's own scheduler code (offload/upstream_all overlay scheduler.py,
_dsv41_adaptive_k, executed here) under production's 0047 settings read from serve.sh, and the depth choice from the
image's DSparkDepthPolicy (when the image source copy is present).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Iterator
from typing import Any, Callable

import numpy as np
import pytest
import torch

import sim
import vllm_stubs

vllm_stubs.install()

from remote_dspark import speculator as S  # noqa: E402
from remote_dspark import wire  # noqa: E402
from remote_dspark.client import RemoteDraftClient  # noqa: E402
from remote_dspark.config import RemoteConfig, n_out_table, n_out_window  # noqa: E402
from remote_dspark.mock_worker import TcpStubServer, WorkerCore, fake_draft  # noqa: E402
from remote_dspark.proxy_proc import decode_init  # noqa: E402
from remote_dspark.round import RemoteRound  # noqa: E402
from remote_dspark.roundcore import STATUS_OK, STATUS_ROUND_FAILED  # noqa: E402
from remote_dspark.shmregion import RING, VERSION, RegionLayout, SharedRegion  # noqa: E402
from remote_dspark.streamsync import CpuHostFlagSync  # noqa: E402

import test_round  # noqa: E402

# the remote DSpark suite's helpers (untyped there), typed here
hello: Callable[[], wire.Hello] = test_round.hello
cfg_for: Callable[..., RemoteConfig] = test_round.cfg_for
churn: Callable[[sim.Engine, int, np.random.Generator], None] = test_round.churn
sd_lookup: Callable[..., list[int]] = vllm_stubs.build_dynamic_sd_schedule_lookup
stub_vllm_config: Callable[..., Any] = vllm_stubs.vllm_config

HERE = Path(__file__).resolve().parent
NOUT = HERE.parent
ROOT = NOUT.parents[1]
SERVE = ROOT / "serve.sh"
DSV41_ENV = ROOT / "dsv41.env"
SCHED = ROOT / "offload/upstream_all/overlay/dist/vllm/v1/core/sched/scheduler.py"
SCHED_SHA = "079986917de3505a29e13bba3837a8b756bac3928598de01258018a4cc1d4e71"   # build.py pin (0091 on 0075)
GPU_WORKER = NOUT / "overlay/dist/vllm/v1/worker/gpu_worker.py"
GPU_WORKER_BASE = ("5aad62527879f2c22a44367fdd503c4a91cc7d21", "offload/upx/overlay/vllm/v1/worker/gpu_worker.py",
                   "837e3e8954452f6ba92ac282a75640cc0c6fe0dbcafd8cf9acf348fb39e0dcef")   # build.py pin (0085b)
IMAGE_DEPTH = Path("/opt/dsv41/data/src-image/vllm/v1/worker/gpu/spec_decode/depth_policy.py")
REMOTE_ROUND_MS = "28.79,31.86,34.44,37.76,41.56,43.68"    # dsv41.env OFFLOAD_DSPARK_ENV (the conf prices)
REMOTE_DRAFT_MS = "4.4"


# ------------------------------------------------------------------------------------------- production settings

def serve_settings() -> dict[str, Any]:
    """0047 AK settings and the K5 schedule as serve.sh launches them (defaults of AK_* in serve.sh)."""
    text = SERVE.read_text()

    def default(name: str) -> str:
        m = re.search(rf"^{name}=\$\{{{name}:-([0-9.]+)\}}", text, re.M)
        assert m, f"serve.sh: no default for {name}"
        return m.group(1)

    spec = re.search(r"^export SPEC='(.+)'$", text, re.M)
    assert spec
    assert "VLLM_DSV41_ADAPTIVE_K=1" in text
    return {"margin": float(default("AK_MARGIN")), "min": int(default("AK_MIN")), "hi": float(default("AK_HI")),
            "max_reqs": int(default("AK_MAX_REQS")), "spec": json.loads(spec.group(1))}


def production_adaptive_k() -> Callable[..., int]:
    """The scheduler's own _dsv41_adaptive_k (production overlay, sha256-pinned), with serve.sh's settings."""
    src = SCHED.read_bytes()
    assert hashlib.sha256(src).hexdigest() == SCHED_SHA
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_dsv41_adaptive_k")
    ak = serve_settings()
    ns: dict[str, Any] = {"math": math, "_DSV41_AK_MIN": ak["min"], "_DSV41_AK_MARGIN": ak["margin"],
                          "_DSV41_AK_HI": ak["hi"]}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SCHED), "exec"), ns)
    f: Callable[..., int] = ns["_dsv41_adaptive_k"]
    return f


def scheduler_window(emas: list[float | None], prefill_chunk: list[bool], adaptive_k: Callable[..., int]) -> int:
    """num_spec_tokens_to_schedule of a step with these requests (scheduler.py: dynamic lookup, then 0047 when the
    step has at most AK_MAX_REQS requests)."""
    ak = serve_settings()
    n = len(emas)
    dense = sd_lookup(ak["spec"]["num_speculative_tokens_per_batch_size"],
                                                        vllm_max_batch_size=sim.M, vllm_num_speculative_tokens=sim.N)
    k = dense[n]
    if n <= ak["max_reqs"]:
        reqs = {f"r{i}": SimpleNamespace(_dsv41_ak_ema=e, is_prefill_chunk=p)
                for i, (e, p) in enumerate(zip(emas, prefill_chunk))}
        k = adaptive_k(SimpleNamespace(requests=reqs), {rid: 1 for rid in reqs}, k)
    return int(k)


def test_production_settings_are_the_ones_this_trim_assumes() -> None:
    ak = serve_settings()
    assert (ak["margin"], ak["min"], ak["hi"], ak["max_reqs"]) == (1.0, 2, 1.6, 4)
    assert ak["spec"]["num_speculative_tokens_per_batch_size"] == [[1, 4, 5]]          # K5
    f = production_adaptive_k()
    assert scheduler_window([0.2], [False], f) == 2                  # prose: ceil(0.2 + 1) = 2 = AK_MIN
    assert scheduler_window([1.3], [False], f) == 3                  # ceil(2.3)
    assert scheduler_window([1.59], [False], f) == 3
    assert scheduler_window([1.6], [False], f) == 5                  # >= AK_HI: full schedule
    assert scheduler_window([None], [False], f) == 5                 # no history: full schedule
    assert scheduler_window([0.5, 0.5], [False, True], f) == 5       # a prefill chunk: full schedule
    assert scheduler_window([0.9, 1.4, 0.3, 1.1], [False] * 4, f) == 3   # B4: the max over the step


# ------------------------------------------------------------------------------------------- config

def _cfg(**kw: str) -> RemoteConfig:
    env = {"VLLM_DSPARK_REMOTE": "tcp://127.0.0.1:1", "VLLM_DSPARK_REMOTE_IDENTITY": bytes(range(32)).hex(),
           "VLLM_DSPARK_REMOTE_POLICY": "capacity"}
    env.update(kw)
    return RemoteConfig.from_env(env)


def test_window_switch_and_its_preconditions() -> None:
    assert _cfg().n_out == "auto"
    assert n_out_window(_cfg(VLLM_DSPARK_REMOTE_N_OUT="window"), True) == (
        True, "cut to the scheduler's next-step draft count")
    assert n_out_window(_cfg(VLLM_DSPARK_REMOTE_N_OUT="window"), False)[0] is False       # synchronous scheduling
    assert n_out_window(_cfg(VLLM_DSPARK_REMOTE_N_OUT="window", VLLM_DSPARK_REMOTE_POLICY="shadow"), True)[0] is False
    assert n_out_window(_cfg(VLLM_DSPARK_REMOTE_N_OUT="window", VLLM_DSPARK_REMOTE_POLICY="resilience"), True)[0]
    assert n_out_window(_cfg(), True)[0] is False
    assert n_out_window(_cfg(VLLM_DSPARK_REMOTE_N_OUT="0"), True)[0] is False
    with pytest.raises(ValueError, match="VLLM_DSPARK_REMOTE_N_OUT"):
        _cfg(VLLM_DSPARK_REMOTE_N_OUT="trim")
    # the per-request-count table is the same for auto and window (window only cuts further)
    dense = [0, 5, 5, 4, 4]
    for mode in ("conf", "fixed"):
        assert n_out_table(_cfg(VLLM_DSPARK_REMOTE_N_OUT="window"), 5, mode, None, dense) == \
            n_out_table(_cfg(), 5, mode, None, dense)


# ------------------------------------------------------------------------------------------- rounds

@pytest.fixture
def server() -> Iterator[TcpStubServer]:
    srv = TcpStubServer(WorkerCore(hello()), "127.0.0.1", 0).start()
    yield srv
    srv.stop()


def window_round(port: int, *, n_out_by_reqs: list[int] | None = None, window: bool = True, **kw: str) -> RemoteRound:
    rnd = RemoteRound(cfg_for(port, VLLM_DSPARK_REMOTE_N_OUT="window" if window else "auto", **kw), hello(),
                      device=torch.device("cpu"), tp_rank=0, broadcast_fn=None, background=True,
                      n_out_by_reqs=n_out_by_reqs, n_out_window=window)
    t = time.monotonic() + 3
    while not client_of(rnd).ready and time.monotonic() < t:
        time.sleep(0.002)
    assert client_of(rnd).ready
    return rnd


def client_of(rnd: RemoteRound) -> RemoteDraftClient:
    assert rnd.client is not None
    return rnd.client


def nout_counts(core: WorkerCore) -> dict[int, int]:
    v = core.counters.values
    return {k: int(v.get(f"n_out_{k}", 0)) for k in range(1, sim.N + 1)}


def check_cut(eng: sim.Engine, sd: sim.StepData, res: Any, k: int) -> int:
    """Positions < k are the full-block drafts bit for bit; positions >= k are zero (ids and confidences)."""
    drafts, conf, ok = res.drafts.numpy(), res.conf.numpy(), res.ok_mask.numpy()
    checked = 0
    for i, r in enumerate(sd.reqs):
        if not sd.need_draft[i]:
            assert ok[i] == 0 and not drafts[i].any()
            continue
        assert ok[i]
        want_ids, want_conf = fake_draft(eng.expected_window(r), r.anchor, r.computed, sim.N, sim.VOCAB)
        assert np.array_equal(drafts[i, :k], want_ids[:k])
        assert np.array_equal(conf[i, :k], want_conf[:k])
        assert not drafts[i, k:].any() and not conf[i, k:].any()
        checked += 1
    return checked


def random_emas(rng: np.random.Generator, n: int) -> list[float | None]:
    out: list[float | None] = []
    for _ in range(n):
        x = rng.random()
        out.append(None if x < 0.08 else float(rng.choice([0.0, 0.4, 0.9, 1.06, 1.3, 1.5, 1.59, 1.6, 2.4, 3.1])))
    return out


def test_n_out_per_entry_is_the_0047_window_at_b1_to_b4(server: TcpStubServer) -> None:
    """Production K5 + 0047 (AK 1.0/2/1.6/4): every drafted entry of a round asks for exactly the scheduler's window
    (n_out = window, or 0 = all N at the full window), and gets exactly those positions."""
    f = production_adaptive_k()
    rnd = window_round(server.port)
    eng = sim.Engine(seed=41)
    rng = np.random.default_rng(41)
    seen: set[tuple[int, int]] = set()
    runs = 0
    for b in (1, 2, 3, 4):
        for s in range(sim.M):
            eng.slots[s] = None
        for s in range(b):
            eng.new_request(s, prompt_len=60 + 7 * s)
        for _ in range(12):                                   # prompts in, then decode rounds
            sd = eng.step(schedule=list(range(b)))
            if sd.batch.num_reqs != b:
                continue
            emas = random_emas(rng, b)
            pref = [r.prefilling for r in sd.reqs]
            k = scheduler_window(emas, pref, f)
            before = nout_counts(server.core)
            res = rnd.run(sd.batch, sd.taps, sd.num_sampled, sd.num_rejected, sd.last_sampled,
                          sd.next_prefill_tokens, next_window=k)
            assert res.read_status() == STATUS_OK
            assert rnd.n_out_for(b, k) == (0 if k >= sim.N else k)
            drafted = sum(sd.need_draft)
            after = nout_counts(server.core)
            assert {kk: after[kk] - before[kk] for kk in after} == {kk: (drafted if kk == min(k, sim.N) else 0)
                                                                   for kk in after}
            check_cut(eng, sd, res, min(k, sim.N))
            seen.add((b, k))
            runs += 1
            for r in sd.reqs:                                 # keep the requests decoding
                r.decode_left = 99
    assert {b for b, _ in seen} == {1, 2, 3, 4}
    assert {k for _, k in seen} >= {2, 3, 5}
    c = rnd.stats.snapshot()["counters"]
    assert c["n_out_window_rounds"] == runs
    assert "n_out_window_missing" not in c
    assert any(key.startswith("n_out_sent_b4_o") for key in c)
    lat = rnd.stats.snapshot()["latency"]
    assert any(key.startswith("worker_us_b1_o") for key in lat)
    client_of(rnd).close()


def test_window_cuts_inside_the_table_and_never_widens_it(server: TcpStubServer) -> None:
    """window and the per-request-count table together: n_out = min(cap[n], window); no window = the table alone; a
    window of 0 (the scheduler asked for no drafts) still asks for one position (n_out 0 would mean all N)."""
    cap = [0, 5, 5, 4, 4]
    rnd = window_round(server.port, n_out_by_reqs=cap)
    assert [rnd.n_out_for(n) for n in range(1, 5)] == [0, 0, 4, 4]
    assert [rnd.n_out_for(n, 3) for n in range(1, 5)] == [3, 3, 3, 3]
    assert [rnd.n_out_for(n, 5) for n in range(1, 5)] == [0, 0, 4, 4]
    assert rnd.n_out_for(4, 9) == 4 and rnd.n_out_for(1, 1) == 1
    off = window_round(server.port, n_out_by_reqs=cap, window=False)
    assert [off.n_out_for(n, 2) for n in range(1, 5)] == [0, 0, 4, 4]      # auto ignores the window
    client_of(rnd).close()
    client_of(off).close()


def test_no_window_this_round_keeps_all_positions(server: TcpStubServer) -> None:
    rnd = window_round(server.port)
    eng = sim.Engine(seed=5)
    eng.new_request(0, prompt_len=40)
    for _ in range(6):
        sd = eng.step(schedule=[0])
        res = rnd.run(sd.batch, sd.taps, sd.num_sampled, sd.num_rejected, sd.last_sampled, sd.next_prefill_tokens)
        assert res.read_status() == STATUS_OK
        check_cut(eng, sd, res, sim.N)
    c = rnd.stats.snapshot()["counters"]
    assert c.get("n_out_window_missing", 0) == 6 and "n_out_window_rounds" not in c
    client_of(rnd).close()


def test_dropped_late_and_lost_replies_with_the_window(server: TcpStubServer) -> None:
    """The trim changes nothing about failures: a late reply (timeout), a dropped connection and a restarted worker
    fail their round closed (zero drafts, zero confidence) and the next successful rounds are exact again, cut to
    their windows."""
    rnd = window_round(server.port)
    eng = sim.Engine(seed=17)
    for s in range(sim.M):
        eng.new_request(s, prompt_len=200 + s)
    rng = np.random.default_rng(17)
    statuses: list[int] = []
    exact_after = 0
    for step in range(160):
        churn(eng, step, rng)
        if not any(eng.slots):
            eng.new_request(0)
        if step == 30:
            server.core.inject.delay_ms = 400                 # late: past the 150 ms timeout
        if step == 31:
            server.core.inject.delay_ms = 0
        if step == 70:
            server.core.inject.drop_next_step = True          # dropped
        if step == 100:
            server.core = WorkerCore(hello())                 # lost: the worker restarted (resync)
        sd = eng.step()
        k = int(rng.choice([2, 3, 4, 5]))
        res = rnd.run(sd.batch, sd.taps, sd.num_sampled, sd.num_rejected, sd.last_sampled,
                      sd.next_prefill_tokens, next_window=k)
        st = res.read_status()
        statuses.append(st)
        if st == STATUS_OK:
            n = check_cut(eng, sd, res, k)
            if step > 31:
                exact_after += n
        else:
            assert st == STATUS_ROUND_FAILED
            assert not res.drafts.numpy().any() and not res.conf.numpy().any() and not res.ok_mask.numpy().any()
            time.sleep(0.01)
    c = rnd.stats.snapshot()["counters"]
    assert c.get("fallback_timeout", 0) >= 1 and c.get("rounds_failed", 0) >= 2 and c.get("resync_rounds", 0) >= 1
    assert exact_after > 100 and statuses[-10:] == [STATUS_OK] * 10
    client_of(rnd).close()


# ------------------------------------------------------------------------------------------- process proxy

def test_descriptor_carries_the_window_and_a_reused_slot_never_keeps_it() -> None:
    assert VERSION == 2
    L = RegionLayout.for_hello(hello(), 4)
    reg = SharedRegion.create(L)
    other = SharedRegion.attach(L, reg.fd)
    for t in range(1, 11):                                    # wraps the 4-slot ring twice
        nw = 3 if t % 3 else 0
        if nw:
            reg.write_descriptor(t, 1, 5, 0, np.array([1]), np.array([2]), np.array([True]), frozenset(), ["a"],
                                 max_q=3, next_window=nw)
        else:                                                 # an old caller: no window argument
            reg.write_descriptor(t, 1, 5, 0, np.array([1]), np.array([2]), np.array([True]), frozenset(), ["a"])
        d = other.read_descriptor(t)
        assert d.next_window == nw and d.max_q == (3 if nw else 0)


def test_process_proxy_round_trip_with_the_window(server: TcpStubServer, tmp_path: Path) -> None:
    region = SharedRegion.create(RegionLayout.for_hello(hello(), RING))
    sync = CpuHostFlagSync(timeout_s=5.0, region=region)
    cfg = cfg_for(server.port, VLLM_DSPARK_REMOTE_ASYNC="1", VLLM_DSPARK_REMOTE_ASYNC_PROXY="process",
                  VLLM_DSPARK_REMOTE_N_OUT="window", VLLM_DSPARK_REMOTE_STATS_FILE=str(tmp_path / "remote.json"))
    rnd = RemoteRound(cfg, hello(), device=torch.device("cpu"), tp_rank=0, broadcast_fn=None, background=True,
                      stream_sync=sync, n_out_window=True)
    assert rnd.proxy is not None and rnd.n_out_window
    assert decode_init(rnd._proxy_init(start_round=1, strict=False))["n_out_window"] is True   # a respawn keeps it
    t_end = time.monotonic() + 5
    while time.monotonic() < t_end:
        rnd.write_stats()
        try:
            if json.loads((tmp_path / "remote.json").read_text())["counters"].get("hellos", 0) >= 1:
                break
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.01)
    eng = sim.Engine(seed=23)
    for s in range(3):
        eng.new_request(s, prompt_len=50 + s)
    rng = np.random.default_rng(23)
    ok_rounds = 0
    for step in range(60):
        if step == 25:
            server.core.inject.delay_ms = 400
        if step == 26:
            server.core.inject.delay_ms = 0
        sd = eng.step(schedule=[0, 1, 2])
        for r in sd.reqs:
            r.decode_left = 99
        k = int(rng.choice([2, 3, 5]))
        before = nout_counts(server.core)
        res = rnd.run(sd.batch, sd.taps, sd.num_sampled, sd.num_rejected, sd.last_sampled,
                      sd.next_prefill_tokens, next_window=k)
        if res.read_status() == STATUS_OK:
            check_cut(eng, sd, res, k)
            after = nout_counts(server.core)
            assert after[k] - before[k] == sum(sd.need_draft)
            ok_rounds += 1
        else:
            time.sleep(0.01)
    rnd.write_stats()
    snap = json.loads((tmp_path / "remote.json").read_text())
    c = snap["counters"]
    # the late round (step 25) fails closed and the reconnect costs some not-ready rounds, as without the trim
    assert c.get("fallback_timeout", 0) + c.get("fallback_not_ready", 0) >= 1
    assert snap["n_out_window"] is True and c.get("n_out_window_rounds", 0) >= ok_rounds >= 30
    assert "n_out_window_missing" not in c
    rnd.close()


# ------------------------------------------------------------------------------------------- speculator

@pytest.fixture
def remote_env(monkeypatch: pytest.MonkeyPatch, server: TcpStubServer) -> Callable[..., TcpStubServer]:
    def setenv(policy: str, **kw: str) -> TcpStubServer:
        for k, v in {"VLLM_DSPARK_REMOTE": f"tcp://127.0.0.1:{server.port}",
                     "VLLM_DSPARK_REMOTE_IDENTITY": bytes(range(32)).hex(), "VLLM_DSPARK_REMOTE_POLICY": policy,
                     "VLLM_DSPARK_REMOTE_TIMEOUT_MS": "200", "VLLM_DSPARK_REMOTE_BACKOFF_MS": "2",
                     "VLLM_DSPARK_REMOTE_BACKOFF_MAX_MS": "4", "VLLM_DSPARK_REMOTE_LOG_EVERY": "0",
                     "VLLM_DSPARK_REMOTE_STATS_FILE": "", "VLLM_DSPARK_REMOTE_STRICT_START": "1", **kw}.items():
            monkeypatch.setenv(k, v)
        return server
    return setenv


def _vcfg(async_scheduling: bool) -> Any:
    cfg = stub_vllm_config(schedule=[[1, 4, 5]])
    cfg.scheduler_config.async_scheduling = async_scheduling
    return cfg


def _propose(spec: Any, sd: sim.StepData, dummy: bool = False) -> torch.Tensor:
    out: torch.Tensor = spec.propose(sd.batch, None, None, None, sd.taps, sd.num_sampled, sd.num_rejected,
                                     sd.last_sampled, sd.next_prefill_tokens, None, None, dummy_run=dummy)
    return out


def test_speculator_takes_the_count_once_per_step(remote_env: Callable[..., TcpStubServer]) -> None:
    remote_env("capacity", VLLM_DSPARK_REMOTE_N_OUT="window")
    spec = S.init_remote_dspark_speculator(_vcfg(True), torch.device("cpu"))
    assert spec.remote.n_out_window and spec.remote.n_out_by_reqs is None
    assert "next-step window cut on" in spec.stats.snapshot()["n_out_reason"]
    dummy_eng = sim.Engine(seed=99)                          # dummy runs are not real engine steps
    dummy_eng.new_request(0, prompt_len=30)
    spec.dsv41_set_next_drafts(3)
    _propose(spec, dummy_eng.step(), dummy=True)              # a dummy run consumes the count, sends nothing
    assert spec.remote.rounds == 0 and spec._next_drafts is None
    eng = sim.Engine(seed=8)
    eng.new_request(0, prompt_len=30)
    eng.new_request(1, prompt_len=31)
    for step in range(12):
        sd = eng.step(schedule=[0, 1])
        for r in sd.reqs:
            r.decode_left = 99
        k = (2, 3, 5)[step % 3]
        if step != 7:
            spec.dsv41_set_next_drafts(k)                     # gpu_worker.py, before execute_model
        out = _propose(spec, sd)
        cut = k if step != 7 else sim.N                       # step 7: no count reached it -> all positions
        for i, r in enumerate(sd.reqs):
            if sd.need_draft[i]:
                want, _ = fake_draft(eng.expected_window(r), r.anchor, r.computed, sim.N, sim.VOCAB)
                assert torch.equal(out[i, :cut], torch.from_numpy(want[:cut]))
                assert not out[i, cut:].any()
    c = spec.stats.snapshot()["counters"]
    assert c["n_out_window_rounds"] == 11 and c["n_out_window_missing"] == 1
    client_of(spec.remote).close()


@pytest.mark.parametrize("policy,async_sched,mode", [("capacity", False, "window"), ("shadow", True, "window"),
                                                     ("capacity", True, "auto")])
def test_speculator_refuses_the_window_without_its_preconditions(remote_env: Callable[..., TcpStubServer], policy: str,
                                                                 async_sched: bool, mode: str) -> None:
    remote_env(policy, VLLM_DSPARK_REMOTE_N_OUT=mode)
    spec = S.init_remote_dspark_speculator(_vcfg(async_sched), torch.device("cpu"))
    assert spec.remote.n_out_window is False
    assert "next-step window cut off" in spec.stats.snapshot()["n_out_reason"]
    client_of(spec.remote).close()


# ------------------------------------------------------------------------------------------- acceptance math

def _image_depth_policy() -> Any:
    if not IMAGE_DEPTH.exists():
        pytest.skip("image source copy not present")
    spec = importlib.util.spec_from_file_location("image_depth_policy", IMAGE_DEPTH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_verified_drafts_and_accepted_counts_are_unchanged(server: TcpStubServer,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Production verifies min(depth, window) drafts per request, depth from the image's conf policy on the
    confidences masked at cap[n]. With the trim the same drafts sit at every position < window; the policy sees zeros
    past the window, so its depth is never above the window and equals production's live depth whenever production's
    choice is inside the window. Accepted tokens = min(matched prefix, live depth): identical whenever the live depth
    is. Rounds where the policy wanted more drafts than the window are counted (the only possible difference: a
    shallower depth there, as with the donor's 0066 MARKOV_TRIM)."""
    dp = _image_depth_policy()
    monkeypatch.setenv("VLLM_DSPARK_DEPTH_POLICY", "conf")
    monkeypatch.setenv("VLLM_DSPARK_ROUND_MS", REMOTE_ROUND_MS)
    monkeypatch.setenv("VLLM_DSPARK_DRAFT_MS", REMOTE_DRAFT_MS)
    dense = sd_lookup([[1, 4, 5]], vllm_max_batch_size=sim.M,
                                                        vllm_num_speculative_tokens=sim.N)
    pol_full = dp.DSparkDepthPolicy(sim.N, sim.M, torch.device("cpu"), True, depth_cap_by_reqs=dense)
    pol_trim = dp.DSparkDepthPolicy(sim.N, sim.M, torch.device("cpu"), True, depth_cap_by_reqs=dense)
    other = TcpStubServer(WorkerCore(hello()), "127.0.0.1", 0).start()     # one worker per client session
    full = window_round(other.port, window=False)
    trim = window_round(server.port)
    eng_a, eng_b = sim.Engine(seed=61), sim.Engine(seed=61)
    rng = np.random.default_rng(61)
    for e in (eng_a, eng_b):
        for s in range(sim.M):
            e.new_request(s, prompt_len=40 + s)
    same = wanted_more = rounds = 0
    for step in range(120):
        sched = sorted(rng.choice(sim.M, size=int(rng.integers(1, sim.M + 1)), replace=False).tolist())
        sa, sb = eng_a.step(schedule=sched), eng_b.step(schedule=sched)
        for r in sa.reqs + sb.reqs:
            r.decode_left = 99
        k = int(rng.choice([2, 3, 4, 5]))
        ra = full.run(sa.batch, sa.taps, sa.num_sampled, sa.num_rejected, sa.last_sampled, sa.next_prefill_tokens)
        rb = trim.run(sb.batch, sb.taps, sb.num_sampled, sb.num_rejected, sb.last_sampled, sb.next_prefill_tokens,
                      next_window=k)
        assert ra.read_status() == rb.read_status() == STATUS_OK
        n = sa.batch.num_reqs
        assert torch.equal(ra.drafts[:, :k], rb.drafts[:, :k]) and torch.equal(ra.conf[:, :k], rb.conf[:, :k])
        idx = sa.batch.idx_mapping
        pol_full.record(ra.conf.clone(), idx, n)
        pol_trim.record(rb.conf.clone(), idx, n)
        d_full = pol_full.depth[idx[:n].long()].numpy()
        d_trim = pol_trim.depth[idx[:n].long()].numpy()
        live_full = np.minimum(d_full, k)
        assert (d_trim <= k).all()
        for i in range(n):
            if not sa.need_draft[i]:
                continue
            rounds += 1
            if d_full[i] <= k:
                assert d_trim[i] == live_full[i]
            else:
                wanted_more += 1
            if d_trim[i] == live_full[i]:
                same += 1
                match = int(rng.integers(0, sim.N + 1))           # target agrees with the first `match` drafts
                assert min(match, int(live_full[i])) == min(match, int(d_trim[i]))
    assert rounds > 200 and same >= rounds - wanted_more
    client_of(full).close()
    client_of(trim).close()
    other.stop()


# ------------------------------------------------------------------------------------------- gpu_worker.py hand-off

def _git_blob(commit: str, path: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{path}"], stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    return r.stdout if r.returncode == 0 else None


def test_gpu_worker_is_production_plus_the_guarded_hand_off() -> None:
    base = _git_blob(*GPU_WORKER_BASE[:2])
    if base is None:
        pytest.skip("0085b source commit not in this clone")
    assert hashlib.sha256(base).hexdigest() == GPU_WORKER_BASE[2]
    old, new = base.decode().splitlines(), GPU_WORKER.read_text().splitlines()
    assert [ln for ln in old if ln not in new] == []
    added = [ln for ln in new if ln not in old]
    assert added[-1].strip() == "set_next(nxt)"
    assert '_DSV41_NEXT_DRAFTS = os.environ.get("VLLM_DSPARK_REMOTE_N_OUT", "auto").strip().lower() == "window"' \
        in added
    assert sum(1 for ln in added if not ln.lstrip().startswith("#")) == 6
    # the hand-off runs before the model runner's execute_model, inside Worker.execute_model
    tree = ast.parse(GPU_WORKER.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute_model"
              and any(isinstance(a, ast.arg) and a.arg == "scheduler_output" for a in n.args.args))
    kinds = [type(s).__name__ for s in fn.body]
    i_hand = next(i for i, s in enumerate(fn.body) if isinstance(s, ast.If)
                  and isinstance(s.test, ast.Name) and s.test.id == "_DSV41_NEXT_DRAFTS")
    i_exec = next(i for i, s in enumerate(fn.body) if isinstance(s, ast.With)
                  and "execute_model" in ast.unparse(s))
    assert i_hand < i_exec, kinds


def test_gpu_worker_hand_off_reaches_the_speculator() -> None:
    """The guarded block, executed with a stand-in worker: the count goes to the speculator only when the switch is
    on and the speculator has the method."""
    tree = ast.parse(GPU_WORKER.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute_model"
              and any(isinstance(a, ast.arg) and a.arg == "scheduler_output" for a in n.args.args))
    block = next(s for s in fn.body if isinstance(s, ast.If) and isinstance(s.test, ast.Name)
                 and s.test.id == "_DSV41_NEXT_DRAFTS")
    code = compile(ast.Module(body=[block], type_ignores=[]), str(GPU_WORKER), "exec")
    got: list[int] = []
    spec = SimpleNamespace(dsv41_set_next_drafts=got.append)
    for on, runner, out in ((True, SimpleNamespace(speculator=spec), SimpleNamespace(num_spec_tokens_to_schedule=3)),
                            (False, SimpleNamespace(speculator=spec), SimpleNamespace(num_spec_tokens_to_schedule=4)),
                            (True, SimpleNamespace(speculator=None), SimpleNamespace(num_spec_tokens_to_schedule=4)),
                            (True, SimpleNamespace(), SimpleNamespace())):
        exec(code, {"_DSV41_NEXT_DRAFTS": on, "self": SimpleNamespace(model_runner=runner),
                    "scheduler_output": out})
    assert got == [3]


def test_dsv41_env_turns_the_trim_on_with_its_overlay() -> None:
    """The install: VLLM_DSPARK_REMOTE_N_OUT=window in the remote drafter env and the remote package + gpu_worker.py
    mounted from the same upstream-all stage (skipped before the install commit)."""
    env = DSV41_ENV.read_text()
    if "VLLM_DSPARK_REMOTE_N_OUT" not in env:
        pytest.skip("dsv41.env without the trim (before the install commit)")
    m = re.search(r'^OFFLOAD_DSPARK_ENV="([^"]*)"', env, re.M)
    assert m and "VLLM_DSPARK_REMOTE_N_OUT=window" in m.group(1).split()
    stage = re.search(r"^PROD_UPSTREAM_ALL=(\w+)", env, re.M)
    assert stage
    sid = stage.group(1)
    assert f"dsv41-upstream-all/{sid}/remote_dspark:" in env and f"dsv41-upstream-all/{sid}/dist/vllm/v1/worker/" \
        "gpu_worker.py:" in env
    manifest = ROOT / "offload/upstream_all/MANIFEST.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()[:12] == sid
    rows = {r["path"]: r for r in json.loads(manifest.read_text())["files"]}
    for rel in ("remote_dspark/roundcore.py", "remote_dspark/speculator.py", "dist/vllm/v1/worker/gpu_worker.py"):
        src = (NOUT / "overlay" / rel).read_bytes()
        assert rows[rel]["sha256"] == hashlib.sha256(src).hexdigest(), rel
    assert json.loads(manifest.read_text())["switches"]["VLLM_DSPARK_REMOTE_N_OUT"] == "window"
