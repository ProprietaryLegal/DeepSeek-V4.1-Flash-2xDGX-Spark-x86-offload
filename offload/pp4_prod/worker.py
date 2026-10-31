#!/usr/bin/env python3
"""PP4-INSTALL (NDM 2026-10-28): the x86host side of PP4 production, as text only.

The TP2 production unit `dsv41-dspark-worker-tp2-prod.service` keeps its own unit file. PP4 adds ONE drop-in
(50-pp4.conf) that runs the qualified sampled K2 worker: release 76e2e21 (prod_tp2.sh stage), the user miniconda
CPython 3.13 with torch 2.12.1+cu130, and an immutable runtime copy (stock + facc exllamav3 extensions, p2p, reviewed tune
cache) whose attestation runs before every start, so interpreter or library drift refuses a start (the Spark then serves
target-only rounds) instead of changing the drafter. The drop-in and attestation texts are PP4-PROMOTE's reviewed
renderings (offload/pp4-promote pp4_promote_switch.py render-dropin / render-attest), byte for byte.

Nothing here touches a host. The install package (`$C/PP4-INSTALL/INSTALL.sh`) pipes these texts over ssh:

    python3 offload/pp4_prod/worker.py dropin           # the drop-in text
    python3 offload/pp4_prod/worker.py attest           # the runtime attestation (attest.sh)
    python3 offload/pp4_prod/worker.py stage-runtime    # bash for `ssh x86host bash -s`: copy + verify the runtime (new dir)
    python3 offload/pp4_prod/worker.py verify-process   # bash for `ssh x86host bash -s`: the running worker is PP4's
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import shlex
import sys

PP4_COMMIT = '76e2e21cb519d09e7179246d80a3af9a688a3775'   # PP4 Round18, the admitted commit (QUALIFIED 2026-10-28)
PP4_ID = PP4_COMMIT[:12]
PYTHON = '/home/operator/miniconda3/bin/python3'
RELEASE = '%h/dsv41-offload/prod/dspark-worker/' + PP4_COMMIT[:7]
RUNTIME = '%h/dsv41-offload/prod/pp4-runtime/' + PP4_ID
RUNTIME_SOURCE = '/opt/dsv41/x86host-data/pp4/source'   # x86host: the reviewed staging (staging-review.json)
UNIT = 'dsv41-dspark-worker-tp2-prod.service'
DROPIN_DIR = '.config/systemd/user/dsv41-dspark-worker-tp2-prod.service.d'
DROPIN = DROPIN_DIR + '/50-pp4.conf'
SO_SHA256 = {'stock/exllamav3_ext.cpython-313-x86_64-linux-gnu.so':
                 '6c77786a3755fa60f9548b86fa0650c4c47100dc3728cda9567658580ccd653e',
             'facc/exllamav3_ext_facc.cpython-313-x86_64-linux-gnu.so':
                 '2582a363ef76b3338b80dfdd4296025fb5c1743c610748bd0e7e5b75d8b0d61e',
             'p2p/08e1903b0a43feff/dspark_p2p.so':
                 '92d1b8c003df23b871b33217931c89e4487e6027fd705d46621ebf838f625cf6'}
TUNE = 'exl3_tune_cache-reviewed.bin'
TUNE_SHA256 = '937e9633334be0a5a7a97557e83f962bfbc33dce84a76b93e331b8017b0d405e'
# PP4-PROMOTE's restore-pp4.sh pins the drop-in it renders; equality proves this copy is the reviewed text.
REVIEWED_DROPIN_SHA256 = 'f9d056561a93e8230dc2455dde5a6153f7f90e0e32aff5ba93a3f840fa066461'


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def render_dropin() -> str:
    """systemd drop-in for the existing TP2 production unit: everything not named stays the unit's own."""
    attest = f'{RUNTIME}/attest.sh'
    locks = '%h/dsv41-offload/locks/gpu-c4e7a371.lock %h/dsv41-offload/locks/gpu-7744b44b.lock'
    return '\n'.join((
        f'# PP4-PROMOTE {PP4_ID}: sampled K2 drafting from qualified bytes (pp4_promote_switch.py render-dropin).',
        '# Rollback: remove exactly this file (hash-checked), daemon-reload, restart through prod_window.sh.',
        '[Service]',
        'Environment=PYTHONDONTWRITEBYTECODE=1',
        f'Environment=PYTHONPATH={RUNTIME}/stock:{RUNTIME}/facc:{RELEASE}/offload/dspark',
        f'Environment=DSPARK_P2P_PREBUILT={RUNTIME}/p2p',
        f'Environment=EXLLAMAV3_TUNE_CACHE={RUNTIME}/{TUNE}',
        'Environment=DSPARK_WORKER_ARM=k2-tp2',
        'Environment=DSPARK_SAMPLED_TOP32=1',
        f'Environment=DSPARK_SOURCE_COMMIT={PP4_COMMIT}',
        f'WorkingDirectory={RELEASE}/offload/dspark',
        f'ExecStartPre=/bin/sh {attest}',
        'ExecStart=',
        f'ExecStart=/bin/sh {RELEASE}/offload/dspark/worker/run/gpu_locked.sh {locks} -- {PYTHON} -u -m worker.server '
        '--tp 2 --root /opt/dsv41/x86host-data/dspark --ofl 10.202.28.1:18620 --max-model-len 1048576 '
        '--status-file %h/dsv41-offload/prod/run/dspark-worker.status.json',
        ''))


