#!/usr/bin/env python3
"""PP4-INSTALL (NDM 2026-10-28): put the PP4 layer into a production dsv41.env, by exact anchors.

CPU only. The layer is the same on any production that mounts K1's model_runner.py and one remote_dspark package
(prod/upstream-all a0006fc, or the matter promotion on top of it): the PP4 switches go at the end of OFFLOAD_DSPARK_ENV,
the remote_dspark and model_runner.py mounts take their sources from ~/dsv41-pp4/<id>/, two new verifier mounts follow,
and PROD_PP4=<id> selects the layer. NOUT-TRIM's switch is removed (MANIFEST remove_env). Anything it cannot place
exactly refuses; nothing else in the file changes.

    python3 offload/pp4_prod/compose_env.py apply --base-commit <production commit>   # writes ./dsv41.env
    python3 offload/pp4_prod/compose_env.py check --base-commit <production commit>   # ./dsv41.env == the composition
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MARKER = '# PP4-INSTALL '


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f'PP4 COMPOSE REFUSED: {message}')


def assignment(lines: list[str], name: str) -> int:
    """Index of the ONE active single-line `NAME="..."` assignment; comments and look-alikes never match."""
    hits = [i for i, line in enumerate(lines) if line.startswith(name + '="') and line.rstrip('\n').endswith('"')]
    require(len(hits) == 1, f'{name}: expected exactly one active single-line assignment, found {len(hits)}')
    return hits[0]


def tokens(line: str, name: str) -> list[str]:
    value = line.rstrip('\n')[len(name) + 2:-1]
    require('"' not in value, f'{name}: unexpected quoting')
    return value.split()


def compose(text: str, manifest: dict[str, object], stage_id: str) -> str:
    require(MARKER not in text and 'PROD_PP4=' not in text, 'PP4 layer already present in dsv41.env')
    lines = text.splitlines(keepends=True)
    require(bool(lines) and lines[-1].endswith('\n'), 'dsv41.env must end with a newline')
    switches = manifest['switches']
    remove = manifest['remove_env']
    forbidden = manifest['forbidden_env']
    assert isinstance(switches, dict) and isinstance(remove, list) and isinstance(forbidden, list)
    removed: list[str] = []
    for name in ('OFFLOAD_DOCKER_ENV', 'OFFLOAD_DSPARK_ENV'):
        i = assignment(lines, name)
        kept: list[str] = []
        for token in tokens(lines[i], name):
            key = token.split('=', 1)[0]
            require(key not in switches and key not in forbidden, f'production {name} already sets {key}')
            if key in remove:
                removed.append(token)
            else:
                kept.append(token)
        if name == 'OFFLOAD_DSPARK_ENV':
            require(any(t.startswith('VLLM_DSPARK_REMOTE=') for t in kept), 'production remote DSpark absent')
            kept += [f'{k}={v}' for k, v in switches.items()]
        lines[i] = f'{name}="{" ".join(kept)}"\n'
    i = assignment(lines, 'OFFLOAD_DOCKER_ARGS')
    args = tokens(lines[i], 'OFFLOAD_DOCKER_ARGS')
    require(len(args) % 2 == 0 and all(a == '-v' for a in args[::2]), 'OFFLOAD_DOCKER_ARGS: -v pairs required')
    stage = f'\\$HOME/dsv41-pp4/{stage_id}'
    files = manifest['files']
    assert isinstance(files, list)
    verifier = {str(r['container_path']): f"{stage}/{r['path']}" for r in files if r['kind'] == 'verifier'}
    mount = str(manifest['remote_dspark_mount'])
    runner = next(t for t in verifier if t.endswith('/vllm/v1/worker/gpu/model_runner.py'))
    replace = {mount: f'{stage}/remote_dspark', runner: verifier[runner]}
    seen: set[str] = set()
    out: list[str] = []
    for spec in args[1::2]:
        require(spec.endswith(':ro') and spec.count(':') == 2, f'unexpected mount {spec}')
        source, target, _ = spec.split(':')
        require(target not in verifier or target in replace, f'{target} already mounted by production')
        if target in replace:
            require(target not in seen, f'duplicate mount {target}')
            seen.add(target)
            source = replace[target]
        out.append(f'{source}:{target}:ro')
    require(seen == set(replace), 'production remote_dspark / model_runner.py mounts not found exactly once')
    out += [f'{src}:{target}:ro' for target, src in verifier.items() if target not in replace]
    lines[i] = 'OFFLOAD_DOCKER_ARGS="' + ' '.join(f'-v {m}' for m in out) + '"\n'
    note = (f'# NOUT-TRIM ({" ".join(removed)}) is off while PP4 is on: a fixed window of 5 leaves it nothing to cut, and\n'
            '# PP4\'s remote package carries no trim (gpu_worker.py\'s hand-off is inert without it).\n') if removed else ''
    lines += [MARKER + '(NDM 2026-10-28, documents/plans/2026-10-28_pp4-install.md): sampled K2 drafting, PP4 Round18\n',
              f'# {str(manifest["pp4_commit"])[:7]} (the qualified admission\'s bytes). OFFLOAD_DSPARK_ENV ends with the PP4 '
              'switches (fixed window 5,\n',
              '# adaptive window and confidence depth off, sampled top-32 proposals on). OFFLOAD_DOCKER_ARGS mounts the '
              'composed\n',
              '# 0075 + PP4 remote_dspark package and PP4\'s verifier (model_runner.py, rejection_sampler_utils.py,\n',
              '# dsv41_pp4_round_trace.py) from ~/dsv41-pp4/<PROD_PP4>/ (offload/pp4_prod/stage.sh from start.sh,\n',
              '# verify_running.sh from K1\'s verify.sh); serve.sh fixes SPEC at 5; x86host runs the 50-pp4.conf worker '
              'drop-in.\n',
              note,
              '# Rollback: $C/PP4-INSTALL/ROLLBACK.sh on Controller (the pre-PP4 backup\'s commit, K1 record and strict W8).\n',
              f'PROD_PP4={stage_id}\n']
    return ''.join(lines)


def load() -> tuple[dict[str, object], str]:
    raw = (HERE / 'MANIFEST.json').read_bytes()
    manifest: dict[str, object] = json.loads(raw)
    return manifest, hashlib.sha256(raw).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('apply', 'check', 'print'))
    parser.add_argument('--base-commit', required=True)
    a = parser.parse_args()
    base = subprocess.run(['git', '-C', str(ROOT), 'show', f'{a.base_commit}:dsv41.env'], check=True,
                          stdout=subprocess.PIPE, env={'PATH': '/usr/bin:/bin'}).stdout.decode()
    manifest, stage_id = load()
    text = compose(base, manifest, stage_id)
    if a.action == 'print':
        print(text, end='')
    elif a.action == 'apply':
        (ROOT / 'dsv41.env').write_text(text)
        print(f'dsv41.env = {a.base_commit[:12]} dsv41.env + the PP4 layer {stage_id}')
    else:
        require((ROOT / 'dsv41.env').read_text() == text, f'dsv41.env is not {a.base_commit[:12]} + the PP4 layer {stage_id}')
        print(f'dsv41.env == {a.base_commit[:12]} dsv41.env + the PP4 layer {stage_id}')


if __name__ == '__main__':
    main()
