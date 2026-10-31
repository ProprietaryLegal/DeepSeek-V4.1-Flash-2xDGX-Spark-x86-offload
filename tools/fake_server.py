#!/usr/bin/env python3
"""A fake OpenAI-compatible server for dry runs of tools/bench.py (no GPU, no model, stdlib only).

It serves /v1/models, /tokenize, /metrics (vLLM counter names) and streaming /v1/chat/completions with a usage chunk.
Prompt tokens are counted as ceil(characters / 3.6). Prefill takes prompt_tokens / --prefill-tps seconds, then tokens
are streamed at --decode-tps per request (max_tokens with ignore_eos, otherwise at most --natural-stop tokens).
Every request body is appended to --log (JSONL, with the prompt replaced by its length and sha256), so a dry run can
check what the benchmark would send: no kv_transfer_params, a fresh cache_salt per request, the sampling fields.

    python3 -I tools/fake_server.py --port 18765 --log /tmp/fake.jsonl &
    python3 -I tools/bench.py run --url http://127.0.0.1:18765 --settle 0 --out /tmp/dry.json"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = 'fake-model'


class State:
    def __init__(self, a: argparse.Namespace) -> None:
        self.a = a
        self.lock = threading.Lock()
        self.running = 0
        self.c = {'prompt_tokens': 0.0, 'generation_tokens': 0.0, 'spec_decode_num_drafts': 0.0,
                  'spec_decode_num_draft_tokens': 0.0, 'spec_decode_num_accepted_tokens': 0.0,
                  'request_success': 0.0}
        self.salts: set[str] = set()

    def log(self, rec: dict) -> None:
        if self.a.log:
            with self.lock, open(self.a.log, 'a') as f:
                f.write(json.dumps(rec, sort_keys=True) + '\n')


def ntok(text: str) -> int:
    return math.ceil(len(text) / 3.6)


def make_handler(st: State):
    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args) -> None:  # quiet
            pass

        def _json(self, code: int, obj) -> None:
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self) -> None:
            if self.path == '/v1/models':
                return self._json(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model'}]})
            if self.path == '/metrics':
                with st.lock:
                    lines = [f'vllm:num_requests_running{{model_name="{MODEL}"}} {st.running}',
                             f'vllm:num_requests_waiting{{model_name="{MODEL}"}} {st.a.waiting}']
                    lines += [f'vllm:{k}_total{{model_name="{MODEL}"}} {v}' for k, v in st.c.items()]
                b = ('\n'.join(lines) + '\n').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            self._json(404, {'error': 'not found'})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            if self.path == '/tokenize':
                text = ''.join(m.get('content', '') for m in body.get('messages', [])) if 'messages' in body \
                    else body.get('prompt', '')
                return self._json(200, {'count': ntok(text) + 8, 'max_model_len': 327680})
            if self.path != '/v1/chat/completions':
                return self._json(404, {'error': 'not found'})
            text = ''.join(m.get('content', '') for m in body['messages'])
            salt = body.get('cache_salt')
            with st.lock:
                reused = salt is not None and salt in st.salts
                if salt is not None:
                    st.salts.add(salt)
            st.log({'t': time.time(), 'keys': sorted(body), 'prompt_chars': len(text),
                    'prompt_sha256': hashlib.sha256(text.encode()).hexdigest(), 'cache_salt': salt,
                    'salt_reused': reused, **{k: body.get(k) for k in ('max_tokens', 'temperature', 'top_p', 'seed',
                                                                        'ignore_eos', 'priority', 'chat_template_kwargs',
                                                                        'stream_options', 'kv_transfer_params')}})
            pt = ntok(text) + 8
            if pt > st.a.max_len:
                return self._json(400, {'error': f'prompt {pt} > max_model_len {st.a.max_len}'})
            n = int(body.get('max_tokens') or 16)
            if not body.get('ignore_eos'):
                n = min(n, st.a.natural_stop)
            with st.lock:
                st.running += 1
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                time.sleep(pt / st.a.prefill_tps)
                think = bool((body.get('chat_template_kwargs') or {}).get('thinking'))
                for i in range(n):
                    field = 'reasoning_content' if think and i < n // 2 else 'content'
                    ev = {'choices': [{'index': 0, 'delta': {field: f' w{i}'}, 'finish_reason': None}]}
                    self.wfile.write(f'data: {json.dumps(ev)}\n\n'.encode())
                    self.wfile.flush()
                    time.sleep(1.0 / st.a.decode_tps)
                fin = {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'length' if n == body.get('max_tokens') else 'stop'}]}
                usage = {'choices': [], 'usage': {'prompt_tokens': pt, 'completion_tokens': n, 'total_tokens': pt + n,
                                                  'prompt_tokens_details': {'cached_tokens': 0}}}
                for ev in (fin, usage):
                    self.wfile.write(f'data: {json.dumps(ev)}\n\n'.encode())
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
                rounds = max(1, n // 2)
                with st.lock:
                    st.c['prompt_tokens'] += pt
                    st.c['generation_tokens'] += n
                    st.c['spec_decode_num_drafts'] += rounds
                    st.c['spec_decode_num_draft_tokens'] += rounds * 5
                    st.c['spec_decode_num_accepted_tokens'] += n - rounds
                    st.c['request_success'] += 1
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with st.lock:
                    st.running -= 1
            self.close_connection = True

    return H


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=18765)
    ap.add_argument('--log')
    ap.add_argument('--prefill-tps', type=float, default=2_000_000)
    ap.add_argument('--decode-tps', type=float, default=4000)
    ap.add_argument('--natural-stop', type=int, default=400, help='tokens before a natural stop without ignore_eos')
    ap.add_argument('--max-len', type=int, default=327680)
    ap.add_argument('--waiting', type=int, default=0, help='report this many waiting requests (tests the idle check)')
    a = ap.parse_args()
    if a.port == 8000:
        raise SystemExit('refusing port 8000 (the production API port)')
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(State(a)))
    srv.daemon_threads = True
    print(f'fake server on http://{a.host}:{a.port}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
