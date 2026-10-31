#!/usr/bin/env python3
"""PP4-INSTALL start gate: the six W5 greedy prompts against K1-post under the approved 1.1-nat near-tie rule.

PP4 verifies a fixed window of 5, which moves where near-tied tokens fall, so greedy identity with K1-post cannot be
required: the qualified admission (same bytes, on 596ba1c) gave 1 IDENTICAL and 5 near-ties (0.0-1.0 nats). Each row
of each run must be IDENTICAL to K1-post, or its first differing token must be a near-tie under registration
pp4-r14-near-tie-1p1 (PP4-PROMOTE pp4_cells.near_tie_values): both tokens in the target's top 20 at that position,
|logprob difference| <= 1.1 nats + 1e-3, and the better of the two within 1.1 nats + 1e-3 of the top token.

Requests are W5/greedy_check.py's (same prompts and body: T=0, 300 tokens, thinking off); the probe is the PP4 one
(/tokenize, then one max_tokens=1 completion with top-20 logprobs on the common token prefix). Synthetic prompts only.

    python3 offload/pp4_prod/greedy_near_tie.py --url URL --out DIR [--runs 3] [--strict] [--references-out PATH]

--strict (the nout layer, L1 = P + NOUT-TRIM): every row of every run must be IDENTICAL to K1-post; no near-tie
allowance. NOUT only trims what the worker sends back (S116: byte-identical on the same trajectory) and P's own W8
requires six IDENTICAL, so a divergence under L1 is a fault, not a near-tie. A differing row is still probed, for the
record only.

--references-out writes the runs' outputs as PP4 greedy references (W5 jsonl) only if every run agrees byte for byte;
it never overwrites. Exit 0 = PASS, 1 = a row fails the rule, 2 = a request failed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable, cast
import urllib.request

CAMPAIGN = Path('/opt/dsv41/campaigns/DSV41-OFFLOAD')
GREEDY_SCRIPT = CAMPAIGN / 'W5/greedy_check.py'
GREEDY_SHA256 = 'e40c52c0e9ab13d46df9b9cf49020ad87034d8651e4585e741b5eb14ef4f0845'
REFERENCE = CAMPAIGN / 'K1-production/greedy-post.jsonl'
REGISTRATION = 'pp4-r14-near-tie-1p1'
STRICT = 'strict-identity'
NEAR_TIE_NATS = 1.1 + 1e-3   # NDM's 1.1-nat ceiling for the drafting fix, with NBW's rounding allowance
MODEL = 'DeepSeek-V4.1-Flash-1017-EXL3-Spark-TP2'
Json = dict[str, object]
Post = Callable[[str, Json], Json]


def http_post(url: str) -> Post:
    def post(path: str, body: Json) -> Json:
        req = urllib.request.Request(url.rstrip('/') + path, json.dumps(body).encode(),
                                     {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as r:
            value: Json = json.load(r)
            return value
    return post


def prompts() -> list[str]:
    """W5's PROMPTS, read from the pinned file (never imported: no code from the campaign directory runs here)."""
    data = GREEDY_SCRIPT.read_bytes()
    if hashlib.sha256(data).hexdigest() != GREEDY_SHA256:
        raise SystemExit('W5/greedy_check.py changed; refusing')
    found = [n for n in ast.parse(data).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'PROMPTS' for t in n.targets)]
    value = ast.literal_eval(found[0].value) if len(found) == 1 else None
    if not (isinstance(value, list) and len(value) == 6 and all(isinstance(p, str) for p in value)):
        raise SystemExit('six greedy PROMPTS required')
    return cast(list[str], value)


def references(path: Path) -> list[str]:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if [r.get('i') for r in rows] != list(range(6)) or not all(isinstance(r.get('text'), str) for r in rows):
        raise SystemExit(f'{path}: six ordered reference outputs required')
    return [str(r['text']) for r in rows]


def generate(post: Post, prompt: str) -> tuple[str, Json]:
    body: Json = {'model': MODEL, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0,
                  'max_tokens': 300, 'chat_template_kwargs': {'thinking': False}}
    r = post('/v1/chat/completions', body)
    choice = cast(list[Json], r['choices'])[0]
    text = cast(Json, choice['message'])['content']
    if not isinstance(text, str):
        raise ValueError('greedy reply has no text')
    return text, cast(Json, r.get('usage', {}))


def near_tie_values(top: dict[str, float], reference_id: int, run_id: int) -> Json:
    """PP4-PROMOTE pp4_cells.near_tie_values (registration pp4-r14-near-tie-1p1), returning its verdict."""
    out: Json = {'reference_token_id': reference_id, 'run_token_id': run_id, 'near_tie': False}
    if len(top) != 20 or not all(k.startswith('token_id:') and k[9:].isdigit() for k in top):
        out['why'] = 'exactly twenty token-id keyed top-logprob entries required'
        return out
    lps = {int(k[9:]): float(v) for k, v in top.items()}
    if len(lps) != 20 or not all(-9999 < v <= 0 for v in lps.values()):
        out['why'] = 'duplicate, clamped or invalid top-20 logprobs'
        return out
    if reference_id not in lps or run_id not in lps:
        out['why'] = 'a differing token is outside the top 20'
        return out
    a, b, best = lps[reference_id], lps[run_id], max(lps.values())
    out.update(margin_nats=abs(a - b), gap_to_top_nats=best - max(a, b), run_gap_to_top_nats=best - b)
    if abs(a - b) > NEAR_TIE_NATS:
        out['why'] = 'divergence exceeds 1.1 nats'
    elif best - max(a, b) > NEAR_TIE_NATS:
        out['why'] = 'the better token is more than 1.1 nats below the top'
    else:
        out['near_tie'] = True
    return out


