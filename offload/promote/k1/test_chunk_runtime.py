"""PROMO-8192: the K1 runtime check reads the prefill chunk from the running container's launch file.

CPU only. Every host command is a local stub; no service, ssh or HTTP is reached.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
sys.path.insert(0, str(PACKAGE))


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = load("check_runtime_chunk", PACKAGE / "check_runtime.py")
PROFILES = load("profiles_chunk", PACKAGE / "profiles.py")

# The launch file shape the recipe launcher writes (offload/launch/dsv41_tp2_offload.sh launch()).
ARGV = """#!/usr/bin/env bash
set -e
exec vllm serve '/srv/dsv41/legal-v2a' --served-model-name 'DeepSeek-V4.1-Flash-1017-EXL3-Spark-TP2' --host 0.0.0.0 --port 8000 \\
  --tensor-parallel-size 2 --nnodes 2 --node-rank 0 --master-addr 10.202.26.2 --master-port 25000 \\
  --gpu-memory-utilization 0.86 --max-model-len 327680 --max-num-seqs 4 \\
  --max-num-batched-tokens CHUNK --load-format auto \\
  --kv-cache-memory-bytes 6442450944 \\
  --limit-mm-per-prompt '{"image":4}' --mm-processor-cache-gb 0 --long-prefill-token-threshold 1024 --scheduling-policy priority --enable-prompt-tokens-details
"""


def log_line(kv: str, length: str = "327,680") -> str:
    return f"(EngineCore pid=7) GPU KV cache size: {kv} tokens, Maximum concurrency for {length} tokens per request: 5.90x\n"


def test_engine_kv_figure_is_registered_per_profile_and_chunk() -> None:
    small, large = PROFILES.get_profile("327680"), PROFILES.get_profile("524288")
    assert RUNTIME.expected_kv_tokens(small, 4096) == small.kv_tokens == 2502600
    assert RUNTIME.expected_kv_tokens(large, 4096) == large.kv_tokens
    assert RUNTIME.expected_kv_tokens(small, 8192) == 1934490
    for profile, chunk in ((large, 8192), (small, 16384), (small, 2048), (small, 0)):
        with pytest.raises(ValueError, match="no reviewed engine KV figure"):
            RUNTIME.expected_kv_tokens(profile, chunk)


def test_8192_figure_is_the_allocator_transcription_with_two_chunks_in_flight() -> None:
    arithmetic = load("kv_arith_chunk", REPO / "offload/kvpack/kv_arith.py")
    assert arithmetic.IN_FLIGHT == 2 * RUNTIME.PROFILE_CHUNK
    assert arithmetic.capacity(6442450944, 327680, 3, 14)[0] == 2502600
    setattr(arithmetic, "IN_FLIGHT", 2 * 8192)
    tokens, concurrency, blocks = arithmetic.capacity(6442450944, 327680, 3, 14)
    assert (tokens, blocks) == (RUNTIME.CHUNK_KV_TOKENS[("327680", 8192)], 46603)
    assert concurrency > 4  # still more than MAX_SEQS=4 full-length requests


@pytest.mark.parametrize("chunk", [4096, 8192])
def test_launched_chunk_reads_the_one_argv_value(chunk: int) -> None:
    assert RUNTIME.launched_chunk(ARGV.replace("CHUNK", str(chunk))) == chunk


@pytest.mark.parametrize("text", [
    ARGV.replace("--max-num-batched-tokens CHUNK ", ""),
    ARGV.replace("CHUNK", "8192 --max-num-batched-tokens 4096"),
    ARGV.replace("CHUNK", "8k"),
    "",
])
def test_launched_chunk_refuses_missing_repeated_or_malformed(text: str) -> None:
    with pytest.raises(ValueError):
        RUNTIME.launched_chunk(text)


def test_check_log_binds_the_figure_to_the_chunk() -> None:
    profile = PROFILES.get_profile("327680")
    RUNTIME.check_log(log_line("1,934,490"), profile, 8192)
    RUNTIME.check_log(log_line("2,502,600"), profile, 4096)
    RUNTIME.check_log(log_line("2,502,600"), profile)          # no chunk given: the unchanged 4096 contract
    for text, chunk in ((log_line("2,502,600"), 8192), (log_line("1,934,490"), 4096),
                        (log_line("1,934,490") + log_line("2,502,600"), 8192), ("", 8192),
                        (log_line("1,934,490", "524,288"), 8192)):
        with pytest.raises(ValueError):
            RUNTIME.check_log(text, profile, chunk)


def run_cli(tmp_path: Path, kv: str, serve: str | None) -> subprocess.CompletedProcess[str]:
    (tmp_path / "engine.log").write_text(log_line(kv))
    (tmp_path / "models.json").write_text(json.dumps({"data": [{"id": "alias", "max_model_len": 327680}]}))
    args = [sys.executable, str(PACKAGE / "check_runtime.py"), "--profile", "327680", "--log", str(tmp_path / "engine.log"),
            "--models", str(tmp_path / "models.json"), "--served", "alias"]
    if serve is not None:
        (tmp_path / "serve.sh").write_text(serve)
        args += ["--serve", str(tmp_path / "serve.sh")]
    return subprocess.run(args, text=True, capture_output=True, check=False)


def test_cli_reads_the_chunk_from_the_launch_file(tmp_path: Path) -> None:
    ok = run_cli(tmp_path, "1,934,490", ARGV.replace("CHUNK", "8192"))
    assert ok.returncode == 0, ok.stderr
    assert "KV 1,934,490 at chunk 8,192" in ok.stdout
    assert run_cli(tmp_path, "2,502,600", ARGV.replace("CHUNK", "4096")).returncode == 0
    assert run_cli(tmp_path, "2,502,600", None).returncode == 0
    for kv, serve in (("1,934,490", None), ("2,502,600", ARGV.replace("CHUNK", "8192")),
                      ("1,934,490", ARGV.replace("CHUNK", "4096")), ("1,330,447", ARGV.replace("CHUNK", "16384"))):
        refused = run_cli(tmp_path, kv, serve)
        assert refused.returncode == 1 and "K1 runtime REFUSED" in refused.stderr


VERIFY_SSH = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
while args and args[0] == '-o':
    args = args[2:]
node, cmd = args[0], args[1]
with open(os.environ['STUB_EVENTS'], 'a') as f:
    f.write(node + ' ' + cmd + '\\n')
if cmd == 'docker logs dsv41-serve 2>&1':
    print(os.environ['STUB_LOG'], end='')
elif cmd == 'docker exec dsv41-serve cat /serve.sh':
    print(os.environ['STUB_ARGV'], end='')
else:
    print('UNEXPECTED SSH: ' + cmd, file=sys.stderr)
    sys.exit(98)
'''


def verify_root(tmp_path: Path) -> Path:
    """verify.sh's real tail (evidence, launch file, models, check_runtime) with its two earlier gates stubbed."""
    root = tmp_path / "root"
    (root / "offload/promote/k1").mkdir(parents=True)
    for name in ("verify.sh", "check_runtime.py", "profiles.py", "constants.sh"):
        shutil.copy2(PACKAGE / name, root / "offload/promote/k1" / name)
    (root / "offload/promote/k1/manage.py").write_text("print('stub manage verify')\n")
    (root / "offload/kvpack").mkdir(parents=True)
    (root / "offload/kvpack/stage_overlay.sh").write_text("#!/bin/bash\necho stub verify-running\n")
    (root / "offload/kvpack/stage_overlay.sh").chmod(0o755)
    (root / "logs").mkdir()
    (root / "dsv41.env").write_text("HEAD=spark\nWORKER=sparkworker\nPORT=8000\nSERVED=alias\nPROD_K1=1\nPROD_K1_PROFILE=327680\n")
    (root / "bin").mkdir()
    (root / "bin/ssh").write_text(VERIFY_SSH)
    (root / "bin/curl").write_text('#!/bin/sh\necho \'{"data": [{"id": "alias", "max_model_len": 327680}]}\'\n')
    for name in ("ssh", "curl"):
        (root / "bin" / name).chmod(0o755)
    return root


