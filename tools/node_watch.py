#!/usr/bin/env python3
"""Read-only node watch for a benchmark window: GPU SM clock, temperature and MemAvailable on each serving node.

Every --interval seconds it runs one read-only query per node (over ssh, or locally with --local) and appends a JSONL
row. When any node's MemAvailable falls below --min-gib it creates --stop-file, which makes tools/bench.py close its
requests in flight and stop (exit 3). It changes nothing on the nodes: the query is nvidia-smi --query-gpu plus
/proc/meminfo. Stop it with Ctrl-C or when --until-file exists. Stdlib only.

    python3 -I tools/node_watch.py --node sparkhead --node sparkworker --out runs/x-nodes.jsonl \\
        --stop-file runs/STOP --until-file runs/DONE"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

QUERY = ('nvidia-smi --query-gpu=clocks.sm,clocks.max.sm,temperature.gpu,power.draw --format=csv,noheader,nounits '
         '2>/dev/null; grep MemAvailable /proc/meminfo')


def parse(text: str) -> dict:
    row: dict = {}
    for line in text.splitlines():
        if line.startswith('MemAvailable:'):
            row['mem_available_gib'] = round(int(line.split()[1]) / 1048576, 3)
        elif ',' in line and 'sm_clock_mhz' not in row:
            parts = [p.strip() for p in line.split(',')]
            keys = ('sm_clock_mhz', 'max_sm_clock_mhz', 'gpu_temp_c', 'power_w')
            for k, v in zip(keys, parts):
                try:
                    row[k] = float(v)
                except ValueError:
                    row[k] = None
    return row


def sample(node: str, local: bool, timeout: float) -> dict:
    cmd = ['bash', '-c', QUERY] if local else ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', node, QUERY]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        return {'error': 'timeout'}
    return parse(out) or {'error': 'no output'}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--node', action='append', default=[], help='ssh alias of a serving node (repeat)')
    ap.add_argument('--local', action='store_true', help='query this machine instead of ssh nodes')
    ap.add_argument('--interval', type=float, default=5.0)
    ap.add_argument('--min-gib', type=float, default=4.5)
    ap.add_argument('--out', required=True)
    ap.add_argument('--stop-file', required=True)
    ap.add_argument('--until-file')
    ap.add_argument('--samples', type=int, default=0, help='stop after this many rounds (0 = until --until-file)')
    a = ap.parse_args(argv)
    nodes = ['local'] if a.local else a.node
    if not nodes:
        ap.error('give --node at least once, or --local')
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open('a') as f:
        while True:
            ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            for node in nodes:
                row = {'ts': ts, 'node': node, **sample(node, a.local, max(4.0, a.interval))}
                f.write(json.dumps(row, sort_keys=True) + '\n')
                f.flush()
                mem = row.get('mem_available_gib')
                if mem is not None and mem < a.min_gib and not Path(a.stop_file).exists():
                    Path(a.stop_file).write_text(f'{ts} {node} MemAvailable {mem} GiB < {a.min_gib}\n')
                    print(f'STOP: {node} MemAvailable {mem} GiB < {a.min_gib} GiB', file=sys.stderr, flush=True)
            n += 1
            if (a.samples and n >= a.samples) or (a.until_file and Path(a.until_file).exists()):
                return 0
            time.sleep(a.interval)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
