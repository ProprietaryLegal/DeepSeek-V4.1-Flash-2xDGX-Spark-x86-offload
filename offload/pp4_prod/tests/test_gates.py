"""PP4 start gate and auto-rollback watch, against fake endpoints and fake probes (CPU only, no socket)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import cast

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import greedy_near_tie as g  # noqa: E402
import start_check as s  # noqa: E402
import watch as w  # noqa: E402

Json = dict[str, object]
PROMPTS = [f'prompt {i}' for i in range(6)]
REFS = [f'reference text {i} alpha beta' for i in range(6)]


def top20(**lps: float) -> dict[str, float]:
    """Twenty token-id keyed logprobs: the given ids, then filler tokens far below."""
    out = {f'token_id:{k[1:]}': v for k, v in lps.items()}
    filler = 1000
    while len(out) < 20:
        out[f'token_id:{filler}'] = -12.0 - filler / 1e4
        filler += 1
    return out


class FakeServe:
    """Greedy replies per prompt index; /tokenize splits on spaces into word-hash ids; the probe answers a top-20."""

    def __init__(self, replies: list[str], top: dict[str, float]) -> None:
        self.replies, self.top, self.calls = replies, top, 0

    def ids(self, text: str) -> list[int]:
        return [7 if word == 'alpha' else 8 if word == 'ALPHA' else 100 + len(word) for word in text.split()]

    def __call__(self, path: str, body: Json) -> Json:
        self.calls += 1
        if path == '/v1/chat/completions':
            i = PROMPTS.index(cast(list[Json], body['messages'])[0]['content'])  # type: ignore[arg-type]
            return {'choices': [{'message': {'content': self.replies[i]}}], 'usage': {'completion_tokens': 3}}
        if path == '/tokenize':
            if 'messages' in body:
                return {'tokens': [1, 2, 3]}
            return {'tokens': self.ids(str(body['prompt']))}
        if path == '/v1/completions':
            return {'choices': [{'logprobs': {'top_logprobs': [self.top]}}]}
        raise AssertionError(path)


def run(tmp: Path, replies: list[str], top: dict[str, float], runs: int = 1) -> tuple[bool, list[list[str]], Json]:
    out = tmp / 'g'
    out.mkdir(parents=True)
    ok, texts = g.check(FakeServe(replies, top), out, runs, REFS, PROMPTS, log=lambda line: None)
    return ok, texts, json.loads((out / 'greedy-near-tie.json').read_text())


def test_identical_rows_pass(tmp_path: Path) -> None:
    ok, texts, summary = run(tmp_path, list(REFS), top20(t7=-0.1))
    assert ok and summary['pass'] and all(r['verdict'] == 'IDENTICAL' for r in cast(list[Json], summary['rows']))


def test_a_near_tie_divergence_passes(tmp_path: Path) -> None:
    replies = list(REFS)
    replies[2] = 'reference text 2 ALPHA beta'          # first differing token: 7 (reference) vs 8 (run)
    ok, _, summary = run(tmp_path, replies, top20(t7=-0.40, t8=-0.90))
    row = cast(list[Json], summary['rows'])[2]
    assert ok and row['verdict'] == 'NEAR-TIE' and row['margin_nats'] == pytest.approx(0.5)


@pytest.mark.parametrize('top,why', [
    (top20(t7=-0.1, t8=-1.5), 'divergence exceeds 1.1 nats'),
    (top20(t5=-0.01, t7=-1.3, t8=-1.6), 'the better token is more than 1.1 nats below the top'),
    (top20(t7=-0.1), 'a differing token is outside the top 20'),
])
def test_a_real_divergence_fails(tmp_path: Path, top: dict[str, float], why: str) -> None:
    replies = list(REFS)
    replies[4] = 'reference text 4 ALPHA beta'
    ok, _, summary = run(tmp_path, replies, top)
    row = cast(list[Json], summary['rows'])[4]
    assert not ok and row['verdict'] == 'FAIL' and row['why'] == why


def test_strict_refuses_a_near_tie(tmp_path: Path) -> None:
    replies = list(REFS)
    replies[2] = 'reference text 2 ALPHA beta'
    out = tmp_path / 'g'
    out.mkdir()
    ok, _ = g.check(FakeServe(replies, top20(t7=-0.40, t8=-0.90)), out, 1, REFS, PROMPTS, log=lambda line: None, strict=True)
    summary = json.loads((out / 'greedy-near-tie.json').read_text())
    row = cast(list[Json], summary['rows'])[2]
    assert not ok and summary['registration'] == g.STRICT and row['verdict'] == 'FAIL' and row['near_tie'] is True
    assert row['why'] == 'strict: IDENTICAL to K1-post required (a near-tie)'
    (tmp_path / 'h').mkdir()
    assert g.check(FakeServe(list(REFS), top20(t7=-0.1)), tmp_path / 'h', 1, REFS, PROMPTS, log=lambda line: None,
                   strict=True)[0]


def test_exact_ceiling_with_rounding_allowance(tmp_path: Path) -> None:
    replies = list(REFS)
    replies[0] = 'reference text 0 ALPHA beta'
    assert run(tmp_path / 'a', replies, top20(t7=-0.0, t8=-1.1005))[0]
    assert not run(tmp_path / 'b', replies, top20(t7=-0.0, t8=-1.1020))[0]


def test_references_only_from_identical_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = tmp_path / 'refs.jsonl'
    ref.write_text(''.join(json.dumps({'i': i, 'text': t}) + '\n' for i, t in enumerate(REFS)))
    monkeypatch.setattr(g, 'prompts', lambda: PROMPTS)
    monkeypatch.setattr(g, 'http_post', lambda url: FakeServe(list(REFS), top20(t7=-0.1)))
    out_refs = tmp_path / 'pp4.jsonl'
    rc = g.main(['--url', 'http://x', '--out', str(tmp_path / 'o'), '--runs', '3', '--reference', str(ref),
                 '--references-out', str(out_refs)])
    assert rc == 0 and [json.loads(line)['text'] for line in out_refs.read_text().splitlines()] == REFS
    with pytest.raises(SystemExit, match='never overwritten'):
        g.main(['--url', 'http://x', '--out', str(tmp_path / 'o2'), '--reference', str(ref), '--references-out', str(out_refs)])


def test_unstable_runs_write_no_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = tmp_path / 'refs.jsonl'
    ref.write_text(''.join(json.dumps({'i': i, 'text': t}) + '\n' for i, t in enumerate(REFS)))
    serve = FakeServe(list(REFS), top20(t7=-0.4, t8=-0.5))
    flip = {'n': 0}

    def post(path: str, body: Json) -> Json:
        if path == '/v1/chat/completions' and cast(list[Json], body['messages'])[0]['content'] == PROMPTS[1]:
            flip['n'] += 1
            serve.replies[1] = REFS[1] if flip['n'] % 2 else 'reference text 1 ALPHA beta'
        return serve(path, body)
    monkeypatch.setattr(g, 'prompts', lambda: PROMPTS)
    monkeypatch.setattr(g, 'http_post', lambda url: post)
    out_refs = tmp_path / 'pp4.jsonl'
    assert g.main(['--url', 'x', '--out', str(tmp_path / 'o'), '--runs', '3', '--reference', str(ref),
                   '--references-out', str(out_refs)]) == 0
    assert not out_refs.exists()


def test_w5_prompts_are_read_from_the_pinned_file() -> None:
    if not g.GREEDY_SCRIPT.exists():
        pytest.skip('campaign W5 not mounted here')
    assert len(g.prompts()) == 6


# ---- start_check

METRICS = ('vllm:spec_decode_num_drafts_total{{engine="0"}} {d}\nvllm:spec_decode_num_draft_tokens_total {t}\n'
           'vllm:spec_decode_num_accepted_tokens_total {a}\nvllm:request_success_total{{finished_reason="length"}} {r}\n')


def smoke(tmp: Path, before: dict[str, int], after: dict[str, int]) -> bool:
    pages = [METRICS.format(**before), METRICS.format(**after)]

    def get(path: str) -> str:
        assert path == '/metrics'
        return pages.pop(0)

    def post(path: str, body: Json) -> Json:
        assert body['temperature'] == 1.0 and body['priority'] == 10
        return {'choices': [{'finish_reason': 'length'}], 'usage': {'completion_tokens': 128}}
    return s.smoke(get, post, tmp)


def test_smoke_passes_when_drafts_are_accepted(tmp_path: Path) -> None:
    assert smoke(tmp_path, dict(d=10, t=50, a=12, r=5), dict(d=300, t=1500, a=400, r=8))
    data = json.loads((tmp_path / 'sampled-smoke.json').read_text())
    assert data['accepted_per_round'] == pytest.approx(388 / 290)


def test_smoke_fails_on_target_only_rounds(tmp_path: Path) -> None:
    assert not smoke(tmp_path, dict(d=10, t=50, a=12, r=5), dict(d=300, t=1500, a=12, r=8))


def status(**kw: object) -> Json:
    base: Json = {'pid': 2, 'session': 99, 'steps': 40, 'drafted_requests': 40, 'tp': 2, 'tp_comm_errors': 0,
                  'tp_comm_errors_in_a_row': 0}
    base.update(kw)
    return base


@pytest.mark.parametrize('after,ok', [
    (status(), True),
    (status(pid=1), False),
    (status(session=11), False),
    (status(steps=0), False),
    (status(tp=1), False),
    (status(tp_comm_errors=1), False),
])
def test_worker_status_after_the_install(after: Json, ok: bool) -> None:
    before = status(pid=1, session=11, steps=900)
    assert s.worker(before, after)[0] is ok


@pytest.mark.parametrize('after,ok', [
    (status(pid=1, steps=950, drafted_requests=950, tp_comm_errors=2), True),
    (status(pid=1, steps=900, drafted_requests=950, tp_comm_errors=2), False),   # no step since the install
    (status(pid=2, steps=950, drafted_requests=950, tp_comm_errors=2), False),   # restarted underneath (a crash)
    (status(pid=1, session=11, steps=950, drafted_requests=950, tp_comm_errors=2), False),
    (status(pid=1, steps=950, drafted_requests=950, tp_comm_errors=3), False),
])
def test_same_worker_status_for_the_nout_layer(after: Json, ok: bool) -> None:
    before = status(pid=1, session=11, steps=900, drafted_requests=900, tp_comm_errors=2)
    assert s.worker(before, after, same=True)[0] is ok


# ---- watch

class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


class Probes:
    def __init__(self) -> None:
        self.serve_ok: list[bool] = []
        self.containers: dict[str, list[w.Container]] = {}
        self.errors: dict[str, list[list[str]]] = {}
        self.workers: list[w.Worker] = []
        self.inconclusive: set[str] = set()

    def serve(self) -> bool:
        return self.serve_ok.pop(0) if self.serve_ok else True

    def container(self, node: str) -> w.Container:
        if node in self.inconclusive:
            raise w.Inconclusive(f'{node}: ssh down')
        seq = self.containers.get(node, [])
        return seq.pop(0) if len(seq) > 1 else (seq[0] if seq else w.Container('c-' + node, True, False, 0, False))

    def engine_errors(self, node: str, since: str) -> list[str]:
        seq = self.errors.get(node, [])
        return seq.pop(0) if seq else []

    def worker(self) -> w.Worker:
        if 'x86host' in self.inconclusive:
            raise w.Inconclusive('x86host: ssh down')
        return self.workers.pop(0) if len(self.workers) > 1 else (self.workers[0] if self.workers else w.Worker(True, 0, 0))


def watch(p: Probes) -> tuple[str | None, list[str]]:
    clock = Clock()
    lines: list[str] = []
    result = w.watch(p, since='T', log=lines.append, clock=clock, sleep=clock.sleep)
    return result, lines


def test_healthy_watch_runs_thirty_polls() -> None:
    result, lines = watch(Probes())
    assert result is None and lines[-1] == 'WATCH PASS: 30 polls, no hard failure'


def test_serve_down_three_polls_in_a_row_is_hard() -> None:
    p = Probes()
    p.serve_ok = [True, False, False, True, False, False, False]
    result, _ = watch(p)
    assert result == 'serve unhealthy: /v1/models failed 3 polls in a row'


def test_two_serve_blips_are_not_hard() -> None:
    p = Probes()
    p.serve_ok = [False, False, True] * 10
    assert watch(p)[0] is None


@pytest.mark.parametrize('later,expect', [
    (w.Container('c-sparkworker-wired', True, False, 1, False), 'replaced or restarted'),
    (w.Container('other', True, False, 0, False), 'replaced or restarted'),
    (w.Container('c-sparkworker-wired', False, False, 0, False), 'running=False'),
    (w.Container('c-sparkworker-wired', True, False, 0, True), 'oom_killed=True'),
])
def test_container_changes_are_hard(later: w.Container, expect: str) -> None:
    p = Probes()
    p.containers['sparkworker-wired'] = [w.Container('c-sparkworker-wired', True, False, 0, False)] * 3 + [later]
    result, _ = watch(p)
    assert result is not None and result.startswith('sparkworker-wired: ') and expect in result


def test_engine_oom_line_is_hard() -> None:
    p = Probes()
    p.errors['sparkhead'] = [[], [], ['torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2 GiB']]
    result, _ = watch(p)
    assert result is not None and result.startswith('sparkhead: engine log: torch.OutOfMemoryError')


def test_engine_patterns() -> None:
    hard = ['RuntimeError: CUDA error: an illegal memory access was encountered', 'vllm.v1.engine.exceptions.EngineDeadError',
            '(EngineCore_DP0 pid=7) ERROR EngineCore encountered a fatal error.', 'NCCL error in: ...',
            'Fatal Python error: Segmentation fault', 'RuntimeError: Engine core proc EngineCore_DP0 died unexpectedly']
    soft = ['remote DSpark round failed (status 2); target-only round', 'INFO: tp_comm_errors 0', 'Avg generation throughput: 41.2 tokens/s',
            '(EngineCore_DP0 pid=7) INFO scheduler: 0 requests failed', '(EngineCore_DP0 pid=7) WARNING remote DSpark round failed']
    assert all(w.ENGINE_HARD.search(line) for line in hard)
    assert not any(w.ENGINE_HARD.search(line) for line in soft)


@pytest.mark.parametrize('workers,expect', [
    ([w.Worker(True, 0, 0), w.Worker(True, 1, 0)], 'restarted'),
    ([w.Worker(True, 0, 0), w.Worker(True, 0, 1)], 'tp_comm_errors rose 0->1'),
    ([w.Worker(True, 0, 0)] + [w.Worker(False, 0, 0)] * 3, 'not active on 3 polls'),
])
def test_worker_failures_are_hard(workers: list[w.Worker], expect: str) -> None:
    p = Probes()
    p.workers = workers
    result, _ = watch(p)
    assert result is not None and expect in result


def test_ssh_trouble_alone_is_inconclusive_not_hard() -> None:
    p = Probes()
    p.inconclusive = {'sparkworker-wired', 'x86host'}
    result, lines = watch(p)
    assert result is None and sum('INCONCLUSIVE' in line for line in lines) >= 30


def test_main_runs_the_rollback_once_on_a_hard_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(w, 'watch', lambda probes, **kw: 'serve unhealthy: test')

    class Done:
        returncode = 0

    def fake_run(argv: list[str], **kw: object) -> Done:
        calls.append(argv[-1])
        return Done()
    monkeypatch.setattr(subprocess, 'run', fake_run)
    rc = w.main(['--url', 'http://x', '--log', str(tmp_path / 'watch.log'), '--rollback', 'echo rollback'])
    assert rc == 3 and calls == ['echo rollback']
    assert 'AUTO-ROLLBACK DONE' in (tmp_path / 'watch.log').read_text()
