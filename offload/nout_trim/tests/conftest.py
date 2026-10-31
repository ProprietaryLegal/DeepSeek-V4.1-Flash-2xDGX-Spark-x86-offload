# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the drafter request trim (NOUT-TRIM), CPU only, no vLLM install.

`import remote_dspark` resolves to the trimmed package (offload/nout_trim/overlay/remote_dspark); the simulated engine,
the reference worker and the vLLM stand-ins come from the remote DSpark test suite (offload/dspark/spark/tests). The
trimmed package carries no hostflag.c (its file set is production's), so the async hand-off library is compiled once
from offload/dspark/spark/remote_dspark/hostflag.c into the session's basetemp and found through
VLLM_DSPARK_REMOTE_OFL_DIR, as production finds /opt/dsv41-ofl/libdsv41_hostflag.so.

    python3 -m pytest -q offload/nout_trim/tests --basetemp <scratch>
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("TRITON_INTERPRET", "1")

HERE = Path(__file__).resolve().parent
NOUT = HERE.parent
ROOT = NOUT.parents[1]
OVERLAY = NOUT / "overlay"
SPARK = ROOT / "offload/dspark/spark"
for p in (str(SPARK / "tests"), str(OVERLAY)):      # the trimmed package first
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


@pytest.fixture(scope="session", autouse=True)
def hostflag_lib(tmp_path_factory: pytest.TempPathFactory) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler for hostflag.c")
    d = tmp_path_factory.mktemp("ofl")
    so = d / "libdsv41_hostflag.so"
    subprocess.run([cc, "-O2", "-Wall", "-shared", "-fPIC", "-o", str(so),
                    str(SPARK / "remote_dspark/hostflag.c"), "-lpthread"], check=True)
    os.environ["VLLM_DSPARK_REMOTE_OFL_DIR"] = str(d)
    return so