@pytest.mark.parametrize("chunk, kv, ok", [(8192, "1,934,490", True), (4096, "2,502,600", True),
                                           (8192, "2,502,600", False), (4096, "1,934,490", False)])
def test_verify_sh_checks_the_running_containers_chunk(tmp_path: Path, chunk: int, kv: str, ok: bool) -> None:
    root = verify_root(tmp_path)
    env = dict(os.environ, PATH=f"{root / 'bin'}:{os.environ['PATH']}", STUB_EVENTS=str(root / "events"),
               STUB_LOG=log_line(kv), STUB_ARGV=ARGV.replace("CHUNK", str(chunk)))
    for key in list(env):
        if key.startswith("KVPACK_TEST_"):
            del env[key]
    result = subprocess.run(["bash", "offload/promote/k1/verify.sh"], cwd=root, env=env, text=True, capture_output=True,
                            check=False)
    events = (root / "events").read_text()
    assert "spark docker exec dsv41-serve cat /serve.sh" in events and "spark docker logs dsv41-serve 2>&1" in events
    if ok:
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"KV {kv} at chunk {chunk:,}" in result.stdout and "K1 runtime evidence: " in result.stdout
        evidence = Path(result.stdout.split("K1 runtime evidence: ")[1].split()[0])
        assert (root / evidence / "serve.sh").read_text() == ARGV.replace("CHUNK", str(chunk))
    else:
        assert result.returncode != 0 and "K1 runtime REFUSED" in result.stderr
