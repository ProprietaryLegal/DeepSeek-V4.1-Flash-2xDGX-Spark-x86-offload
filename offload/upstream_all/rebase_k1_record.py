#!/usr/bin/env python3
"""UPSTREAM-INSTALL (2026-10-28): rebase the K1 promotion record onto the upstream-all dsv41.env and start.sh.

Run on sparkhead from ~/dsv41-deploy with prod/upstream-all checked out (coordinator, inside the install window):

    python3 offload/upstream_all/rebase_k1_record.py

K1's start guard (offload/promote/k1/manage.py verify) refuses a start unless dsv41.env and start.sh equal the hashes
in logs/k1-promotion/files.json["promoted"]. This rewrites ONLY those two hashes, and only from 596ba1c's promoted
pair, from an earlier upstream-all rebase (its pre-rebase copy holds 596ba1c's pair), or idempotently. "original" (the pre-K1 backup) is untouched. The pre-rebase record is
copied to logs/upstream-all/files.json.pre-rebase first (exclusive); INSTALL-ALL/ROLLBACK.sh restores the record
byte for byte from Controller's backup.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "logs/k1-promotion/files.json"
SAVE = ROOT / "logs/upstream-all/files.json.pre-rebase"
BASE_PROMOTED = {  # production 596ba1c
    "dsv41.env": "faa9d3e0019a8665f0b61dbf46a79134680731d43b9a9cb99ca2fa5af85373a8",
    "start.sh": "fa172986fcb3e9ee66fd62b6dc11435ec7a56abdc60247ad1e73d85fa561ad5d",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    record = json.loads(RECORD.read_text())
    now = {name: sha(ROOT / name) for name in BASE_PROMOTED}
    if record["promoted"] == now:
        print(f"K1 record already rebased onto upstream-all: {now}")
        return
    rebased_before = SAVE.exists() and json.loads(SAVE.read_text())["promoted"] == BASE_PROMOTED
    if record["promoted"] != BASE_PROMOTED and not rebased_before:
        raise SystemExit(f"K1 record promoted={record['promoted']} is neither 596ba1c's nor this checkout's; refusing")
    SAVE.parent.mkdir(parents=True, exist_ok=True)
    if not SAVE.exists():
        shutil.copy2(RECORD, SAVE)
    record["promoted"] = now
    tmp = RECORD.with_name(".files.json.upstream-all")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    tmp.replace(RECORD)
    print(f"K1 record rebased: promoted {BASE_PROMOTED} -> {now}; pre-rebase copy {SAVE}")


if __name__ == "__main__":
    main()
