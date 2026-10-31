"""The PP4 layer itself: pinned bytes, the dsv41.env composition on both possible bases, the x86host texts, the serve.sh
hook and the composition audit's rules. CPU only; reads files of this checkout (no git, no host)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import audit  # noqa: E402
import build  # noqa: E402
import compose_env  # noqa: E402
import worker  # noqa: E402

MANIFEST_BYTES = (HERE.parent / 'MANIFEST.json').read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
STAGE = hashlib.sha256(MANIFEST_BYTES).hexdigest()[:12]
# The production this layer is composed on (offload/pp4_prod/BASE) and its dsv41.env (a copy, checked against git by
# compose_env.py check in the install's static gate); its verify window is UPSTREAM-ALL's K5.
BASE = (HERE.parent / 'BASE').read_text().strip()
BASE_ENV = HERE / 'data' / f'{BASE[:7]}.dsv41.env'
K5 = json.loads((TREE / 'offload/upstream_all/MANIFEST.json').read_text())['serve_argv']['--speculative-config']


def test_overlay_bytes_are_the_manifest_and_the_pins() -> None:
    rows = MANIFEST['files']
    assert len(rows) == 25 and sum(r['kind'] == 'remote' for r in rows) == 22
    for r in rows:
        assert hashlib.sha256((HERE.parent / 'overlay' / r['path']).read_bytes()).hexdigest() == r['sha256']
    remote = {r['path'].removeprefix('remote_dspark/'): r['sha256'] for r in rows if r['kind'] == 'remote'}
    assert remote == build.REMOTE_SHA256
    verifier = {r['container_path'].removeprefix(build.DIST): r['sha256'] for r in rows if r['kind'] == 'verifier'}
    assert verifier == build.VERIFIER_SHA256
    on_disk = {str(p.relative_to(HERE.parent / 'overlay')) for p in (HERE.parent / 'overlay').rglob('*') if p.is_file()}
    assert on_disk == {r['path'] for r in rows}


def test_manifest_declares_the_pp4_switch_set_and_the_reviewed_worker() -> None:
    assert MANIFEST['switches'] == {'VLLM_DSV41_ADAPTIVE_K': '0', 'VLLM_DSPARK_DEPTH_POLICY': 'fixed:5',
                                    'VLLM_DSPARK_DEPTH_FILE': '', 'VLLM_DSPARK_LOOKUP': '',
                                    'VLLM_DSPARK_REMOTE_WANT_MARGIN': '0', 'VLLM_DSPARK_SAMPLED_TOP32': '1'}
    assert json.loads(MANIFEST['spec']) == {'method': 'dspark', 'num_speculative_tokens': 5}
    assert MANIFEST['remove_env'] == ['VLLM_DSPARK_REMOTE_N_OUT']
    assert MANIFEST['pp4_commit'] == worker.PP4_COMMIT == '76e2e21cb519d09e7179246d80a3af9a688a3775'
    assert MANIFEST['worker']['dropin_sha256'] == worker.REVIEWED_DROPIN_SHA256 == worker.sha(worker.render_dropin())


def test_pp4_runner_is_k1_plus_the_reviewed_additions_only() -> None:
    k1 = (TREE / 'offload/kvpack/overlay/vllm/v1/worker/gpu/model_runner.py').read_text()
    pp4 = (HERE.parent / 'overlay/dist/vllm/v1/worker/gpu/model_runner.py').read_text()
    assert hashlib.sha256(k1.encode()).hexdigest() == build.K1_RUNNER_SHA256
    k1_lines, pp4_lines = k1.splitlines(), pp4.splitlines()
    added = [line for line in pp4_lines if line not in k1_lines]
    assert all(line in pp4_lines for line in k1_lines)          # nothing of the K1 runner removed
    assert added[0] == 'from vllm.v1.worker.gpu import dsv41_pp4_round_trace as _pp4_round'
    assert "REMOTE_DRAFT_PROBS_ABI = 'pp3-dyadic24-standard-v1'" in added
    assert sum('@_pp4_round.' in line for line in added) == 2 and len(added) <= 12


def test_compose_on_the_base_is_the_committed_dsv41_env() -> None:
    base = BASE_ENV.read_text()
    assert compose_env.compose(base, MANIFEST, STAGE) == (TREE / 'dsv41.env').read_text()


def test_compose_on_the_nout_production_removes_the_trim_and_nothing_else() -> None:
    base = (HERE / 'data/b90ba5aa-nout.dsv41.env').read_text()
    out = compose_env.compose(base, MANIFEST, STAGE)
    i = out.splitlines().index(next(line for line in out.splitlines() if line.startswith('OFFLOAD_DSPARK_ENV="')))
    tokens = out.splitlines()[i][len('OFFLOAD_DSPARK_ENV="'):-1].split()
    assert not any(t.startswith('VLLM_DSPARK_REMOTE_N_OUT=') for t in tokens)
    assert tokens[-6:] == [f'{k}={v}' for k, v in MANIFEST['switches'].items()]
    assert 'NOUT-TRIM (VLLM_DSPARK_REMOTE_N_OUT=window) is off while PP4 is on' in out
    assert f'PROD_PP4={STAGE}' in out
    # every other line of the NOUT production stays
    kept = [line for line in base.splitlines() if not line.startswith(('OFFLOAD_DSPARK_ENV=', 'OFFLOAD_DOCKER_ARGS='))]
    assert all(line in out.splitlines() for line in kept)


@pytest.mark.parametrize('mutation', ['already', 'two-dspark', 'no-runner-mount', 'utils-mounted', 'sets-switch'])
def test_compose_refuses_what_it_cannot_place_exactly(mutation: str) -> None:
    base = BASE_ENV.read_text()
    dist = '/usr/local/lib/python3.12/dist-packages/'
    bad = {
        'already': base + 'PROD_PP4=abc\n',
        'two-dspark': base + base[base.index('OFFLOAD_DSPARK_ENV="'):].split('\n', 1)[0] + '\n',
        'no-runner-mount': base.replace(f':{dist}vllm/v1/worker/gpu/model_runner.py:ro', f':{dist}vllm/v1/worker/gpu/other.py:ro'),
        'utils-mounted': base.replace('OFFLOAD_DOCKER_ARGS="', f'OFFLOAD_DOCKER_ARGS="-v /x:{dist}vllm/v1/worker/gpu/spec_decode/rejection_sampler_utils.py:ro '),
        'sets-switch': base.replace('VLLM_DSPARK_REMOTE_POLICY=capacity', 'VLLM_DSPARK_REMOTE_POLICY=capacity VLLM_DSPARK_SAMPLED_TOP32=0'),
    }[mutation]
    assert bad != base
    with pytest.raises(SystemExit, match='PP4 COMPOSE REFUSED'):
        compose_env.compose(bad, MANIFEST, STAGE)


def render(tmp: Path, env_text: str) -> dict[str, str]:
    where = tmp / 'r'
    where.mkdir(parents=True)
    (where / 'dsv41.env').write_text(env_text)
    shutil.copy2(TREE / 'serve.sh', where / 'serve.sh')
    return audit.render(where)


def test_serve_hook_fixes_spec_only_with_prod_pp4(tmp_path: Path) -> None:
    pp4 = render(tmp_path / 'a', (TREE / 'dsv41.env').read_text())
    base = render(tmp_path / 'b', BASE_ENV.read_text())
    assert json.loads(pp4['SPEC']) == json.loads(MANIFEST['spec'])
    assert base['SPEC'] == K5
    env = audit.env_of(pp4)
    for key, value in MANIFEST['switches'].items():
        assert env[key] == value                                  # the later -e wins over serve.sh's ADAPTIVE_K=1
    assert pp4['DOCKER_ENV'].split().count('VLLM_DSV41_ADAPTIVE_K=1') == 1


def test_audit_passes_exactly_the_layer_and_flags_anything_else(tmp_path: Path) -> None:
    base = render(tmp_path / 'a', BASE_ENV.read_text())
    head = render(tmp_path / 'b', (TREE / 'dsv41.env').read_text())
    rows, bad = audit.audit(base, head, MANIFEST, STAGE)
    nout = 'VLLM_DSPARK_REMOTE_N_OUT=' in BASE_ENV.read_text()
    assert bad == [] and len(rows) == 12 + nout
    extra = dict(head, DOCKER_ENV=head['DOCKER_ENV'] + ' VLLM_SOMETHING_ELSE=1')
    assert audit.audit(base, extra, MANIFEST, STAGE)[1] == ['env VLLM_SOMETHING_ELSE']
    knob = dict(head, MAX_BATCH='4096')
    assert audit.audit(base, knob, MANIFEST, STAGE)[1] == ['knob MAX_BATCH']
    moved = dict(head, OFFLOAD_DOCKER_ARGS=head['OFFLOAD_DOCKER_ARGS'].replace('$HOME/dsv41-kvpack/559c5867ba42/vllm/models/deepseek_v41/attention.py',
                                                                                '$HOME/elsewhere/attention.py'))
    assert any(b.startswith('mount ') and 'attention.py' in b for b in audit.audit(base, moved, MANIFEST, STAGE)[1])


def test_nout_production_audit_declares_the_removed_trim(tmp_path: Path) -> None:
    nout = (HERE / 'data/b90ba5aa-nout.dsv41.env').read_text()
    base = render(tmp_path / 'a', nout)
    head = render(tmp_path / 'b', compose_env.compose(nout, MANIFEST, STAGE))
    rows, bad = audit.audit(base, head, MANIFEST, STAGE)
    assert bad == []
    assert ('env', 'VLLM_DSPARK_REMOTE_N_OUT', "'window' -> None", 'PP4 removes (NOUT-TRIM off at a fixed window)') in rows


def test_worker_texts_are_the_reviewed_ones() -> None:
    dropin = worker.render_dropin()
    assert worker.sha(dropin) == worker.REVIEWED_DROPIN_SHA256
    assert 'Environment=DSPARK_SAMPLED_TOP32=1' in dropin and dropin.count('ExecStart=') == 2
    assert worker.sha(worker.render_attest()) == '0ccf597151e18f0a1458c096c7242c20706a7558730c25e61b4204f56d26e400'
    stage = worker.render_stage_runtime()
    assert 'if [ -d "$D" ]; then sh "$D/attest.sh"' in stage and 'chmod -R a-w' in stage
    verify = worker.render_verify_process()
    assert worker.sha(dropin) in verify and 'PP4 WORKER SAMPLED pid' in verify


def test_nout_layer_audit_is_exactly_the_stage_move(tmp_path: Path) -> None:
    """L1 (NOUT-TRIM over the 0075 stage): the switch, the stage id, the 16 moved mounts, 7 changed MANIFEST rows."""
    old = json.loads((TREE / 'offload/upstream_all/MANIFEST.json').read_text())
    new = json.loads((HERE / 'data/b90ba5aa-upstream-MANIFEST.json').read_text())
    old_id = hashlib.sha256((TREE / 'offload/upstream_all/MANIFEST.json').read_bytes()).hexdigest()[:12]
    new_id = hashlib.sha256((HERE / 'data/b90ba5aa-upstream-MANIFEST.json').read_bytes()).hexdigest()[:12]
    assert (old_id, new_id) == ('c1e72298e5b1', 'e7e8e3f2dd57')
    base = render(tmp_path / 'a', (HERE / 'data/a0006fc.dsv41.env').read_text())
    head = render(tmp_path / 'b', (HERE / 'data/b90ba5aa-nout.dsv41.env').read_text())
    rows, bad = audit.audit_stage_move(base, head, old, new, old_id, new_id)
    assert bad == []
    assert ('env', 'VLLM_DSPARK_REMOTE_N_OUT', "None -> 'window'", 'upstream-all switch') in rows
    assert sum(r[0] == 'bytes' for r in rows) == 7
    assert any(r[1] == '16 upstream-all mounts' for r in rows)
    # anything else is undeclared: an extra env key, a mount moved elsewhere
    extra = dict(head, DOCKER_ENV=head['DOCKER_ENV'] + ' VLLM_OTHER=1')
    assert audit.audit_stage_move(base, extra, old, new, old_id, new_id)[1] == ['env VLLM_OTHER']
    elsewhere = dict(head, OFFLOAD_DOCKER_ARGS=head['OFFLOAD_DOCKER_ARGS'].replace(f'dsv41-upstream-all/{new_id}/dist/vllm_exl3_moe/smoe.py',
                                                                                    'elsewhere/smoe.py'))
    assert any(b.startswith('mount ') for b in audit.audit_stage_move(base, elsewhere, old, new, old_id, new_id)[1])
