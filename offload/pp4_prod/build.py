#!/usr/bin/env python3
"""PP4-INSTALL (NDM 2026-10-28): compose the PP4 sampled-drafting overlay into ONE content-addressed tree.

CPU only. Reads git objects of pinned commits (never a working tree, never GIT_DIR & co.) and writes `overlay/` +
`MANIFEST.json` beside this file:

    python3 offload/pp4_prod/build.py write    # (re)generate overlay/ and MANIFEST.json
    python3 offload/pp4_prod/build.py check    # overlay/ and MANIFEST.json equal a fresh build

overlay/remote_dspark/  per file, a three-way merge (`git merge-file`): ours = the 0075 package production a0006fc mounts
                        (UPSTREAM-ALL stage c1e72298e5b1), theirs = PP4 Round18's package, base = 596ba1c's package (where
                        both started). Any conflict refuses. NOUT-TRIM's package (it rides the matter promotion) is NOT
                        merged on purpose: PP4 verifies a fixed window of 5, where the trim has nothing to cut, and the
                        qualified PP4 code carries no trim; MANIFEST `remove_env` drops its switch while PP4 is on.
overlay/dist/...        PP4 Round18's ordinary verifier (offload/launch/windows/pp4_prepare.py at the PP4 commit, over the
                        image snapshot and the K1 runner), refused unless equal to the qualified admission's verifier_sha256.
The stage id is MANIFEST.json's sha256[:12] (dsv41.env PROD_PP4); stage.sh copies overlay/ to ~/dsv41-pp4/<id>/.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import worker  # noqa: E402  (sibling module; this directory is not a package)

DIST = '/usr/local/lib/python3.12/dist-packages/'
REMOTE = 'vllm/v1/worker/gpu/spec_decode/remote_dspark'
RUNNER = 'vllm/v1/worker/gpu/model_runner.py'
UTILS = 'vllm/v1/worker/gpu/spec_decode/rejection_sampler_utils.py'
TRACE = 'vllm/v1/worker/gpu/dsv41_pp4_round_trace.py'

PP4 = worker.PP4_COMMIT                               # PP4 Round18 (R-PP4), the admitted commit
BASE = '596ba1cf4e3b11be29b41a57e7f69a5d8efa4799'     # production before UPSTREAM-ALL: where both packages started
PROD = 'a0006fc5ebbcbbce4e69f61154731a83f0c4ed9d'     # prod/upstream-all: its stage carries the 0075 package
BASE_PACKAGE = PP4_PACKAGE = 'offload/dspark/spark/remote_dspark'
PROD_PACKAGE = 'offload/upstream_all/overlay/remote_dspark'
SRC_IMAGE = Path('/opt/dsv41/data/src-image')   # read-only snapshot of the image's python sources (PP3/PP4 prep)
ADMISSION = 'PP4-76e2e21c-admission-W-20261028T034416Z/admission-receipt.json'
ADMISSION_SHA256 = 'e90829d04dfc3f1e575e5953d90efe0267c03458782a91c0e04c830e082d8b14'
K1_RUNNER_SHA256 = '682eb895b8fb3d68b9580954b6cda255a49f882bddb4b06342d7d96258eb6e62'
# Ordinary (measurement) verifier = the qualified admission seed's verifier_sha256 (the admission variant is never used).
VERIFIER_SHA256 = {RUNNER: 'e0a11b89a99db93e34f586c03162bb9a4fb3325b6572e88b76f7b14f1a837a97',
                   UTILS: '1468ec723b116013912911625c6d489acc69aedc7a0dffc540d9dd42605c58de',
                   TRACE: '5b9165adfa6a065497aa3d1fe78f468484d25ecab22230dd6aaa09cf3a44a4d3'}
SPEC = '{"method":"dspark","num_speculative_tokens":5}'
# PP4-sampled.env / pp4_window.COMMON_ENV minus the experiment-only round directory; identities stay production's.
SWITCHES = {'VLLM_DSV41_ADAPTIVE_K': '0', 'VLLM_DSPARK_DEPTH_POLICY': 'fixed:5', 'VLLM_DSPARK_DEPTH_FILE': '',
            'VLLM_DSPARK_LOOKUP': '', 'VLLM_DSPARK_REMOTE_WANT_MARGIN': '0', 'VLLM_DSPARK_SAMPLED_TOP32': '1'}
REMOVE_ENV = ('VLLM_DSPARK_REMOTE_N_OUT',)
FORBIDDEN_ENV = ('VLLM_PP4_ROUND_DIR', 'VLLM_PP4_ADMISSION_RUN')
# The composed package, pinned (merge: how the file came out of the three-way merge).
REMOTE_SHA256 = {
    '__init__.py': '9467a2214fb05bc8a10a63d4dc2faa8c646af949d730c9e3613978a66c2b09cc',  # equal
    'breaker.py': '78bcc9c0504bc9c6dba3f48925408c48749a9ee88dba3498ac42d67e711e3887',  # equal
    'client.py': 'c1d2481a6bd07b81f178df4458194c835531b8a5de67fe3ebd7ee7370ba7ca94',  # theirs
    'config.py': '4052810b45333f4c0df6b7cd62c03c278e4984503b04417df2b7fc9b327c100a',  # theirs
    'fused_gather.py': '6c42c28e5d6f1918081d939c1b31d6895af54ca5328ea346903a3f0ad3a98c6f',  # equal
    'gather.py': '1e2dae2cff52617685faa74f7c899654253f2011ba995ec7b8304817672fe543',  # merged
    'hostflag.py': '7e1ce6e645c1c25c8f33e305ca35a05379a8c6a85920c1e3f75462a9fa76b130',  # equal
    'mock_worker.py': '09dabb928d5f6c659553a1beac0259ab6590958683bb1800c37ac016af0013db',  # equal
    'o1_adapter.py': 'ee0c171c2aadfd0cbc80d5cf036087b6a94fabbbe0e441e60c68b8c690943e38',  # equal
    'probability_buffers.py': 'c4a47070ef048f7f949daa7606bbfc2027bcda16b89ab36d375869decbcd4dbb',  # theirs
    'proxy_proc.py': 'd872f79b89630e8695c5074f8da744fab71202308b162ce477bcb4d4a74fc9ca',  # theirs
    'round.py': '3ce8d56eac1a907a6e911f499da1ab710d3d300b4b26adf179701438700f4921',  # merged
    'roundcore.py': '25366c0584e51af3056e7a6796487ba4b75f56a37aac1e42a889b29c82601bc1',  # merged
    'sampled_wire.py': '9fabaae101946c7addfe7f3c41f4c5e618d21d2a8b4488dff4a371947bc4558a',  # theirs
    'shmregion.py': '496bc6abb62c434488b5e29f9f3d7fbb57b1e5bc86eb4a4d7a52c523d1119209',  # theirs
    'speculator.py': '7ea06525dfc578e02ed6f8830ef341447c7515462ae27e2cd0f34d75c4a7d7c0',  # merged
    'state.py': '647b887e432911f81aee8adf153d9240e58dffc5140cbdbda17de288d3fb6d62',  # equal
    'stats.py': '9a58853a6254614918d0d2b2756cbca7e3d41ecae7c7b37c7d85a96959e20e61',  # equal
    'streamsync.py': '4d26e408f562659ed143405ef6e8977fcbda6735e192c941fa023db3cdc46cab',  # equal
    'suffix_provenance.py': 'f45966212bdb01ad71b219a8a97082c58b3074af9c1edbb9679c070d791c2c22',  # equal
    'transport.py': '4b59d0764cb364103a2e3cb3ddf2b04108891a092a0269edd1d3e24be5e4977b',  # equal
    'wire.py': 'ad10643b3e2f901e1250620643fc1d8315fa52e1e9f6cc6e106fb2601c37098b',  # theirs
}


def git(*args: str) -> bytes:
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, stdout=subprocess.PIPE,
                          env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}).stdout


def blob(commit: str, path: str) -> bytes | None:
    listed = git('ls-tree', '--name-only', commit, path).decode().splitlines()
    return git('show', f'{commit}:{path}') if listed == [path] else None


def package(commit: str, path: str) -> dict[str, bytes]:
    """The *.py files of a remote_dspark package (stage_overlay.sh's selection), by name."""
    names = [n for n in git('ls-tree', '--name-only', f'{commit}:{path}').decode().splitlines() if n.endswith('.py')]
    return {name: git('show', f'{commit}:{path}/{name}') for name in names}


def merge3(ours: bytes | None, base: bytes | None, theirs: bytes | None, name: str) -> tuple[bytes, str]:
    if ours == theirs and ours is not None:
        return ours, 'equal'
    if theirs == base and ours is not None:
        return ours, 'ours'
    if ours == base and theirs is not None:
        return theirs, 'theirs'
    with tempfile.TemporaryDirectory() as t:
        files = []
        for label, data in (('ours', ours), ('base', base), ('theirs', theirs)):
            p = Path(t) / label
            p.write_bytes(data or b'')
            files.append(str(p))
        r = subprocess.run(['git', 'merge-file', '-p', '-L', 'production-0075', '-L', 'base-596ba1c', '-L', 'pp4',
                            *files], stdout=subprocess.PIPE, env={'PATH': '/usr/bin:/bin'})
    if r.returncode != 0:
        raise SystemExit(f'{name}: three-way merge has {r.returncode} conflict(s); refusing')
    return r.stdout, 'merged'


def remote_files() -> dict[str, tuple[bytes, str]]:
    ours, base, theirs = package(PROD, PROD_PACKAGE), package(BASE, BASE_PACKAGE), package(PP4, PP4_PACKAGE)
    if set(ours) - set(theirs):
        raise SystemExit(f'production package files absent from PP4: {sorted(set(ours) - set(theirs))}')
    return {name: merge3(ours.get(name), base.get(name), theirs[name], name) for name in sorted(theirs)}


def verifier_files() -> dict[str, bytes]:
    """PP4's ordinary verifier, prepared exactly as the qualified admission did, from the PP4 commit's own code."""
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / 'src'
        src.mkdir()
        archive = git('archive', PP4, 'offload/kvpack', 'offload/dspark/probabilistic/pp3',
                      'offload/dspark/probabilistic/__init__.py', 'offload/launch/windows/pp4_prepare.py',
                      'offload/launch/windows/pp4_round_trace.py')
        subprocess.run(['tar', '-x', '-C', str(src)], input=archive, check=True)
        out = Path(t) / 'out'
        subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); '
                        'from offload.launch.windows import pp4_prepare as p; '
                        'from pathlib import Path; p.prepare(Path(sys.argv[2]), Path(sys.argv[3]))',
                        str(src), str(SRC_IMAGE), str(out)], check=True, stdout=subprocess.DEVNULL)
        files = {name: (out / name).read_bytes() for name in VERIFIER_SHA256}
    for name, data in files.items():
        got = hashlib.sha256(data).hexdigest()
        if got != VERIFIER_SHA256[name]:
            raise SystemExit(f'{name}: prepared {got} != qualified {VERIFIER_SHA256[name]}')
    return files


