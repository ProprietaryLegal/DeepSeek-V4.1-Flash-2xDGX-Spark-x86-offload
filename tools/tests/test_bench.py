"""CPU tests for tools/bench.py against tools/fake_server.py (stdlib unittest; no GPU, no network beyond 127.0.0.1).

    python3 -I -m unittest discover -s tools/tests -v"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import bench  # noqa: E402
import fake_server  # noqa: E402
import node_watch  # noqa: E402


class Fake:
    def __init__(self, tmp: Path, **kw) -> None:
        opts = dict(log=str(tmp / 'fake.jsonl'), prefill_tps=5_000_000, decode_tps=20000, natural_stop=50,
                    max_len=327680, waiting=0)
        opts.update(kw)
        self.state = fake_server.State(argparse.Namespace(**opts))
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), fake_server.make_handler(self.state))
        self.srv.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.srv.server_address[1]}'
        self.log = Path(opts['log'])
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def bodies(self) -> list[dict]:
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def run(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return bench.main(argv)


class BenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = Fake(self.tmp)

    def tearDown(self) -> None:
        self.fake.close()

    def args(self, *extra: str) -> list[str]:
        return ['run', '--url', self.fake.url, '--settle', '0', '--idle-wait', '2', '--quiet',
                '--out', str(self.tmp / 'run.json'), *extra]

    def test_plan_lists_both_profiles(self) -> None:
        cells = bench.select(bench.args(['plan', '--profile', 'all']))
        ids = [c.id for c in cells]
        self.assertIn('mia/decode/prose/t0/s4', ids)
        self.assertIn('mia/decode/code/t0/s1', ids)
        self.assertIn('mia/decode/prose/t07-think/s1', ids)
        self.assertIn('mia/prefill/256k', ids)
        self.assertEqual([i for i in ids if i.startswith('ours/')],
                         ['ours/short-b1', 'ours/32k-b1', 'ours/32k-b3', 'ours/32k-b4', 'ours/150k-b1'])
        self.assertEqual(run(['plan', '--profile', 'all', '--json']), 0)

    def test_request_fields_match_each_profile(self) -> None:
        rc = run(self.args('--only', 'ours/short-b1,mia/decode/prose/t0/s2,mia/prefill/4k', '--reps-mia', '1',
                           '--reps-ours', '2', '--reps-prefill', '1'))
        self.assertEqual(rc, 0)
        rows = self.fake.bodies()
        self.assertEqual(len(rows), 2 + 2 + 1)
        for r in rows:
            self.assertIsNone(r['kv_transfer_params'], 'the benchmark must never tag a request for the matter tier')
            self.assertFalse(r['salt_reused'])
            self.assertEqual(r['stream_options'], {'include_usage': True})
        self.assertEqual(len({r['cache_salt'] for r in rows}), len(rows))
        self.assertEqual(len({r['prompt_sha256'] for r in rows}), len(rows))
        ours = [r for r in rows if r['priority'] == 10]
        self.assertEqual(len(ours), 2)
        for r in ours:
            self.assertEqual((r['temperature'], r['ignore_eos'], r['max_tokens']), (1.0, True, 512))
            self.assertEqual(r['chat_template_kwargs']['thinking'], True)
            self.assertEqual(r['chat_template_kwargs']['reasoning_effort'], 'high')
        self.assertEqual(sorted(r['seed'] for r in ours), [42, 43])
        mia = [r for r in rows if r['priority'] is None]
        for r in mia:
            self.assertEqual(r['temperature'], 0.0)
            self.assertIsNone(r['ignore_eos'])
            self.assertFalse(r['chat_template_kwargs']['thinking'])
        out = json.loads((self.tmp / 'run.json').read_text())
        self.assertEqual(out['schema'], bench.SCHEMA)
        cells = {e['cell']['id']: e for e in out['cells']}
        s = cells['ours/short-b1']['summary']
        self.assertEqual(s['n_requests_ok'], 2)
        self.assertEqual(s['completion_tokens'], 512)
        self.assertGreater(s['decode_tok_s'], 0)
        self.assertAlmostEqual(s['accepted_per_round'], 1.0, places=6)
        self.assertEqual(cells['mia/decode/prose/t0/s2']['summary']['completion_tokens'], 50)
        self.assertIsNotNone(cells['mia/decode/prose/t0/s2']['summary']['aggregate_tok_s'])
        self.assertEqual(cells['mia/prefill/4k']['summary']['completion_tokens'], 1)
        self.assertFalse(any(g['foreign_traffic'] for e in out['cells'] for g in e['groups']))
        text = (self.tmp / 'run.json').read_text()
        self.assertNotIn(' w1', text, 'generated text must not be stored')

    def test_long_prompt_size_is_close_to_target(self) -> None:
        rc = run(self.args('--only', 'ours/32k-b1', '--reps-ours', '1', '--exact-size'))
        self.assertEqual(rc, 0)
        out = json.loads((self.tmp / 'run.json').read_text())
        pt = out['cells'][0]['summary']['prompt_tokens']
        self.assertLess(abs(pt - 32000), 64)

    def test_busy_server_stops_with_rc3_and_sends_nothing(self) -> None:
        self.fake.close()
        self.fake = Fake(self.tmp, waiting=1)
        rc = run(self.args('--only', 'ours/short-b1', '--reps-ours', '1'))
        self.assertEqual(rc, 3)
        self.assertEqual(self.fake.bodies(), [])
        self.assertIn('not idle', json.loads((self.tmp / 'run.json').read_text())['stopped'])

    def test_stop_file_cancels_in_flight(self) -> None:
        self.fake.close()
        self.fake = Fake(self.tmp, decode_tps=50)
        stop = self.tmp / 'STOP'
        threading.Timer(1.0, stop.write_text, args=('x',)).start()
        rc = run(self.args('--only', 'ours/short-b1', '--reps-ours', '1', '--stop-file', str(stop)))
        self.assertEqual(rc, 3)
        self.assertIn('in-flight', json.loads((self.tmp / 'run.json').read_text())['stopped'])

    def test_compare(self) -> None:
        a = self.tmp / 'a.json'
        b = self.tmp / 'b.json'
        self.assertEqual(run(self.args('--only', 'ours/short-b1', '--reps-ours', '1', '--label', 'a') + ['--out', str(a)]), 0)
        self.assertEqual(run(self.args('--only', 'ours/short-b1', '--reps-ours', '1', '--label', 'b') + ['--out', str(b)]), 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(bench.main(['compare', str(a), str(b)]), 0)
        self.assertIn('| ours/short-b1 | decode_tok_s |', buf.getvalue())


class SynthTests(unittest.TestCase):
    def test_deterministic_and_varied(self) -> None:
        a = bench.Synth(7).text(20000)
        self.assertEqual(a, bench.Synth(7).text(20000))
        self.assertNotEqual(a, bench.Synth(8).text(20000))
        sentences = [s for s in a.replace('\n', ' ').split('. ') if s]
        self.assertGreater(len(set(sentences)) / len(sentences), 0.98)

    def test_rate_model_is_positive(self) -> None:
        for c in bench.build_plan(['mia', 'ours'], 1, 1, 1, [4096, 262144], [1, 4]):
            self.assertGreater(bench.estimate_group_s(c), 0)


class NodeWatchTests(unittest.TestCase):
    def test_parse(self) -> None:
        row = node_watch.parse('2281, 3003, 61, 48.20\nMemAvailable:    6291456 kB\n')
        self.assertEqual(row['sm_clock_mhz'], 2281.0)
        self.assertEqual(row['mem_available_gib'], 6.0)

    def test_parse_without_gpu(self) -> None:
        self.assertEqual(node_watch.parse('MemAvailable: 1048576 kB'), {'mem_available_gib': 1.0})


if __name__ == '__main__':
    unittest.main()
