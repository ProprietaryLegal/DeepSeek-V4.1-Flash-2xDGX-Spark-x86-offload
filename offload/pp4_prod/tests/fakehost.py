"""Fake Spark hosts for the PP4 shell checks: a PATH with `ssh` and `docker` stand-ins (no socket, no daemon).

`ssh [-o X]... HOST CMD` runs CMD locally under bash with FAKE_NODE=HOST and HOME=<root>/HOST/home, so `$HOME` paths in a
command land in a per-node directory. `docker exec dsv41-serve sha256sum|find|cat /serve.sh` and `docker inspect
dsv41-serve` read <root>/HOST/container/<container path>, <root>/HOST/env and <root>/HOST/serve.sh.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat

SSH = r'''#!/bin/bash
echo "$*" >> "$FAKE_ROOT/ssh.log"
[ "${FAKE_SSH_DENY:-0}" = 1 ] && { echo "fake ssh denied: $*" >&2; exit 99; }
while [ $# -gt 0 ]; do
  case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac
done
host=$1; shift
mkdir -p "$FAKE_ROOT/$host/home"
FAKE_NODE=$host HOME=$FAKE_ROOT/$host/home exec bash -c "$*"
'''
DOCKER = r'''#!/bin/bash
root=$FAKE_ROOT/$FAKE_NODE/container
if [ "$1 $2" = "exec dsv41-serve" ]; then
  shift 2
  case "$1" in
    sha256sum) shift; rc=0
      for p in "$@"; do
        if [ -f "$root$p" ]; then echo "$(sha256sum < "$root$p" | cut -c1-64)  $p"; else echo "sha256sum: $p: missing" >&2; rc=1; fi
      done; exit $rc ;;
    find) d=$2; [ -d "$root$d" ] || exit 1; (cd "$root$d" && find . -maxdepth 1 -name '*.py' -type f | sed "s#^\.#$d#") ;;
    cat) cat "$FAKE_ROOT/$FAKE_NODE/serve.sh" ;;
    *) echo "fake docker exec: $*" >&2; exit 2 ;;
  esac
elif [ "$1 $2" = "inspect dsv41-serve" ]; then
  cat "$FAKE_ROOT/$FAKE_NODE/env"
elif [ "$1 $2" = "logs dsv41-serve" ]; then
  cat "$FAKE_ROOT/$FAKE_NODE/logs" 2>/dev/null || true
else
  echo "fake docker: $*" >&2; exit 2
fi
'''


def install(root: Path) -> dict[str, str]:
    """Write the stand-ins under root/bin; returns the environment to run a script with."""
    bin_dir = root / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, text in (('ssh', SSH), ('docker', DOCKER)):
        path = bin_dir / name
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'FAKE_ROOT': str(root)}


def container(root: Path, node: str, files: dict[str, bytes], env: list[str], serve: str, logs: str = '') -> None:
    """One node's running dsv41-serve: container files by container path, env lines (docker order), /serve.sh text,
    and its engine log (docker logs)."""
    base = root / node
    if (base / 'container').exists():
        shutil.rmtree(base / 'container')
    for path, data in files.items():
        target = base / 'container' / path.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (base / 'env').write_text('\n'.join(env) + '\n')
    (base / 'serve.sh').write_text(serve)
    (base / 'logs').write_text(logs)