def build() -> tuple[dict[str, bytes], dict[str, object]]:
    if blob(PP4, 'offload/launch/windows/pp4_prepare.py') is None:
        raise SystemExit('PP4 commit lacks pp4_prepare.py')
    runner_k1 = blob(PP4, f'offload/kvpack/overlay/{RUNNER}')
    if runner_k1 is None or hashlib.sha256(runner_k1).hexdigest() != K1_RUNNER_SHA256:
        raise SystemExit('PP4 commit K1 runner is not production K1 (682eb895)')
    prod_runner = blob(PROD, f'offload/kvpack/overlay/{RUNNER}')
    if prod_runner != runner_k1:
        raise SystemExit('production K1 runner differs from the one PP4 was prepared on')
    tree: dict[str, bytes] = {}
    rows: list[dict[str, str]] = []
    for name, (data, how) in remote_files().items():
        path = f'remote_dspark/{name}'
        tree[path] = data
        rows.append({'kind': 'remote', 'path': path, 'container_path': f'{DIST}{REMOTE}/{name}',
                     'sha256': hashlib.sha256(data).hexdigest(), 'merge': how})
    for name, data in verifier_files().items():
        path = f'dist/{name}'
        tree[path] = data
        rows.append({'kind': 'verifier', 'path': path, 'container_path': f'{DIST}{name}',
                     'sha256': hashlib.sha256(data).hexdigest(),
                     'replaces': 'K1 overlay ' + K1_RUNNER_SHA256[:8] if name == RUNNER else 'image file'
                     if name == UTILS else 'new file'})
    manifest: dict[str, object] = {
        'schema': 'dsv41-pp4-prod-v1',
        'plan': 'documents/plans/2026-10-28_pp4-install.md',
        'pp4_commit': PP4,
        'admission': {'receipt': ADMISSION, 'sha256': ADMISSION_SHA256},
        'remote_sources': {'ours': f'{PROD}:{PROD_PACKAGE}', 'base': f'{BASE}:{BASE_PACKAGE}',
                           'theirs': f'{PP4}:{PP4_PACKAGE}'},
        'remote_dspark_mount': DIST + REMOTE,
        'files': rows,
        'spec': SPEC,
        'switches': SWITCHES,
        'remove_env': list(REMOVE_ENV),
        'forbidden_env': list(FORBIDDEN_ENV),
        'supersedes': {'argv': ['--speculative-config'], 'switches': list(REMOVE_ENV), 'mount': DIST + REMOTE},
        'worker': {'commit': PP4, 'unit': worker.UNIT, 'dropin': worker.DROPIN,
                   'dropin_sha256': worker.sha(worker.render_dropin()),
                   'attest_sha256': worker.sha(worker.render_attest()),
                   'release': worker.RELEASE.replace('%h', '~'), 'runtime': worker.RUNTIME.replace('%h', '~'),
                   'python': worker.PYTHON, 'so_sha256': worker.SO_SHA256, 'tune_sha256': worker.TUNE_SHA256},
    }
    return tree, manifest