def tokens(post: Post, body: Json) -> list[int]:
    value = post('/tokenize', {'model': MODEL, **body})['tokens']
    if not (isinstance(value, list) and all(isinstance(t, int) for t in value)):
        raise ValueError('tokenize returned no token ids')
    return cast(list[int], value)


def probe(post: Post, prompt: str, reference: str, text: str) -> Json:
    p = tokens(post, {'messages': [{'role': 'user', 'content': prompt}], 'add_generation_prompt': True,
                      'chat_template_kwargs': {'thinking': False}})
    ta = tokens(post, {'prompt': reference, 'add_special_tokens': False})
    tb = tokens(post, {'prompt': text, 'add_special_tokens': False})
    index = next((k for k, (u, v) in enumerate(zip(ta, tb)) if u != v), None)
    if index is None:
        return {'near_tie': False, 'why': 'no differing token: a pure prefix difference'}
    r = post('/v1/completions', {'model': MODEL, 'prompt': [*p, *ta[:index]], 'max_tokens': 1, 'temperature': 0,
                                 'logprobs': 20, 'return_tokens_as_token_ids': True, 'priority': 10})
    choice = cast(list[Json], r['choices'])[0]
    top = cast(list[dict[str, float]], cast(Json, choice['logprobs'])['top_logprobs'])[0]
    return {'token_index': index, **near_tie_values(top, ta[index], tb[index])}


def check(post: Post, out: Path, runs: int, reference: list[str], ask: list[str],
          log: Callable[[str], None] = print, strict: bool = False) -> tuple[bool, list[list[str]]]:
    texts: list[list[str]] = []
    ok = True
    summary: list[Json] = []
    for run in range(runs):
        rows: list[str] = []
        with (out / f'run-{run + 1}.jsonl').open('x') as f:
            for i, prompt in enumerate(ask):
                text, usage = generate(post, prompt)
                rows.append(text)
                f.write(json.dumps({'i': i, 'text': text, 'usage': usage}) + '\n')
                row: Json = {'run': run + 1, 'i': i, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
                if text == reference[i]:
                    row['verdict'] = 'IDENTICAL'
                    log(f'run {run + 1} greedy {i} IDENTICAL {len(text)}')
                else:
                    row.update(probe(post, prompt, reference[i], text))
                    row['verdict'] = 'NEAR-TIE' if row.get('near_tie') and not strict else 'FAIL'
                    if strict:
                        row['why'] = 'strict: IDENTICAL to K1-post required' + (' (a near-tie)' if row.get('near_tie') else '')
                    ok = ok and row['verdict'] == 'NEAR-TIE'
                    log(f"run {run + 1} greedy {i} {row['verdict']} token {row.get('token_index')} margin "
                        f"{row.get('margin_nats')} gap {row.get('gap_to_top_nats')}{' (' + str(row['why']) + ')' if 'why' in row else ''}")
                summary.append(row)
        texts.append(rows)
    stable = all(t == texts[0] for t in texts)
    (out / 'greedy-near-tie.json').write_text(json.dumps(
        {'registration': STRICT if strict else REGISTRATION, 'reference': str(REFERENCE), 'runs': runs, 'pass': ok,
         'runs_identical_to_each_other': stable, 'rows': summary}, indent=1) + '\n')
    return ok, texts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--reference', type=Path, default=REFERENCE)
    ap.add_argument('--references-out', type=Path)
    ap.add_argument('--strict', action='store_true', help='identity with K1-post on every row (the nout layer)')
    a = ap.parse_args(argv)
    if a.runs < 1:
        raise SystemExit('--runs must be at least 1')
    if a.references_out is not None and a.references_out.exists():
        raise SystemExit(f'{a.references_out} exists; never overwritten')
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        ok, texts = check(http_post(a.url), a.out, a.runs, references(a.reference), prompts(), strict=a.strict)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(f'GREEDY NEAR-TIE ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    rule = STRICT if a.strict else REGISTRATION
    if not ok:
        print(f'GREEDY NEAR-TIE FAIL ({rule}); see {a.out}/greedy-near-tie.json')
        return 1
    print(f"GREEDY NEAR-TIE PASS ({rule}): {a.runs} run(s) x 6 rows {'IDENTICAL' if a.strict else 'IDENTICAL or near-tie'} vs K1-post")
    if a.references_out is not None:
        if all(t == texts[0] for t in texts):
            with a.references_out.open('x') as f:
                for i, text in enumerate(texts[0]):
                    f.write(json.dumps({'i': i, 'text': text}) + '\n')
            print(f'PP4 GREEDY REFERENCES WRITTEN {a.references_out} ({a.runs} identical runs)')
        else:
            print('PP4 GREEDY REFERENCES NOT WRITTEN: the runs differ from each other (identity cannot be the W8 rule)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
