#!/usr/bin/env python3
"""PP4-INSTALL composition audit: the effective serve configuration of the base production and of prod/pp4.

CPU only; reads git objects, never a host. For each commit it sources dsv41.env and serve.sh's variable block (up to the
JIT step, which is never run) in a scratch directory, exactly as offload/upstream_all/audit.py does, and reads back the
container env (serve.sh DOCKER_ENV, then dsv41.env's OFFLOAD_DOCKER_ENV and OFFLOAD_DSPARK_ENV; a later key wins, as
with docker -e), the launch knobs and the bind mounts (target -> source). The matter tier's serve block (when the base
has one) is rendered OFF on both sides, so it cancels. The audit passes only when:
  env delta    == exactly MANIFEST switches (set or changed) and remove_env (removed), nothing else;
  knob delta   == SPEC (to MANIFEST spec) and the PROD_PP4 marker, nothing else;
  mounts delta == exactly the PP4 files: the remote_dspark and model_runner.py sources move to ~/dsv41-pp4/<id>/, and
                  the other verifier files are new mounts from there; every other mount keeps its source.

    python3 offload/pp4_prod/audit.py --base <production commit> [--head HEAD] [--markdown OUT.md]

--layer nout audits the other stacked layer, an UPSTREAM-ALL stage move (L1 = the matter production + NOUT-TRIM): the env
delta must be exactly the switches the head's upstream-all MANIFEST adds or changes, the knob delta exactly
PROD_UPSTREAM_ALL (old stage id -> new), and every changed mount exactly an upstream-all mount moving from the old stage
directory to the new one at the same relative path; the MANIFEST rows whose bytes changed are listed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DIST = '/usr/local/lib/python3.12/dist-packages/'
KNOBS = ('SPEC', 'MAX_BATCH', 'MAX_SEQS', 'MAX_LEN', 'KV_BYTES', 'EXTRA', 'GPU_CLOCK_CAP', 'MODEL_DIR', 'IMAGE',
         'PROD_K1', 'PROD_K1_PROFILE', 'PROD_UPSTREAM_ALL', 'PROD_PP4')
PROBE = r'''
set -euo pipefail
set -a; . ./dsv41.env; set +a
export HEAD=spark WORKER=sparkworker
eval "$(sed -n '/^set -euo pipefail$/,/^JIT=/p' serve.sh | sed '$d')"
python3 - <<'EOF'
import json, os
print(json.dumps({k: os.environ.get(k, "") for k in
    ("DOCKER_ENV", "SPEC", "MAX_BATCH", "MAX_SEQS", "MAX_LEN", "KV_BYTES", "EXTRA", "OFFLOAD_DOCKER_ARGS",
     "GPU_CLOCK_CAP", "MODEL_DIR", "IMAGE", "PROD_K1", "PROD_K1_PROFILE", "PROD_UPSTREAM_ALL", "PROD_PP4")}))
EOF
'''
# serve.sh of the matter promotion sources this file and calls matter_block; rendered OFF (its "not staged" path)
MATTER_STUB = '''matter_block() { MATTER_STATE=OFF MATTER_REASON=audit MATTER_EXTRA= MATTER_DOCKER_ENV= MATTER_DOCKER_ARGS=; }
'''


def git(*args: str) -> bytes:
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, stdout=subprocess.PIPE,
                          env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}).stdout


def render(where: Path) -> dict[str, str]:
    """The effective configuration of the dsv41.env and serve.sh in `where` (matter tier rendered OFF)."""
    stub = where / 'offload/prefixstore/production/matter_serve.sh'
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(MATTER_STUB)
    out = subprocess.run(['bash', '-c', PROBE], cwd=where, check=True, stdout=subprocess.PIPE, text=True,
                         env={'PATH': '/usr/bin:/bin', 'HOME': '/home/x'}).stdout
    value: dict[str, str] = json.loads(out)
    return value


def materialize(commit: str, where: Path) -> dict[str, str]:
    for name in ('dsv41.env', 'serve.sh'):
        (where / name).write_bytes(git('show', f'{commit}:{name}'))
    return render(where)


def env_of(cfg: dict[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for kv in cfg['DOCKER_ENV'].split():
        key, val = kv.split('=', 1)
        env[key] = val
    return env


def mounts_of(cfg: dict[str, str]) -> dict[str, str]:
    args = shlex.split(cfg['OFFLOAD_DOCKER_ARGS'])
    if not all(a == '-v' for a in args[::2]):
        raise SystemExit('OFFLOAD_DOCKER_ARGS must be -v pairs')
    out: dict[str, str] = {}
    for spec in args[1::2]:
        src, dst, mode = spec.rsplit(':', 2)
        if mode != 'ro' or dst in out:
            raise SystemExit(f'unexpected mount {spec}')
        out[dst] = src
    return out


def audit(base: dict[str, str], head: dict[str, str], manifest: dict[str, object], stage_id: str) -> tuple[
        list[tuple[str, str, str, str]], list[str]]:
    switches = manifest['switches']
    remove = manifest['remove_env']
    files = manifest['files']
    assert isinstance(switches, dict) and isinstance(remove, list) and isinstance(files, list)
    rows: list[tuple[str, str, str, str]] = []
    bad: list[str] = []
    eb, eh = env_of(base), env_of(head)
    for key in sorted(set(eb) | set(eh)):
        if eb.get(key) == eh.get(key):
            continue
        if key in switches and eh.get(key) == switches[key]:
            item = 'PP4 switch'
        elif key in remove and key in eb and key not in eh:
            item = 'PP4 removes (NOUT-TRIM off at a fixed window)'
        else:
            item = 'UNDECLARED'
            bad.append(f'env {key}')
        rows.append(('env', key, f'{eb.get(key)!r} -> {eh.get(key)!r}', item))
    for key in switches:
        if eh.get(key) != switches[key]:
            bad.append(f'env {key} is {eh.get(key)!r}, MANIFEST says {switches[key]!r}')
    for key in KNOBS:
        if base[key] == head[key]:
            continue
        if key == 'SPEC' and json.loads(head[key]) == json.loads(str(manifest['spec'])):
            item = 'PP4 fixed verify window 5'
        elif key == 'PROD_PP4' and not base[key] and head[key] == stage_id:
            item = 'PP4 install marker (stage/verify switch)'
        else:
            item = 'UNDECLARED'
            bad.append(f'knob {key}')
        rows.append(('knob', key, f'{base[key]!r} -> {head[key]!r}', item))
    mb, mh = mounts_of(base), mounts_of(head)
    stage = f'$HOME/dsv41-pp4/{stage_id}/'
    declared = {str(r['container_path']): stage + str(r['path']) for r in files if r['kind'] == 'verifier'}
    declared[str(manifest['remote_dspark_mount'])] = stage + 'remote_dspark'
    for dst in sorted(set(mb) | set(mh)):
        if mb.get(dst) == mh.get(dst):
            continue
        if declared.get(dst) == mh.get(dst):
            item = 'PP4 file (source moves to the PP4 stage)' if dst in mb else 'PP4 file (new mount)'
        else:
            item = 'UNDECLARED'
            bad.append(f'mount {dst}')
        rows.append(('mount', dst, f'{mb.get(dst)} -> {mh.get(dst)}', item))
    for dst, src in declared.items():
        if mh.get(dst) != src:
            bad.append(f'PP4 mount {dst} is {mh.get(dst)}, expected {src}')
    return rows, bad


def audit_stage_move(base: dict[str, str], head: dict[str, str], old: dict[str, object], new: dict[str, object],
                     old_id: str, new_id: str) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """L1: an UPSTREAM-ALL stage move (NOUT-TRIM on the matter production)."""
    sw_old, sw_new = old['switches'], new['switches']
    assert isinstance(sw_old, dict) and isinstance(sw_new, dict)
    rows: list[tuple[str, str, str, str]] = []
    bad: list[str] = []
    eb, eh = env_of(base), env_of(head)
    for key in sorted(set(eb) | set(eh)):
        if eb.get(key) == eh.get(key):
            continue
        ok = (key in sw_new and sw_old.get(key) != sw_new[key] and eh.get(key) == sw_new[key]) or \
             (key in sw_old and key not in sw_new and key not in eh)
        rows.append(('env', key, f'{eb.get(key)!r} -> {eh.get(key)!r}', 'upstream-all switch' if ok else 'UNDECLARED'))
        if not ok:
            bad.append(f'env {key}')
    for key in KNOBS:
        if base[key] == head[key]:
            continue
        ok = key == 'PROD_UPSTREAM_ALL' and base[key] == old_id and head[key] == new_id
        rows.append(('knob', key, f'{base[key]!r} -> {head[key]!r}', 'upstream-all stage id' if ok else 'UNDECLARED'))
        if not ok:
            bad.append(f'knob {key}')
    mb, mh = mounts_of(base), mounts_of(head)
    moved = 0
    for dst in sorted(set(mb) | set(mh)):
        if mb.get(dst) == mh.get(dst):
            continue
        src_b, src_h = mb.get(dst, ''), mh.get(dst, '')
        prefix_b, prefix_h = f'$HOME/dsv41-upstream-all/{old_id}/', f'$HOME/dsv41-upstream-all/{new_id}/'
        if src_b.startswith(prefix_b) and src_h == prefix_h + src_b.removeprefix(prefix_b):
            moved += 1
            continue
        rows.append(('mount', dst, f'{src_b or None} -> {src_h or None}', 'UNDECLARED'))
        bad.append(f'mount {dst}')
    rows.append(('mount', f'{moved} upstream-all mounts', f'~/dsv41-upstream-all/{old_id}/ -> ~/dsv41-upstream-all/{new_id}/',
                 'upstream-all stage directory'))
    files_old, files_new = old['files'], new['files']
    assert isinstance(files_old, list) and isinstance(files_new, list)
    before = {str(r['container_path']): str(r['sha256']) for r in files_old}
    after = {str(r['container_path']): str(r['sha256']) for r in files_new}
    for dst in sorted(set(before) | set(after)):
        if before.get(dst) != after.get(dst):
            rows.append(('bytes', dst, f'{(before.get(dst) or "absent")[:8]} -> {(after.get(dst) or "absent")[:8]}',
                         'upstream-all MANIFEST row'))
    return rows, bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', required=True)
    ap.add_argument('--head', default='HEAD')
    ap.add_argument('--markdown', type=Path)
    ap.add_argument('--layer', choices=('pp4', 'nout'), default='pp4')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        base, head = materialize(a.base, Path(t1)), materialize(a.head, Path(t2))
    if a.layer == 'nout':
        upstream = 'offload/upstream_all/MANIFEST.json'
        raw_old, raw_new = git('show', f'{a.base}:{upstream}'), git('show', f'{a.head}:{upstream}')
        stage_id = hashlib.sha256(raw_new).hexdigest()[:12]
        rows, bad = audit_stage_move(base, head, json.loads(raw_old), json.loads(raw_new),
                                     hashlib.sha256(raw_old).hexdigest()[:12], stage_id)
    else:
        raw = git('show', f'{a.head}:offload/pp4_prod/MANIFEST.json')
        manifest: dict[str, object] = json.loads(raw)
        stage_id = hashlib.sha256(raw).hexdigest()[:12]
        rows, bad = audit(base, head, manifest, stage_id)
    eb, eh, mb, mh = env_of(base), env_of(head), mounts_of(base), mounts_of(head)
    lines = [f'# {a.layer.upper()} composition audit: {a.base[:12]} -> {a.head}', '',
             f'Rendered from git objects by offload/pp4_prod/audit.py --layer {a.layer} (stage {stage_id}). {len(rows)} differences; '
             f'{len(bad)} undeclared.', '', '| Kind | Key / target | Change | Item |', '|-|-|-|-|']
    for kind, key, change, item in rows:
        short = change.replace('\\$HOME', '~').replace(DIST, 'P/').replace('$HOME', '~')
        lines.append(f"| {kind} | `{key.replace(DIST, 'P/')}` | {short} | {item} |")
    lines += ['', f'Unchanged production mounts: {sum(1 for d in mb if mb.get(d) == mh.get(d))} of {len(mb)}; '
              f'env keys unchanged: {sum(1 for k in eb if eb.get(k) == eh.get(k))} of {len(eb)}; '
              f'head mounts {len(mh)}, env keys {len(eh)}.',
              '', 'RESULT: ' + (('PASS (env delta = the PP4 switches, mounts delta = the PP4 files)' if a.layer == 'pp4' else
                                 'PASS (env delta = the upstream-all switches, mounts delta = the stage move)') if not bad
                                else 'FAIL: ' + '; '.join(bad))]
    text = '\n'.join(lines) + '\n'
    if a.markdown:
        a.markdown.write_text(text)
    print(text)
    if bad:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
