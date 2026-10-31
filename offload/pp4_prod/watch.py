#!/usr/bin/env python3
"""PP4-INSTALL: the 15-minute auto-rollback watch after the install (run on Controller, read-only probes).

Polls every 30 s for 15 minutes and rolls back ONLY on a hard failure, never on speed:
  serve      GET /v1/models fails (15 s timeout) on 3 polls in a row;
  container  dsv41-serve on either Spark is not running, restarting, OOM-killed, or its id / restart count changed since
             the watch started;
  engine     a new engine log line on either Spark (since the watch started) reports CUDA OOM, a CUDA error / illegal
             memory access, vLLM's fatal engine-core messages, an NCCL error or a segmentation fault;
  worker     the x86host TP2 unit is not active on 3 polls in a row, its restart count rose (a crash), or the worker's
             tp_comm_errors rose.
An ssh probe that cannot run is logged INCONCLUSIVE (never a failure by itself; the serve probe decides liveness).
On the first hard failure it runs the rollback command once and exits 3 (rollback done) or 4 (rollback failed: HOLD
stays, read the log). A clean watch exits 0.

    python3 offload/pp4_prod/watch.py --url URL --log FILE --rollback 'bash .../ROLLBACK.sh --execute --auto'
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import subprocess
import time
from typing import Callable, Protocol
import urllib.request

WATCH_S = 15 * 60
POLL_S = 30
STRIKES = 3
NODES = ('sparkhead', 'sparkworker-wired')
UNIT = 'dsv41-dspark-worker-tp2-prod.service'
STATUS = '~/dsv41-offload/prod/run/dspark-worker.status.json'
# vLLM's own fatal messages only: every line of the engine-core process carries an "(EngineCore_DP0 pid=…)" prefix, so
# a bare "EngineCore … failed" would match ordinary INFO lines
ENGINE_HARD = re.compile(r'CUDA out of memory|OutOfMemoryError|CUDA error|illegal memory access|EngineDeadError'
                         r'|EngineCore encountered a fatal error|Engine core proc [^\n]*died|EngineCore failed to start'
                         r'|NCCL error|Segmentation fault|core dumped')
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']


class Inconclusive(Exception):
    """A probe that could not run (ssh down, malformed reply): logged, never a failure by itself."""


@dataclass(frozen=True)
class Container:
    id: str
    running: bool
    restarting: bool
    restarts: int
    oom: bool


@dataclass(frozen=True)
class Worker:
    active: bool
    restarts: int
    tp_comm_errors: int


class Probes(Protocol):
    def serve(self) -> bool: ...
    def container(self, node: str) -> Container: ...
    def engine_errors(self, node: str, since: str) -> list[str]: ...
    def worker(self) -> Worker: ...


class Live:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip('/')

    def serve(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + '/v1/models', timeout=15) as r:
                return bool(json.load(r).get('data'))
        except (OSError, ValueError):
            return False

    def ssh(self, host: str, command: str) -> str:
        try:
            r = subprocess.run([*SSH, host, command], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Inconclusive(f'{host}: {exc}') from exc
        if r.returncode != 0:
            raise Inconclusive(f'{host}: rc {r.returncode}: {r.stderr.strip()[:200]}')
        return r.stdout

    def container(self, node: str) -> Container:
        out = self.ssh(node, "docker inspect -f '{{.Id}} {{.State.Running}} {{.State.Restarting}} {{.RestartCount}} "
                             "{{.State.OOMKilled}}' dsv41-serve").split()
        if len(out) != 5:
            raise Inconclusive(f'{node}: docker inspect reply {out!r}')
        return Container(out[0], out[1] == 'true', out[2] == 'true', int(out[3]), out[4] == 'true')

    def engine_errors(self, node: str, since: str) -> list[str]:
        text = self.ssh(node, f'docker logs --since {since} dsv41-serve 2>&1 | tail -n 20000')
        return [line[:300] for line in text.splitlines() if ENGINE_HARD.search(line)][:5]

    def worker(self) -> Worker:
        out = self.ssh('x86host', f'systemctl --user show -p ActiveState -p NRestarts --value {UNIT}; cat {STATUS}')
        lines = out.splitlines()
        if len(lines) < 3:
            raise Inconclusive(f'x86host: reply {out[:200]!r}')
        try:
            status = json.loads('\n'.join(lines[2:]))
            return Worker(lines[0] == 'active', int(lines[1]), int(status.get('tp_comm_errors', 0)))
        except (ValueError, TypeError) as exc:
            raise Inconclusive(f'x86host: {exc}') from exc


def watch(probes: Probes, *, since: str, log: Callable[[str], None], clock: Callable[[], float] = time.monotonic,
          sleep: Callable[[float], None] = time.sleep, duration: float = WATCH_S, interval: float = POLL_S) -> str | None:
    """Returns None after a clean watch, else the hard failure (the caller rolls back)."""
    base: dict[str, Container] = {}
    for node in NODES:
        try:
            base[node] = probes.container(node)
        except Inconclusive as exc:
            log(f'WATCH baseline {node} INCONCLUSIVE: {exc}')
    try:
        wbase: Worker | None = probes.worker()
    except Inconclusive as exc:
        wbase = None
        log(f'WATCH baseline worker INCONCLUSIVE: {exc}')
    log(f'WATCH START duration={duration:g}s interval={interval:g}s; containers '
        + ' '.join(f'{n}={c.id[:12]} restarts {c.restarts}' for n, c in base.items())
        + (f'; worker restarts {wbase.restarts} tp_comm_errors {wbase.tp_comm_errors}' if wbase else ''))
    serve_down = worker_down = polls = 0
    until = clock() + duration
    next_poll = clock()
    while clock() < until:
        if clock() < next_poll:
            sleep(min(next_poll - clock(), until - clock()))
            if clock() >= until:
                break
        polls += 1
        next_poll += interval
        notes: list[str] = []
        serve_down = 0 if probes.serve() else serve_down + 1
        if serve_down >= STRIKES:
            return f'serve unhealthy: /v1/models failed {serve_down} polls in a row'
        if serve_down:
            notes.append(f'/v1/models failed ({serve_down}/{STRIKES})')
        for node in NODES:
            try:
                c = probes.container(node)
                b = base.setdefault(node, c)
                if not c.running or c.restarting or c.oom:
                    return f'{node}: dsv41-serve running={c.running} restarting={c.restarting} oom_killed={c.oom}'
                if c.id != b.id or c.restarts != b.restarts:
                    return f'{node}: dsv41-serve replaced or restarted (id {b.id[:12]}->{c.id[:12]}, restarts {b.restarts}->{c.restarts})'
                errors = probes.engine_errors(node, since)
                if errors:
                    return f'{node}: engine log: ' + ' | '.join(errors)
            except Inconclusive as exc:
                notes.append(f'INCONCLUSIVE {exc}')
        try:
            w = probes.worker()
            if wbase is None:
                wbase = w
            worker_down = 0 if w.active else worker_down + 1
            if worker_down >= STRIKES:
                return f'x86host worker unit not active on {worker_down} polls in a row'
            if w.restarts > wbase.restarts:
                return f'x86host worker restarted (NRestarts {wbase.restarts}->{w.restarts}): a crash'
            if w.tp_comm_errors > wbase.tp_comm_errors:
                return f'x86host worker tp_comm_errors rose {wbase.tp_comm_errors}->{w.tp_comm_errors}'
            if not w.active:
                notes.append(f'worker not active ({worker_down}/{STRIKES})')
        except Inconclusive as exc:
            notes.append(f'INCONCLUSIVE {exc}')
        log(f'WATCH poll {polls}: ' + ('HEALTHY' if not notes else '; '.join(notes)))
    log(f'WATCH PASS: {polls} polls, no hard failure')
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', required=True)
    ap.add_argument('--log', required=True)
    ap.add_argument('--rollback', required=True, help='shell command run once on a hard failure')
    ap.add_argument('--duration', type=float, default=WATCH_S)
    a = ap.parse_args(argv)

    def log(line: str) -> None:
        text = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}"
        print(text, flush=True)
        with open(a.log, 'a') as f:
            f.write(text + '\n')
    since = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failure = watch(Live(a.url), since=since, log=log, duration=a.duration)
    if failure is None:
        return 0
    log(f'WATCH HARD FAILURE: {failure}; AUTO-ROLLBACK: {a.rollback}')
    rc = subprocess.run(['bash', '-c', a.rollback]).returncode
    log(f'AUTO-ROLLBACK {"DONE" if rc == 0 else f"FAILED rc {rc}: HOLD stays; finish by hand"}')
    return 3 if rc == 0 else 4


if __name__ == '__main__':
    raise SystemExit(main())
