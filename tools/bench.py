#!/usr/bin/env python3
"""Speed benchmark for an OpenAI-compatible server, with JSON output and a compare mode.

It measures two sets of conditions so numbers from different DGX Spark recipes can be put side by side:

  profile "mia"   the conditions of the MiaAI-Lab TensorFold recipe's headline table: temperature 0, thinking off,
                  a prose prompt and a code prompt, 1 / 2 / 3 / 4 streams released together, 512 tokens out, natural
                  end of reply allowed; plus its second row (prose, temperature 0.7, thinking on); plus cold prefill of
                  4K / 8K / 16K / 32K / 64K / 128K / 256K-token prompts (thinking off, 1 token out).
  profile "ours"  the conditions of this repository's speed record: temperature 1 (seed 42 + repeat), thinking on
                  (effort "high"), exactly 512 tokens out (ignore_eos), priority 10, cold prompts of ~1K ("short"),
                  32K and 150K tokens, at 1 stream (short, 32K, 150K) and 3 / 4 concurrent 32K streams.

Every prompt is synthetic and generated here from --seed (no data files, nothing private). Each request gets a fresh
random cache_salt and a salt line at the top of its prompt, so no request can read another's prefix cache. Generated
text is never stored: the JSON keeps token counts, timings and a sha256 of each reply.

    python3 -I tools/bench.py plan --profile all                       # the request list and its estimated duration
    python3 -I tools/bench.py run --profile all --out runs/x.json --label x [--url http://host:8000]
    python3 -I tools/bench.py compare runs/a.json runs/b.json          # per-cell table, no server needed

Definitions (the same as the MiaAI recipe's tools/bench.py so the columns mean the same thing):
  TTFT            request sent -> first streamed token (reasoning or content)
  prefill tok/s   (prompt tokens - cached prompt tokens) / TTFT
  decode tok/s    (completion tokens - 1) / (last token time - first token time), per stream
  aggregate tok/s all completion tokens of a group / (last token anywhere - first token anywhere)
  accepted/round  from /metrics deltas (vLLM spec-decode counters): accepted draft tokens / drafting rounds, per cell

Integrity: before each group the server must be idle (vllm:num_requests_running and _waiting both 0, --idle-wait);
after it, the /metrics prompt- and generation-token deltas must match what this tool sent (a foreign request marks the
group "foreign_traffic": true). --stop-file ends the run cleanly after the current group. Exit 0 = every request
completed, 1 = some failed, 2 = usage error, 3 = server not idle / stopped early (partial JSON is still written).
Stdlib only, Python 3.10+."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import secrets
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA = 'pli-bench/1'
VERSION = '1.0.0'

PROSE = ('Write a long, detailed essay on the history of lighthouses and the people who kept them: how the towers '
         'were built, how their lamps and lenses worked, what daily life at a remote station was like, and how '
         'coastal navigation changed once the lights were automated. Write in full paragraphs, without lists or '
         'headings.')
CODE = ('Write a complete, well-commented Python module that implements a thread-safe LRU cache with per-entry time '
        'expiry, a decorator that applies the cache to functions, and unittest test cases that cover eviction order, '
        'expiry and concurrent access. Output only the code.')
LONG_HEAD = ('SYNTHETIC RECORDS BENCHMARK. The records below are machine-generated and fictional. Summarize them, '
             'compare the recurring themes and point out inconsistencies between records, using only the records.\n\n')
SHORT_HEAD = ('Read the synthetic records below (machine-generated, fictional) and write a careful analytical summary '
              'of what they report, with the most important figures.\n\n')


# ---------------------------------------------------------------------------------------------------------------------
# Synthetic text: varied, non-repeating sentences from templates; deterministic for a seed.

_NOUNS = ('harbor', 'bridge', 'library', 'orchard', 'canal', 'market', 'school', 'railway', 'clinic', 'reservoir',
          'mill', 'quarry', 'ferry', 'archive', 'garden', 'foundry', 'depot', 'museum', 'observatory', 'granary',
          'tannery', 'brewery', 'workshop', 'theater', 'warehouse', 'tunnel', 'dam', 'pier', 'station', 'forest',
          'vineyard', 'pasture', 'marsh', 'aqueduct', 'printworks', 'shipyard', 'bakery', 'kiln', 'lock', 'weir')
_ADJS = ('northern', 'old', 'new', 'eastern', 'upper', 'lower', 'central', 'western', 'southern', 'municipal',
         'regional', 'coastal', 'inland', 'rebuilt', 'seasonal', 'temporary', 'restored', 'historic', 'small', 'large')
_VERBS = ('reported', 'recorded', 'estimated', 'measured', 'counted', 'logged', 'noted', 'published', 'listed',
          'confirmed')
_UNITS = ('visitors', 'tonnes of grain', 'kilometres of track', 'liters of water', 'crates', 'passengers', 'volumes',
          'trees', 'workers', 'repairs', 'shipments', 'inspections', 'complaints', 'permits', 'lamps')
_MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
           'November', 'December')
_CMP = ('higher', 'lower', 'slightly higher', 'slightly lower', 'about the same', 'well above', 'well below')
_CAUSE = ('a dry spring', 'a late frost', 'new staff', 'a road closure', 'a fire in the east wing', 'a flood',
          'a change of schedule', 'higher fees', 'a festival', 'a strike at the port', 'a new tram line', 'snow')
_SYL = ('ka', 'lo', 'ren', 'vi', 'tor', 'mal', 'si', 'ber', 'an', 'qu', 'el', 'dor', 'fa', 'nis', 'ost', 'ul', 'ga',
        'mer', 'pa', 'tin', 'wes', 'ro', 'ha', 'lin', 'cor', 'bel', 'dun', 'eth', 'ira', 'som')
_TEMPLATES = (
    'The {adj} {noun} of {place} {verb} {num} {unit} in {month} {year}, {cmp} than the year before.',
    'According to the {noun} office in {place}, {num} {unit} were {verb2} between {month} and {month2}.',
    'In {year} the {adj} {noun} near {place} closed for {small} weeks after {cause}.',
    'Record {rid}: {place} {noun}, {num} {unit}, inspector {person}, status {status}.',
    '{person} of {place} wrote that the {noun} had {num} {unit} on hand, although the {adj} ledger shows {num2}.',
    'The council of {place} approved {money} for the {adj} {noun}; work began in {month} and ended in {month2} {year}.',
    'Between {year} and {year2}, {unit} at the {noun} of {place} rose from {num} to {num2}.',
    'A survey of the {noun} in {place} found {small} problems, the most serious caused by {cause}.',
    'The {adj} {noun} at {place} reopened on {day} {month} with {num} {unit} and {small} new rules.',
    'Officials in {place} {verb} that {cause} delayed the {noun} by {small} days, at a cost of {money}.',
    'Note {rid} says the {noun} of {place} {verb} {num} {unit}; note {rid2} gives {num2} for the same month.',
    '{person} kept the {noun} at {place} for {small} years and {verb} {num} {unit} in the last one.',
)


class Synth:
    """Synthetic records: every call continues one deterministic stream, so no two prompts share text."""

    def __init__(self, seed: int) -> None:
        self.r = random.Random(seed)

    def _name(self, n: int) -> str:
        return ''.join(self.r.choice(_SYL) for _ in range(n)).capitalize()

    def sentence(self) -> str:
        r = self.r
        y = r.randint(1890, 2025)
        return r.choice(_TEMPLATES).format(
            adj=r.choice(_ADJS), noun=r.choice(_NOUNS), place=self._name(r.randint(2, 3)), verb=r.choice(_VERBS),
            verb2=r.choice(_VERBS), num=f'{r.randint(3, 98000):,}', num2=f'{r.randint(3, 98000):,}', unit=r.choice(_UNITS),
            month=r.choice(_MONTHS), month2=r.choice(_MONTHS), year=y, year2=y + r.randint(1, 30), cmp=r.choice(_CMP),
            small=r.randint(2, 19), cause=r.choice(_CAUSE), rid=f'{r.randint(100, 99999)}-{r.choice("ABCDEFGHK")}',
            rid2=f'{r.randint(100, 99999)}-{r.choice("ABCDEFGHK")}', person=f'{self._name(2)} {self._name(3)}',
            status=r.choice(('open', 'closed', 'pending', 'referred')), money=f'${r.randint(2, 900) * 1000:,}',
            day=r.randint(1, 28))

    def text(self, chars: int) -> str:
        out: list[str] = []
        n = 0
        while n < chars:
            para = ' '.join(self.sentence() for _ in range(self.r.randint(3, 7)))
            out.append(para)
            n += len(para) + 2
        return '\n\n'.join(out)[:chars]


# ---------------------------------------------------------------------------------------------------------------------
# The plan: cells -> groups of concurrent requests.

@dataclass(frozen=True)
class Cell:
    id: str                 # e.g. mia/decode/prose/t0/s2, ours/32k-b3
    profile: str
    suite: str              # decode | prefill | long
    kind: str               # prose | code | records
    streams: int
    target_tokens: int      # prompt size (0 = the short instruction itself)
    max_tokens: int
    temperature: float
    thinking: bool
    effort: str | None
    ignore_eos: bool
    priority: int | None
    reps: int
    seeded: bool            # seed = 42 + rep (ours) instead of a fixed seed


def build_plan(profiles: list[str], reps_mia: int, reps_prefill: int, reps_ours: int,
               prefill_sizes: list[int], streams: list[int]) -> list[Cell]:
    cells: list[Cell] = []
    if 'mia' in profiles:
        for kind, temp, think in (('prose', 0.0, False), ('code', 0.0, False), ('prose', 0.7, True)):
            for s in streams:
                tag = 't0' if temp == 0 else 't07-think'
                cells.append(Cell(f'mia/decode/{kind}/{tag}/s{s}', 'mia', 'decode', kind, s, 0, 512, temp, think,
                                  None, False, None, reps_mia, False))
        for size in prefill_sizes:
            cells.append(Cell(f'mia/prefill/{size // 1024}k', 'mia', 'prefill', 'records', 1, size, 1, 0.0, False,
                              None, False, None, reps_prefill, False))
    if 'ours' in profiles:
        for name, size, s in (('short-b1', 1024, 1), ('32k-b1', 32000, 1), ('32k-b3', 32000, 3), ('32k-b4', 32000, 4),
                              ('150k-b1', 150000, 1)):
            cells.append(Cell(f'ours/{name}', 'ours', 'long', 'records', s, size, 512, 1.0, True, 'high', True, 10,
                              reps_ours, True))
    return cells


# Rate model for the duration estimate only (MEASURED on this repository's production, 2026-10-28 speed record:
# cold 32K TTFT 12.3 s, 150K 57.6 s; decode 57 tok/s at 1 stream, ~30 / ~27 tok/s per stream at 3 / 4).
def est_ttft(tokens: int, concurrent: int) -> float:
    if tokens <= 0:
        return 0.8
    one = tokens / 2600.0 * (1 + tokens / 1_500_000)
    return one * (concurrent + 1) / 2 + 0.5        # concurrent prompts prefill one after another; mean wait


def est_decode_rate(streams: int, thinking: bool) -> float:
    base = {1: 57.0, 2: 42.0, 3: 30.0, 4: 27.0}.get(streams, 25.0)
    return base * (0.95 if thinking else 1.0)


def estimate_group_s(c: Cell) -> float:
    if c.suite == 'prefill':
        return est_ttft(c.target_tokens, 1) + 2.0
    last_ttft = (c.target_tokens / 2600.0 * (1 + c.target_tokens / 1_500_000)) * c.streams + 0.8 if c.target_tokens \
        else 0.8 + 0.1 * c.streams
    return last_ttft + c.max_tokens / est_decode_rate(c.streams, c.thinking) + 2.0


# ---------------------------------------------------------------------------------------------------------------------
# HTTP

class Api:
    def __init__(self, url: str, timeout: float, api_key: str | None) -> None:
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.headers = {'Content-Type': 'application/json'}
        if api_key:
            self.headers['Authorization'] = f'Bearer {api_key}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path: str, timeout: float = 30) -> bytes:
        req = urllib.request.Request(self.url + path, headers=self.headers)
        with self.opener.open(req, timeout=timeout) as r:
            return r.read()

    def post(self, path: str, body: dict, timeout: float | None = None):
        req = urllib.request.Request(self.url + path, json.dumps(body).encode(), self.headers)
        return self.opener.open(req, timeout=timeout or self.timeout)

    def model(self) -> str:
        return json.loads(self.get('/v1/models'))['data'][0]['id']

    def metrics(self) -> dict[str, float] | None:
        try:
            text = self.get('/metrics').decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001 - metrics are optional
            return None
        out: dict[str, float] = {}
        for line in text.splitlines():
            if not line or line[0] == '#':
                continue
            m = re.match(r'([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eEinfNa]+)', line)
            if not m or m.group(1).endswith(('_bucket', '_created')):
                continue
            try:
                out[m.group(1)] = out.get(m.group(1), 0.0) + float(m.group(3))
            except ValueError:
                pass
        return out

    def count_tokens(self, model: str, content: str) -> int | None:
        try:
            with self.post('/tokenize', {'model': model, 'messages': [{'role': 'user', 'content': content}],
                                         'add_generation_prompt': True}, timeout=120) as r:
                d = json.loads(r.read())
            return int(d.get('count') or len(d.get('tokens') or []))
        except Exception:  # noqa: BLE001 - not every server has /tokenize
            return None


def _metric(m: dict[str, float] | None, *names: str) -> float | None:
    if m is None:
        return None
    for n in names:
        for k in (n, n + '_total'):
            if k in m:
                return m[k]
    return None


RUNNING = ('vllm:num_requests_running',)
WAITING = ('vllm:num_requests_waiting',)
PROMPT_TOK = ('vllm:prompt_tokens',)
GEN_TOK = ('vllm:generation_tokens',)
DRAFTS = ('vllm:spec_decode_num_drafts',)
DRAFT_TOK = ('vllm:spec_decode_num_draft_tokens',)
ACCEPTED = ('vllm:spec_decode_num_accepted_tokens',)


def metric_delta(a: dict[str, float] | None, b: dict[str, float] | None) -> dict[str, float] | None:
    if a is None or b is None:
        return None
    keep = re.compile(r'(spec_decode|prefix_cache|prompt_tokens|generation_tokens|external|kv_connector|preempt'
                      r'|num_requests_success|request_success)')
    return {k: b[k] - a.get(k, 0.0) for k in sorted(b) if keep.search(k) and k.endswith('_total') and b[k] != a.get(k, 0.0)}


# ---------------------------------------------------------------------------------------------------------------------
# One request

@dataclass
class Result:
    stream: int
    prompt_sha256: str
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    ttft_s: float | None = None
    prefill_tok_s: float | None = None
    decode_tok_s: float | None = None
    total_s: float | None = None
    finish_reason: str | None = None
    output_sha256: str | None = None
    error: str | None = None
    resp: object = field(default=None, repr=False)
    t_first: float | None = field(default=None, repr=False)
    t_last: float | None = field(default=None, repr=False)


def stream_request(api: Api, body: dict, gate: threading.Barrier | None, res: Result) -> None:
    if gate is not None:
        gate.wait()
    t0 = time.monotonic()
    first = last = None
    usage = None
    finish = None
    digest = hashlib.sha256()
    try:
        with api.post('/v1/chat/completions', body) as resp:
            res.resp = resp
            for raw in resp:
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                ev = json.loads(data)
                if ev.get('usage'):
                    usage = ev['usage']
                for ch in ev.get('choices') or []:
                    delta = ch.get('delta') or {}
                    piece = (delta.get('reasoning_content') or delta.get('reasoning') or '') + (delta.get('content') or '')
                    if piece:
                        now = time.monotonic()
                        first = first or now
                        last = now
                        digest.update(piece.encode())
                    finish = ch.get('finish_reason') or finish
    except urllib.error.HTTPError as exc:
        res.error = f'HTTP {exc.code}: {exc.read().decode(errors="replace")[:200]}'
        return
    except Exception as exc:  # noqa: BLE001 - a benchmark reports, it does not crash
        res.error = f'{type(exc).__name__}: {exc}'[:300]
        return
    end = time.monotonic()
    if first is None or usage is None:
        res.error = f'no tokens or no usage chunk (usage={usage is not None})'
        return
    pt = int(usage.get('prompt_tokens') or 0)
    ct = int(usage.get('completion_tokens') or 0)
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    res.prompt_tokens, res.completion_tokens, res.cached_tokens = pt, ct, cached
    res.ttft_s = first - t0
    res.prefill_tok_s = (pt - (cached or 0)) / res.ttft_s if res.ttft_s > 0 else None
    res.decode_tok_s = (ct - 1) / (last - first) if ct > 1 and last > first else None
    res.total_s = end - t0
    res.finish_reason = finish
    res.output_sha256 = digest.hexdigest()
    res.t_first, res.t_last = first, last


# ---------------------------------------------------------------------------------------------------------------------
# Runner

class Stop(Exception):
    pass


class Runner:
    def __init__(self, a: argparse.Namespace) -> None:
        self.a = a
        self.api = Api(a.url, a.timeout, os.environ.get('API_KEY') or None)
        self.model = a.model or self.api.model()
        self.chars_per_token = 3.6
        self.synth_seed = a.seed

    def calibrate(self) -> dict:
        sample = Synth(self.synth_seed ^ 0x5EED).text(40000)
        n = self.api.count_tokens(self.model, sample)
        if n:
            base = self.api.count_tokens(self.model, '') or 0
            self.chars_per_token = len(sample) / max(1, n - base)
        return {'tokenize': n is not None, 'chars_per_token': round(self.chars_per_token, 4)}

    def prompt(self, c: Cell, rep: int, stream: int) -> tuple[str, str]:
        salt = secrets.token_hex(8)
        head = f'Request {salt}.\n\n'
        if c.suite == 'decode':
            return head + (PROSE if c.kind == 'prose' else CODE), salt
        seed = int.from_bytes(hashlib.sha256(f'{self.synth_seed}|{c.id}|{rep}|{stream}'.encode()).digest()[:8], 'big')
        intro = SHORT_HEAD if c.target_tokens < 4096 else LONG_HEAD
        body = Synth(seed).text(max(0, int(c.target_tokens * self.chars_per_token) - len(intro) - len(head)))
        text = head + intro + body
        if self.a.exact_size:
            n = self.api.count_tokens(self.model, text)
            if n:
                excess = n - c.target_tokens
                if excess > 0:
                    text = text[:max(len(head) + len(intro), len(text) - int(excess * self.chars_per_token) - 8)]
                elif excess < -16:
                    text += '\n\n' + Synth(seed + 1).text(int(-excess * self.chars_per_token))
        return text, salt

    def body(self, c: Cell, rep: int, text: str, salt: str) -> dict:
        kw: dict = {'thinking': c.thinking, 'enable_thinking': c.thinking}
        if c.thinking and c.effort:
            kw['reasoning_effort'] = c.effort
        b = {'model': self.model, 'messages': [{'role': 'user', 'content': text}], 'max_tokens': c.max_tokens,
             'temperature': c.temperature, 'top_p': 1.0, 'seed': (42 + rep) if c.seeded else self.a.seed,
             'stream': True, 'stream_options': {'include_usage': True}, 'chat_template_kwargs': kw}
        if not self.a.no_cache_salt:
            b['cache_salt'] = salt
        if c.ignore_eos:
            b['ignore_eos'] = True
        if c.priority is not None and not self.a.no_priority:
            b['priority'] = c.priority
        return b

    def wait_idle(self) -> bool | None:
        if self.a.no_idle_check:
            return None
        deadline = time.monotonic() + self.a.idle_wait
        while True:
            m = self.api.metrics()
            if m is None:
                return None
            if (_metric(m, *RUNNING) or 0) == 0 and (_metric(m, *WAITING) or 0) == 0:
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(1.0)

    def stop_requested(self) -> bool:
        return bool(self.a.stop_file) and Path(self.a.stop_file).exists()

    def group(self, c: Cell, rep: int) -> dict:
        prompts = [self.prompt(c, rep, s) for s in range(c.streams)]
        bodies = [self.body(c, rep, t, salt) for t, salt in prompts]
        results = [Result(s, hashlib.sha256(t.encode()).hexdigest()) for s, (t, _) in enumerate(prompts)]
        idle = self.wait_idle()
        if idle is False:
            raise Stop(f'server not idle within {self.a.idle_wait:.0f} s before {c.id} rep {rep}')
        m0 = self.api.metrics()
        gate = threading.Barrier(c.streams) if c.streams > 1 else None
        threads = [threading.Thread(target=stream_request, args=(self.api, b, gate, r), daemon=True)
                   for b, r in zip(bodies, results)]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(0.5)
            if self.stop_requested():          # e.g. the memory watch fired: cancel the requests in flight
                for r in results:
                    try:
                        if getattr(r, 'resp', None) is not None:
                            r.resp.close()
                    except Exception:  # noqa: BLE001
                        pass
                raise Stop(f'stop file {self.a.stop_file} present during {c.id} rep {rep}; in-flight requests closed')
        time.sleep(self.a.settle)
        m1 = self.api.metrics()
        ok = [r for r in results if r.error is None]
        agg = None
        if len(ok) == len(results) and ok:
            span = max(r.t_last for r in ok) - min(r.t_first for r in ok)          # type: ignore[type-var]
            agg = sum(r.completion_tokens or 0 for r in ok) / span if span > 0 else None
        delta = metric_delta(m0, m1)
        drafts = _metric(m1, *DRAFTS)
        acc_round = None
        foreign = None
        if m0 is not None and m1 is not None:
            d_drafts = (drafts or 0) - (_metric(m0, *DRAFTS) or 0)
            d_acc = (_metric(m1, *ACCEPTED) or 0) - (_metric(m0, *ACCEPTED) or 0)
            acc_round = d_acc / d_drafts if d_drafts > 0 else None
            d_prompt = (_metric(m1, *PROMPT_TOK) or 0) - (_metric(m0, *PROMPT_TOK) or 0)
            d_gen = (_metric(m1, *GEN_TOK) or 0) - (_metric(m0, *GEN_TOK) or 0)
            sent_prompt = sum(r.prompt_tokens or 0 for r in results)
            sent_gen = sum(r.completion_tokens or 0 for r in results)
            if _metric(m1, *PROMPT_TOK) is not None:
                foreign = d_prompt > sent_prompt + 64 or d_gen > sent_gen + 64
        for r in results:
            r.t_first = r.t_last = r.resp = None
        return {'rep': rep, 'idle_before': idle, 'aggregate_tok_s': agg, 'accepted_per_round': acc_round,
                'foreign_traffic': foreign, 'metrics_delta': delta,
                'requests': [{k: v for k, v in asdict(r).items() if k not in ('t_first', 't_last', 'resp')} for r in results]}

    def run(self, cells: list[Cell]) -> tuple[dict, int]:
        started = time.time()
        out: dict = {'schema': SCHEMA, 'tool': {'name': 'tools/bench.py', 'version': VERSION,
                                                'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                     'run': {'label': self.a.label, 'url': self.a.url, 'model': self.model,
                             'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(started)),
                             'profiles': self.a.profile, 'seed': self.a.seed, 'note': self.a.note},
                     'calibration': self.calibrate(), 'cells': [], 'stopped': None}
        rc = 0
        try:
            for c in cells:
                entry = {'cell': asdict(c), 'groups': []}
                out['cells'].append(entry)
                for rep in range(c.reps):
                    if self.stop_requested():
                        raise Stop(f'stop file {self.a.stop_file} present')
                    g = self.group(c, rep)
                    entry['groups'].append(g)
                    if any(r['error'] for r in g['requests']):
                        rc = 1
                    if any(r['cached_tokens'] for r in g['requests']):
                        print(f'  WARNING {c.id} rep {rep}: cached_tokens > 0 (prefix cache was hit; not a cold prompt)',
                              file=sys.stderr)
                    if not self.a.quiet:
                        show(c, g)
                entry['summary'] = summarize_cell(entry)
                self.write(out)
        except Stop as exc:
            out['stopped'] = str(exc)
            rc = 3
            print(f'STOPPED: {exc}', file=sys.stderr)
        except KeyboardInterrupt:
            out['stopped'] = 'interrupted'
            rc = 3
        for e in out['cells']:
            e.setdefault('summary', summarize_cell(e))
        out['run']['ended_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        out['run']['duration_s'] = round(time.time() - started, 1)
        self.write(out)
        return out, rc

    def write(self, out: dict) -> None:
        if self.a.out:
            p = Path(self.a.out)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + '.tmp')
            tmp.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
            tmp.replace(p)


# ---------------------------------------------------------------------------------------------------------------------
# Summaries, tables, compare

def _med(xs: list) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float)) and math.isfinite(x)]
    return statistics.median(xs) if xs else None


def summarize_cell(entry: dict) -> dict:
    reqs = [r for g in entry['groups'] for r in g['requests'] if r['error'] is None]
    clean = [g for g in entry['groups'] if g.get('foreign_traffic') is not True]
    return {
        'n_groups': len(entry['groups']), 'n_requests_ok': len(reqs),
        'n_errors': sum(1 for g in entry['groups'] for r in g['requests'] if r['error']),
        'n_foreign_traffic_groups': sum(1 for g in entry['groups'] if g.get('foreign_traffic') is True),
        'ttft_s': _med([r['ttft_s'] for r in reqs]),
        'prefill_tok_s': _med([r['prefill_tok_s'] for r in reqs]),
        'decode_tok_s': _med([r['decode_tok_s'] for r in reqs]),
        'aggregate_tok_s': _med([g['aggregate_tok_s'] for g in clean]),
        'accepted_per_round': _med([g['accepted_per_round'] for g in clean]),
        'prompt_tokens': _med([r['prompt_tokens'] for r in reqs]),
        'completion_tokens': _med([r['completion_tokens'] for r in reqs]),
        'cached_tokens_max': max((r['cached_tokens'] or 0 for r in reqs), default=None),
    }


def fmt(x: float | None, d: int = 1) -> str:
    return '-' if x is None else f'{x:,.{d}f}'


def show(c: Cell, g: dict) -> None:
    for r in g['requests']:
        if r['error']:
            print(f'  {c.id} rep {g["rep"]} stream {r["stream"]}: ERROR {r["error"]}', flush=True)
    ok = [r for r in g['requests'] if not r['error']]
    if ok:
        print(f'  {c.id:28s} rep {g["rep"]}  prompt {fmt(_med([r["prompt_tokens"] for r in ok]), 0):>8s}  '
              f'ttft {fmt(_med([r["ttft_s"] for r in ok]), 2):>7s}s  decode {fmt(_med([r["decode_tok_s"] for r in ok])):>6s}'
              f'  agg {fmt(g["aggregate_tok_s"]):>6s}  acc/round {fmt(g["accepted_per_round"], 2):>5s}'
              f'{"  FOREIGN TRAFFIC" if g["foreign_traffic"] else ""}', flush=True)


def table(out: dict) -> str:
    rows = ['| cell | n | prompt tok | TTFT s | prefill tok/s | decode tok/s (per stream) | aggregate tok/s | accepted/round |',
            '|-|-|-|-|-|-|-|-|']
    for e in out['cells']:
        s = e.get('summary') or {}
        rows.append(f'| {e["cell"]["id"]} | {s.get("n_requests_ok")} | {fmt(s.get("prompt_tokens"), 0)} | '
                    f'{fmt(s.get("ttft_s"), 2)} | {fmt(s.get("prefill_tok_s"))} | {fmt(s.get("decode_tok_s"))} | '
                    f'{fmt(s.get("aggregate_tok_s"))} | {fmt(s.get("accepted_per_round"), 3)} |')
    return '\n'.join(rows)


METRICS = ('ttft_s', 'prefill_tok_s', 'decode_tok_s', 'aggregate_tok_s', 'accepted_per_round')


def compare(a_path: str, b_path: str) -> int:
    a, b = (json.loads(Path(p).read_text()) for p in (a_path, b_path))
    sa = {e['cell']['id']: e.get('summary') or {} for e in a['cells']}
    sb = {e['cell']['id']: e.get('summary') or {} for e in b['cells']}
    print(f'A = {a["run"].get("label")} ({a["run"].get("started_utc")})   B = {b["run"].get("label")} ({b["run"].get("started_utc")})')
    print('| cell | metric | A | B | B vs A |')
    print('|-|-|-|-|-|')
    for cid in [c for c in sa if c in sb]:
        for m in METRICS:
            x, y = sa[cid].get(m), sb[cid].get(m)
            if x is None and y is None:
                continue
            d = f'{(y - x) / x * 100:+.1f} %' if isinstance(x, (int, float)) and isinstance(y, (int, float)) and x else '-'
            print(f'| {cid} | {m} | {fmt(x, 3 if m == "accepted_per_round" else 2)} | '
                  f'{fmt(y, 3 if m == "accepted_per_round" else 2)} | {d} |')
    only = sorted(set(sa) ^ set(sb))
    if only:
        print(f'\ncells in only one run: {", ".join(only)}')
    return 0


# ---------------------------------------------------------------------------------------------------------------------

def parse_sizes(text: str) -> list[int]:
    out = []
    for x in text.split(','):
        x = x.strip().lower()
        if x:
            out.append(int(x[:-1]) * 1024 if x.endswith('k') else int(x))
    return out


def args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('run', 'plan'):
        p = sub.add_parser(name)
        p.add_argument('--profile', default='all', choices=('mia', 'ours', 'all'))
        p.add_argument('--reps-mia', type=int, default=3, help='repeats per mia decode cell (default 3)')
        p.add_argument('--reps-prefill', type=int, default=2, help='repeats per prefill size (default 2)')
        p.add_argument('--reps-ours', type=int, default=3, help='repeats per ours cell (default 3)')
        p.add_argument('--prefill-sizes', default='4k,8k,16k,32k,64k,128k,256k')
        p.add_argument('--streams', default='1,2,3,4')
        p.add_argument('--only', default='', help='comma-separated cell id prefixes to keep (e.g. ours/32k,mia/prefill)')
        p.add_argument('--seed', type=int, default=1234)
        p.add_argument('--json', action='store_true', help='plan: print the request list as JSON')
        if name == 'run':
            p.add_argument('--url', default=os.environ.get('API_URL', 'http://127.0.0.1:8000'))
            p.add_argument('--model', default=os.environ.get('MODEL'))
            p.add_argument('--out', help='write the JSON here (rewritten after every cell)')
            p.add_argument('--label', default='')
            p.add_argument('--note', default='', help='free text stored in the JSON (clock, commit, ...)')
            p.add_argument('--timeout', type=float, default=1800)
            p.add_argument('--settle', type=float, default=2.0, help='seconds after each group (default 2)')
            p.add_argument('--idle-wait', type=float, default=120, help='seconds to wait for an idle server per group')
            p.add_argument('--no-idle-check', action='store_true')
            p.add_argument('--stop-file', help='stop cleanly after the current group when this file exists')
            p.add_argument('--exact-size', action='store_true', help='trim/extend each long prompt with /tokenize')
            p.add_argument('--no-cache-salt', action='store_true', help='do not send cache_salt (non-vLLM servers)')
            p.add_argument('--no-priority', action='store_true', help='do not send the priority field')
            p.add_argument('--quiet', action='store_true')
    c = sub.add_parser('compare')
    c.add_argument('a')
    c.add_argument('b')
    s = sub.add_parser('table')
    s.add_argument('run_json')
    return ap.parse_args(argv)


def select(a: argparse.Namespace) -> list[Cell]:
    profiles = ['mia', 'ours'] if a.profile == 'all' else [a.profile]
    cells = build_plan(profiles, a.reps_mia, a.reps_prefill, a.reps_ours, parse_sizes(a.prefill_sizes),
                       [int(x) for x in a.streams.split(',') if x.strip()])
    keep = [k.strip() for k in a.only.split(',') if k.strip()]
    return [c for c in cells if not keep or any(c.id.startswith(k) for k in keep)]


def plan(cells: list[Cell], as_json: bool) -> int:
    rows = []
    total = 0.0
    nreq = 0
    for c in cells:
        g = estimate_group_s(c)
        total += g * c.reps
        nreq += c.streams * c.reps
        rows.append({'cell': c.id, 'groups': c.reps, 'streams': c.streams, 'requests': c.streams * c.reps,
                     'prompt_tokens': c.target_tokens or 'short instruction', 'max_tokens': c.max_tokens,
                     'temperature': c.temperature, 'thinking': c.thinking, 'ignore_eos': c.ignore_eos,
                     'priority': c.priority, 'est_s_per_group': round(g, 1), 'est_s': round(g * c.reps, 1)})
    if as_json:
        print(json.dumps({'cells': rows, 'requests': nreq, 'est_minutes': round(total / 60, 1)}, indent=1))
        return 0
    print('| cell | groups x streams | prompt tokens | max out | T | thinking | est s |')
    print('|-|-|-|-|-|-|-|')
    for r in rows:
        print(f'| {r["cell"]} | {r["groups"]} x {r["streams"]} | {r["prompt_tokens"]} | {r["max_tokens"]} | '
              f'{r["temperature"]} | {"on" if r["thinking"] else "off"} | {r["est_s"]} |')
    print(f'\n{len(rows)} cells, {nreq} requests, ESTIMATED {total / 60:.1f} min (rate model in est_ttft / est_decode_rate)')
    return 0


def main(argv: list[str] | None = None) -> int:
    a = args(argv)
    if a.cmd == 'compare':
        return compare(a.a, a.b)
    if a.cmd == 'table':
        print(table(json.loads(Path(a.run_json).read_text())))
        return 0
    cells = select(a)
    if not cells:
        print('no cells selected', file=sys.stderr)
        return 2
    if a.cmd == 'plan':
        return plan(cells, a.json)
    out, rc = Runner(a).run(cells)
    print()
    print(table(out))
    return rc


if __name__ == '__main__':
    sys.exit(main())
