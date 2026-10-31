"""PROMO-MATTER: remove the CPU-tier regions stopped engines leave in /dev/shm (MC1-PROMOTION.plan.md §2.3).

Every engine start with the offloading connector creates /dev/shm/vllm_offload_<engine id>.mmap (root-owned, up to the
256 MiB CPU tier per Spark, counted against MemAvailable) and nothing unlinks it when the container stops (the serve
runs with --ipc host). Without this, every production restart would leak 256 MiB per Spark.

The production stop path removes them at the next start: serve.sh's matter block runs this on each Spark, in a
throwaway container of the serving image (`--ipc host --network none`, root: the regions are root-owned), ONLY after
`docker ps -q` showed no running container on that Spark, i.e. no process can still map a region (regions are
created only by vLLM engines inside containers). It runs whether the matter tier turns ON or OFF.

    docker run --rm -i --pull never --network none --ipc host --entrypoint python3 IMAGE - '/dev/shm/vllm_offload_*.mmap' < shm_clean.py

One JSON line: {"removed": n, "freed_bytes": b, "failed": f}; region names are engine ids, never printed.
"""
from __future__ import annotations

import glob
import json
import os
import sys

PATTERN = '/dev/shm/vllm_offload_*.mmap'


def clean(pattern: str = PATTERN) -> dict[str, int]:
    removed = freed = failed = 0
    for path in sorted(glob.glob(pattern)):
        try:
            size = os.stat(path, follow_symlinks=False).st_blocks * 512
            os.unlink(path)
        except FileNotFoundError:
            continue
        except OSError:
            failed += 1
            continue
        removed += 1
        freed += size
    return {'removed': removed, 'freed_bytes': freed, 'failed': failed}


if __name__ == '__main__':
    pattern = sys.argv[1] if len(sys.argv) > 1 else PATTERN
    if not pattern.endswith('/vllm_offload_*.mmap'):
        raise SystemExit('shm_clean: only vllm_offload_*.mmap regions are ever removed')
    print(json.dumps(clean(pattern), sort_keys=True))