def render_attest() -> str:
    """Runtime attestation the unit runs before every start: drift refuses a start rather than changing the drafter."""
    return '\n'.join((
        '#!/bin/sh',
        f'# PP4-PROMOTE {PP4_ID} runtime attestation (pp4_promote_switch.py render-attest).',
        'set -eu',
        'cd "$(dirname "$0")"',
        'sha256sum -c --quiet SHA256SUMS',
        *(f'test "$(sha256sum {name} | cut -d" " -f1)" = {digest}' for name, digest in sorted(SO_SHA256.items())),
        f"{PYTHON} -I -c 'import sys, torch; assert sys.version_info[:2] == (3, 13); "
        "assert torch.__version__ == \"2.12.1+cu130\"; assert torch.version.cuda == \"13.0\"'",
        'echo "PP4 RUNTIME ATTESTED"',
        ''))


def render_stage_runtime() -> str:
    """bash for x86host: copy the reviewed runtime into a NEW immutable directory, verify every digest, attest.

    PP4-PROMOTE's pp4_promote_stage.sh x86host step, unchanged in effect. Refuses when the directory (or its .tmp) exists,
    so a second run never touches a staged runtime; an existing, attested runtime is reported and left alone.
    """
    attest = render_attest().encode()
    lines = ['set -euo pipefail', f'S={RUNTIME_SOURCE}', f'D=$HOME/dsv41-offload/prod/pp4-runtime/{PP4_ID}',
             'if [ -d "$D" ]; then sh "$D/attest.sh" && echo "$(hostname): PP4 runtime already staged" && exit 0; fi',
             'test ! -e "$D.tmp" && mkdir -p "$D.tmp"',
             f'cp -a "$S/runtime/stock" "$S/runtime/facc" "$S/runtime/p2p" "$D.tmp/" && cp "$S/{TUNE}" "$D.tmp/"',
             'cd "$D.tmp"']
    lines += [f'test "$(sha256sum {shlex.quote(name)} | cut -d" " -f1)" = {digest}' for name, digest in sorted(SO_SHA256.items())]
    lines += [f'test "$(sha256sum {TUNE} | cut -d" " -f1)" = {TUNE_SHA256}',
              f"find . -type f -not -name {TUNE} -not -path '*/__pycache__/*' | LC_ALL=C sort | xargs sha256sum > SHA256SUMS",
              f'echo {base64.b64encode(attest).decode()} | base64 -d > attest.sh',
              f'test "$(sha256sum < attest.sh | cut -d" " -f1)" = {hashlib.sha256(attest).hexdigest()}',
              'chmod 0555 attest.sh && chmod -R a-w stock facc p2p SHA256SUMS',
              'cd && mv "$D.tmp" "$D" && sh "$D/attest.sh"',
              f'echo "$(hostname): staged PP4 runtime {PP4_ID}"']
    return '\n'.join(lines) + '\n'


def render_verify_process() -> str:
    """bash for x86host: the TP2 unit runs the attested sampled worker from exactly this drop-in, now (prints one line)."""
    short = PP4_COMMIT[:7]
    return f'''set -eu
u={UNIT}
d=$HOME/{DROPIN}
test "$(sha256sum < "$d" | cut -d' ' -f1)" = {sha(render_dropin())}
systemctl --user show -p DropInPaths --value $u | tr ' ' '\\n' | grep -qx "$d"
test "$(systemctl --user show -p NeedDaemonReload --value $u)" = no
test "$(systemctl --user is-active $u)" = active
sh $HOME/dsv41-offload/prod/pp4-runtime/{PP4_ID}/attest.sh
pid=$(systemctl --user show -p MainPID --value $u)
test "$pid" -gt 0
test "$(tr '\\0' '\\n' < /proc/$pid/cmdline | head -1)" = {PYTHON}
test "$(readlink /proc/$pid/cwd)" = "$HOME/dsv41-offload/prod/dspark-worker/{short}/offload/dspark"
tr '\\0' '\\n' < /proc/$pid/environ | grep -qx DSPARK_SAMPLED_TOP32=1
tr '\\0' '\\n' < /proc/$pid/environ | grep -qx DSPARK_SOURCE_COMMIT={PP4_COMMIT}
rt=$HOME/dsv41-offload/prod/pp4-runtime/{PP4_ID}
tr '\\0' '\\n' < /proc/$pid/environ | grep -qx "PYTHONPATH=$rt/stock:$rt/facc:$HOME/dsv41-offload/prod/dspark-worker/{short}/offload/dspark"
echo "PP4 WORKER SAMPLED pid $pid"
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('what', choices=('dropin', 'attest', 'stage-runtime', 'verify-process', 'dropin-sha256'))
    args = parser.parse_args(argv)
    text = {'dropin': render_dropin, 'attest': render_attest, 'stage-runtime': render_stage_runtime,
            'verify-process': render_verify_process}.get(args.what)
    if text is None:
        print(sha(render_dropin()))
    else:
        sys.stdout.write(text())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
