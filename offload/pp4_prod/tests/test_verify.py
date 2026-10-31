"""PP4 shell checks against fake Spark hosts: verify_running.sh (PP4 and UPSTREAM-ALL with PP4's supersedes), stage.sh,
and K1's stage_overlay.sh running check with the declared PP4 runner. CPU only; no socket, no daemon."""
from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import audit  # noqa: E402
import fakehost  # noqa: E402

DIST = '/usr/local/lib/python3.12/dist-packages/'
NODES = ('spark', 'sparkworker')
FAKE_LIB = b'fake top-k library\n'
BASE = (HERE.parent / 'BASE').read_text().strip()
BASE_ENV = HERE / 'data' / f'{BASE[:7]}.dsv41.env'


@pytest.fixture(autouse=True)
def writable_after(tmp_path: Path) -> Iterator[None]:
    """stage.sh leaves staged copies read-only (by design); give them back so the base temp can be removed."""
    yield
    subprocess.run(['chmod', '-R', 'u+w', str(tmp_path)], check=False)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A writable copy of the parts of the checkout the scripts use; the top-k library pin follows the fake bytes."""
    t = tmp_path / 'tree'
    for part in ('offload/pp4_prod', 'offload/upstream_all', 'offload/kvpack', 'offload/promote/k1'):
        shutil.copytree(TREE / part, t / part, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    for name in ('dsv41.env', 'serve.sh'):
        shutil.copy2(TREE / name, t / name)
    m = json.loads((t / 'offload/upstream_all/MANIFEST.json').read_text())
    m['library']['sha256'] = hashlib.sha256(FAKE_LIB).hexdigest()
    (t / 'offload/upstream_all/MANIFEST.json').write_text(json.dumps(m, indent=1) + '\n')
    return t


def source_bytes(tree: Path, source: str) -> dict[str, bytes]:
    """Files a production mount source holds, keyed by path relative to the source (b'' key = the file itself)."""
    for prefix, local in (('$HOME/dsv41-pp4/', 'offload/pp4_prod/overlay'), ('$HOME/dsv41-upstream-all/', 'offload/upstream_all/overlay'),
                          ('$HOME/dsv41-kvpack/', 'offload/kvpack/overlay')):
        if source.startswith(prefix):
            rel = source[len(prefix):].split('/', 1)[1]
            if rel == 'lib/dsv41_topk.so':
                return {'': FAKE_LIB}
            path = tree / local / rel
            if path.is_dir():
                return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*.py')}
            return {'': path.read_bytes()}
    return {'': b'fake production file\n'}


def running(tree: Path, root: Path, env_text: str | None = None, *, mutate: dict[str, bytes | None] | None = None,
            env_extra: list[str] | None = None, spec: str | None = None) -> None:
    """Both fake nodes serve the configuration the given dsv41.env renders (default: the tree's)."""
    where = root / 'render'
    where.mkdir(exist_ok=True)
    (where / 'dsv41.env').write_text(env_text if env_text is not None else (tree / 'dsv41.env').read_text())
    shutil.copy2(tree / 'serve.sh', where / 'serve.sh')
    cfg = audit.render(where)
    files: dict[str, bytes] = {}
    for dst, src in audit.mounts_of(cfg).items():
        for rel, data in source_bytes(tree, src).items():
            files[dst + ('/' + rel if rel else '')] = data
    for path, value in (mutate or {}).items():
        if value is None:
            files.pop(path)
        else:
            files[path] = value
    env = cfg['DOCKER_ENV'].split() + (env_extra or [])
    argv = (f"vllm serve /model --speculative-config '{spec or cfg['SPEC']}' --max-num-batched-tokens {cfg['MAX_BATCH']} "
            '--long-prefill-token-threshold 1024\n')
    # UPSTREAM-ALL item 11 (NOUT-TRIM, when the base carries it) reads its rank-0 decision from the engine log
    logs = ('INFO remote DSpark n_out: next-step window cut on (async scheduling, capacity)\n'
            if 'VLLM_DSPARK_REMOTE_N_OUT=window' in env else '')
    for node in NODES:
        fakehost.container(root, node, files, env, argv, logs)


def sh(tree: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['bash', *args], cwd=tree, env=env, capture_output=True, text=True, timeout=120)


def test_pp4_verify_passes_on_the_composed_production(tree: Path, tmp_path: Path) -> None:
    env = fakehost.install(tmp_path)
    running(tree, tmp_path)
    r = sh(tree, env, 'offload/pp4_prod/verify_running.sh', *NODES)
    assert r.returncode == 0, r.stderr
    assert 'PP4 VERIFIED on spark sparkworker' in r.stdout
    assert r.stdout.count('PP4 25 mounted files == MANIFEST') == 2


@pytest.mark.parametrize('case', ['base-env', 'nout-present', 'extra-remote-file', 'k1-runner', 'k5-spec', 'round-dir'])
def test_pp4_verify_refuses(tree: Path, tmp_path: Path, case: str) -> None:
    env = fakehost.install(tmp_path)
    remote = DIST + 'vllm/v1/worker/gpu/spec_decode/remote_dspark'
    k1_runner = (tree / 'offload/kvpack/overlay/vllm/v1/worker/gpu/model_runner.py').read_bytes()
    kw: dict[str, object] = {
        'base-env': {'env_text': BASE_ENV.read_text()},
        'nout-present': {'env_extra': ['VLLM_DSPARK_REMOTE_N_OUT=window']},
        'extra-remote-file': {'mutate': {remote + '/stray.py': b'x = 1\n'}},
        'k1-runner': {'mutate': {DIST + 'vllm/v1/worker/gpu/model_runner.py': k1_runner}},
        'k5-spec': {'spec': '{"method":"dspark","num_speculative_tokens":5,"num_speculative_tokens_per_batch_size":[[1,4,5]]}'},
        'round-dir': {'env_extra': ['VLLM_PP4_ROUND_DIR=/pp4-round']},
    }[case]  # type: ignore[assignment]
    running(tree, tmp_path, **kw)  # type: ignore[arg-type]
    r = sh(tree, env, 'offload/pp4_prod/verify_running.sh', *NODES)
    assert r.returncode == 1
    assert 'PP4 verification FAILED' in r.stderr


def test_upstream_verify_leaves_superseded_items_to_pp4(tree: Path, tmp_path: Path) -> None:
    env = fakehost.install(tmp_path)
    running(tree, tmp_path)
    stage = hashlib.sha256((tree / 'offload/pp4_prod/MANIFEST.json').read_bytes()).hexdigest()[:12]
    with_pp4 = sh(tree, {**env, 'PROD_PP4': stage}, 'offload/upstream_all/verify_running.sh', *NODES)
    assert with_pp4.returncode == 0, with_pp4.stderr
    assert 'UPSTREAM-ALL VERIFIED on spark sparkworker' in with_pp4.stdout
    assert f'remote_dspark superseded by PP4 {stage}' in with_pp4.stdout
    # the same running containers fail the unmodified checks: PP4 really replaced the 0075 package and the K5 argv
    without = sh(tree, env, 'offload/upstream_all/verify_running.sh', *NODES)
    assert without.returncode == 1
    assert 'running files differ from MANIFEST' in without.stderr and '--speculative-config' in without.stderr
    wrong = sh(tree, {**env, 'PROD_PP4': '000000000000'}, 'offload/upstream_all/verify_running.sh', *NODES)
    assert wrong.returncode == 1 and "is not this checkout's PP4 manifest" in wrong.stderr


def test_upstream_verify_unchanged_on_the_base_production(tree: Path, tmp_path: Path) -> None:
    env = fakehost.install(tmp_path)
    k5 = json.loads((tree / 'offload/upstream_all/MANIFEST.json').read_text())['serve_argv']['--speculative-config']
    running(tree, tmp_path, BASE_ENV.read_text(), spec=k5)
    r = sh(tree, env, 'offload/upstream_all/verify_running.sh', *NODES)
    assert r.returncode == 0, r.stderr
    assert 'superseded' not in r.stdout


def test_stage_copies_verifies_and_never_overwrites(tree: Path, tmp_path: Path) -> None:
    env = fakehost.install(tmp_path)
    stage = hashlib.sha256((tree / 'offload/pp4_prod/MANIFEST.json').read_bytes()).hexdigest()[:12]
    first = sh(tree, {**env, 'PROD_PP4': stage}, 'offload/pp4_prod/stage.sh', *NODES)
    assert first.returncode == 0, first.stderr
    for node in NODES:
        staged = tmp_path / node / 'home/dsv41-pp4' / stage
        assert (staged / 'dist/vllm/v1/worker/gpu/model_runner.py').read_bytes() == \
            (tree / 'offload/pp4_prod/overlay/dist/vllm/v1/worker/gpu/model_runner.py').read_bytes()
        assert len([p for p in staged.rglob('*') if p.is_file()]) == 25
    again = sh(tree, {**env, 'PROD_PP4': stage}, 'offload/pp4_prod/stage.sh', *NODES)
    assert again.returncode == 0 and again.stdout.count('exists (staged before); verifying') == 2
    victim = tmp_path / 'sparkworker/home/dsv41-pp4' / stage / 'remote_dspark/wire.py'
    victim.parent.chmod(0o755)
    victim.chmod(0o644)
    victim.write_text('# changed\n')
    bad = sh(tree, {**env, 'PROD_PP4': stage}, 'offload/pp4_prod/stage.sh', *NODES)
    assert bad.returncode == 1 and 'differs from MANIFEST' in bad.stderr
    wrong = sh(tree, {**env, 'PROD_PP4': '000000000000'}, 'offload/pp4_prod/stage.sh', *NODES)
    assert wrong.returncode == 1 and "but this checkout's manifest is" in wrong.stderr


def test_stage_refuses_an_overlay_file_the_manifest_does_not_name(tree: Path, tmp_path: Path) -> None:
    env = fakehost.install(tmp_path)
    (tree / 'offload/pp4_prod/overlay/remote_dspark/stray.py').write_text('x = 1\n')
    r = sh(tree, env, 'offload/pp4_prod/stage.sh', *NODES)
    assert r.returncode == 1 and 'holds files MANIFEST.json does not name' in r.stderr


def k1_running(tree: Path, root: Path, runner: bytes) -> dict[str, str]:
    """K1's own test hooks: the running container's 13 K1 paths and its switch environment."""
    m = json.loads((tree / 'offload/kvpack/MANIFEST.json').read_text())
    run_root = root / 'k1-running'
    for e in m['files']:
        target = run_root / e['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((tree / 'offload/kvpack/overlay' / e['path']).read_bytes())
    (run_root / 'vllm/v1/worker/gpu/model_runner.py').write_bytes(runner)
    expect = subprocess.run(['bash', '-c', '. offload/promote/k1/constants.sh && echo "$K1_EXPECT"'], cwd=tree,
                            capture_output=True, text=True, check=True).stdout.strip()
    (root / 'k1-env').write_text('\n'.join(expect.split()) + '\n')
    return {'KVPACK_TEST_RUNNING_ROOT': str(run_root), 'KVPACK_TEST_RUNNING_ENV': str(root / 'k1-env'), 'K1_EXPECT': expect}


def test_k1_running_check_accepts_exactly_the_declared_pp4_runner(tree: Path, tmp_path: Path) -> None:
    pp4_runner = (tree / 'offload/pp4_prod/overlay/dist/vllm/v1/worker/gpu/model_runner.py').read_bytes()
    k1 = k1_running(tree, tmp_path, pp4_runner)
    base = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path), **k1}
    declared = hashlib.sha256(pp4_runner).hexdigest()

    def check(extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(['bash', 'offload/kvpack/stage_overlay.sh', 'verify-running', '--expect', k1['K1_EXPECT'], 'local'],
                              cwd=tree, env={**base, **extra}, capture_output=True, text=True, timeout=60)
    ok = check({'KVPACK_PP4_RUNNER_SHA256': declared})
    assert ok.returncode == 0, ok.stderr
    assert f'model_runner.py = the declared PP4 runner {declared[:12]}' in ok.stdout
    assert check({}).returncode == 1                                   # undeclared replacement: refused
    assert check({'KVPACK_PP4_RUNNER_SHA256': '0' * 64}).returncode == 1  # a different declared sha: refused
    assert check({'KVPACK_PP4_RUNNER_SHA256': 'nothex'}).returncode == 1
    # the K1 runner itself still passes without a declaration (production before PP4)
    k1_runner = (tree / 'offload/kvpack/overlay/vllm/v1/worker/gpu/model_runner.py').read_bytes()
    (Path(k1['KVPACK_TEST_RUNNING_ROOT']) / 'vllm/v1/worker/gpu/model_runner.py').write_bytes(k1_runner)
    assert check({}).returncode == 0
