#!/usr/bin/env python3
"""PP4-INSTALL start gate: the sampled drafting path works end to end (proposals arrive and are accepted).

    python3 offload/pp4_prod/start_check.py smoke --url URL --out DIR
        three short synthetic requests at T=1 (seeded, 128 tokens, priority 10); /metrics before and after: the server
        completed them, drafts were proposed and accepted (accepted draft tokens > 0, i.e. not target-only rounds).
    python3 offload/pp4_prod/start_check.py worker --before A.json --after B.json [--same-worker]
        the x86host worker's status file before and after the smoke: a session opened after the install (new id), steps
        and drafted requests advanced, TP = 2, no TP collective failure since the install. The PP4 layer restarts the
        worker (a new pid is required); the NOUT layer does not (--same-worker: the same pid, counters advanced past the
        before values, tp_comm_errors unchanged).
Exit 0 = PASS, 1 = FAIL. No generated text is kept (numbers only).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Callable, cast
import urllib.request

MODEL = 'DeepSeek-V4.1-Flash-1017-EXL3-Spark-TP2'
METRICS = ('vllm:spec_decode_num_drafts_total', 'vllm:spec_decode_num_draft_tokens_total',
           'vllm:spec_decode_num_accepted_tokens_total', 'vllm:request_success_total')
PROMPTS = ('Describe a quiet harbor town at dawn in five sentences.',
           'Write a short checklist for preparing a household budget.',
           'Explain how a bicycle gear system works, in plain words.')
Json = dict[str, object]


def metric_sums(text: str) -> dict[str, float]:
    """Sum of every series of each counter (all engines / labels)."""
    out = dict.fromkeys(METRICS, 0.0)
    for name in METRICS:
        for value in re.findall(r'^' + re.escape(name) + r'(?:\{[^\n]*\})?\s+([^\s]+)\s*$', text, re.M):
            out[name] += float(value)
    return out


def smoke(get: Callable[[str], str], post: Callable[[str, Json], Json], out: Path) -> bool:
    before = metric_sums(get('/metrics'))
    rows: list[Json] = []
    for i, prompt in enumerate(PROMPTS):
        r = post('/v1/chat/completions', {'model': MODEL, 'messages': [{'role': 'user', 'content': prompt}],
                                          'temperature': 1.0, 'top_p': 1.0, 'seed': 42 + i, 'max_tokens': 128,
                                          'priority': 10, 'chat_template_kwargs': {'thinking': False}})
        choice = cast(list[Json], r['choices'])[0]
        usage = cast(Json, r['usage'])
        rows.append({'i': i, 'finish_reason': choice.get('finish_reason'),
                     'completion_tokens': usage.get('completion_tokens')})
    after = metric_sums(get('/metrics'))
    delta = {k: after[k] - before[k] for k in METRICS}
    tokens = sum(int(cast(int, r['completion_tokens'] or 0)) for r in rows)
    ok = (tokens > 0 and delta['vllm:spec_decode_num_drafts_total'] > 0
          and delta['vllm:spec_decode_num_accepted_tokens_total'] > 0)
    result: Json = {'requests': rows, 'metric_delta': delta, 'completion_tokens': tokens, 'pass': ok,
                    'accepted_per_round': (delta['vllm:spec_decode_num_accepted_tokens_total']
                                           / delta['vllm:spec_decode_num_drafts_total'])
                    if delta['vllm:spec_decode_num_drafts_total'] else None}
    (out / 'sampled-smoke.json').write_text(json.dumps(result, indent=1) + '\n')
    print(f"SAMPLED SMOKE {'PASS' if ok else 'FAIL'}: {tokens} tokens over {len(rows)} T=1 requests; "
          f"rounds +{delta['vllm:spec_decode_num_drafts_total']:.0f}, proposed "
          f"+{delta['vllm:spec_decode_num_draft_tokens_total']:.0f}, accepted "
          f"+{delta['vllm:spec_decode_num_accepted_tokens_total']:.0f}")
    return ok


def worker(before: Json, after: Json, same: bool = False) -> tuple[bool, list[str]]:
    why: list[str] = []

    def n(status: Json, key: str) -> int:
        return int(cast(int, status.get(key, 0)))
    if after.get('tp') != 2:
        why.append(f"status tp {after.get('tp')!r}, expected 2")
    if same and after.get('pid') != before.get('pid'):
        why.append('the worker process changed during an install that does not touch it (a crash/restart)')
    if not same and after.get('pid') == before.get('pid'):
        why.append('the worker process did not change since before the install (not restarted with the drop-in)')
    if not isinstance(after.get('session'), int) or after.get('session') == before.get('session'):
        why.append('no session opened since the install')
    def floor(key: str) -> int:  # same worker: counters only grow from their pre-install values
        return n(before, key) if same else 0
    if n(after, 'steps') <= floor('steps'):
        why.append('no drafting steps since the install')
    if n(after, 'drafted_requests') <= floor('drafted_requests'):
        why.append('no drafted requests since the install')
    if n(after, 'tp_comm_errors') != floor('tp_comm_errors') or n(after, 'tp_comm_errors_in_a_row') != 0:
        why.append(f"TP collective failures: {after.get('tp_comm_errors')} ({after.get('tp_comm_errors_in_a_row')} in a row)")
    return not why, why


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='what', required=True)
    s = sub.add_parser('smoke')
    s.add_argument('--url', required=True)
    s.add_argument('--out', type=Path, required=True)
    w = sub.add_parser('worker')
    w.add_argument('--before', type=Path, required=True)
    w.add_argument('--after', type=Path, required=True)
    w.add_argument('--same-worker', action='store_true')
    a = ap.parse_args(argv)
    if a.what == 'smoke':
        base = str(a.url).rstrip('/')

        def get(path: str) -> str:
            with urllib.request.urlopen(base + path, timeout=30) as r:
                return cast(bytes, r.read()).decode()

        def post(path: str, body: Json) -> Json:
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=600) as r:
                value: Json = json.load(r)
                return value
        a.out.mkdir(parents=True, exist_ok=True)
        try:
            return 0 if smoke(get, post, a.out) else 1
        except (OSError, ValueError, KeyError, IndexError) as exc:
            print(f'SAMPLED SMOKE FAIL: {type(exc).__name__}: {exc}')
            return 1
    ok, why = worker(json.loads(a.before.read_text()), json.loads(a.after.read_text()), a.same_worker)
    after = json.loads(a.after.read_text())
    print(f"PP4 WORKER DRAFTING {'PASS' if ok else 'FAIL'}: session {after.get('session')}, steps {after.get('steps')}, "
          f"drafted {after.get('drafted_requests')}, tp {after.get('tp')}, tp_comm_errors {after.get('tp_comm_errors')}"
          + ('' if ok else ' | ' + '; '.join(why)))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
