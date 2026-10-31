"""CPU smoke test for tools/sparkbench.py against tools/fake_server.py (stdlib unittest; 127.0.0.1 only).

    python3 -I -m unittest discover -s tools/tests -v"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_bench import TOOLS, Fake


class SparkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = Fake(self.tmp)

    def tearDown(self) -> None:
        self.fake.close()

    def test_small_pass_writes_every_section(self) -> None:
        out = self.tmp / 'pass.json'
        r = subprocess.run([sys.executable, '-I', str(TOOLS / 'sparkbench.py'), '--url', self.fake.url,
                            '--out', str(out), '--reps', '1', '--conc', '1,2', '--max-tokens', '40',
                            '--suites', 'prose-t0,code-t0,structured-t0,prefill', '--prefill', '4096',
                            '--deep', '4096:1', '--interference', '1'],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(out.read_text())
        self.assertEqual(len(d['decode']), 6)
        for w in d['decode']:
            self.assertEqual(w['errors'], [])
            self.assertEqual(w['streamsOk'], w['concurrency'])
        self.assertEqual([p['target'] for p in d['prefill']], [4096])
        self.assertEqual(len(d['deepDecode']), 1)
        self.assertEqual(len(d['interference']['runs']), 1)
        self.assertIn('ended', d)
        bodies = self.fake.bodies()
        self.assertTrue(bodies)
        for b in bodies:
            self.assertIsNone(b['kv_transfer_params'], 'the benchmark must never tag a request for the matter tier')
            self.assertNotIn('kv_transfer_params', b['keys'])


if __name__ == '__main__':
    unittest.main()