def render(manifest: dict[str, object]) -> str:
    return json.dumps(manifest, indent=1, sort_keys=False) + '\n'


def stage_id(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def pinned(tree: dict[str, bytes]) -> None:
    got = {p.removeprefix('remote_dspark/'): hashlib.sha256(d).hexdigest() for p, d in tree.items()
           if p.startswith('remote_dspark/')}
    if REMOTE_SHA256 and got != REMOTE_SHA256:
        bad = sorted(k for k in set(got) | set(REMOTE_SHA256) if got.get(k) != REMOTE_SHA256.get(k))
        raise SystemExit(f'composed remote package differs from the pinned bytes: {bad}')


def main() -> None:
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    if action not in ('write', 'check'):
        raise SystemExit('usage: build.py write|check')
    tree, manifest = build()
    pinned(tree)
    text = render(manifest)
    overlay = HERE / 'overlay'
    if action == 'write':
        if overlay.exists():
            shutil.rmtree(overlay)
        for path, data in tree.items():
            (overlay / path).parent.mkdir(parents=True, exist_ok=True)
            (overlay / path).write_bytes(data)
        (HERE / 'MANIFEST.json').write_text(text)
        print(f'wrote {len(tree)} files; stage id {stage_id(text)}')
        return
    have = {str(p.relative_to(overlay)): p.read_bytes() for p in overlay.rglob('*') if p.is_file()}
    if have != tree:
        bad = sorted(k for k in set(have) | set(tree) if have.get(k) != tree.get(k))
        raise SystemExit(f'overlay/ differs from a fresh build: {bad}')
    if (HERE / 'MANIFEST.json').read_text() != text:
        raise SystemExit('MANIFEST.json differs from a fresh build')
    print(f'overlay/ and MANIFEST.json == a fresh build ({len(tree)} files, stage id {stage_id(text)})')


if __name__ == '__main__':
    main()
