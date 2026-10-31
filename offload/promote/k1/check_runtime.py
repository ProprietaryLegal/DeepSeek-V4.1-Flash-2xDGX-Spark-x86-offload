#!/usr/bin/env python3
"""Validate the new container's engine log and /v1/models response (CPU only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
from types import MappingProxyType
from typing import Mapping

from profiles import PROFILES, Profile, get_profile

# The allocator reports "GPU KV cache size" as int(num_blocks / blocks_per_request * max_model_len); each SWA group's
# admission cap in blocks_per_request covers two prefill chunks in flight (async scheduling), so the reported figure
# depends on --max-num-batched-tokens while the pool stays 46,603 blocks (offload/kvpack/kv_arith.py IN_FLIGHT).
# 4096 is the chunk every profile's reviewed kv_tokens was measured at. PROMO-8192: 327680 at 8192 = 1,934,490,
# offload/pc1/capacity.py expectation('chunk8192') and the sparkhead engine log of PC1-chunk8192-W-20261027T223211Z.
# Any other (profile, chunk) pair is refused, never extrapolated.
PROFILE_CHUNK = 4096
CHUNK_KV_TOKENS: Mapping[tuple[str, int], int] = MappingProxyType({("327680", 8192): 1934490})


def expected_kv_tokens(profile: Profile, chunk: int) -> int:
    if chunk == PROFILE_CHUNK:
        return profile.kv_tokens
    if (profile.name, chunk) not in CHUNK_KV_TOKENS:
        raise ValueError(f"no reviewed engine KV figure for profile {profile.name} at --max-num-batched-tokens {chunk}")
    return CHUNK_KV_TOKENS[(profile.name, chunk)]


def launched_chunk(text: str) -> int:
    """--max-num-batched-tokens of the running container's launch file (/serve.sh), stated exactly once."""
    argv = shlex.split(text.replace("\\\n", " "))
    if argv.count("--max-num-batched-tokens") != 1 or argv.index("--max-num-batched-tokens") + 1 >= len(argv):
        raise ValueError("launched /serve.sh must set --max-num-batched-tokens exactly once")
    value = argv[argv.index("--max-num-batched-tokens") + 1]
    if not value.isdigit():
        raise ValueError(f"launched --max-num-batched-tokens is not a number: {value!r}")
    return int(value)


def check_log(text: str, profile: Profile, chunk: int = PROFILE_CHUNK) -> None:
    # The allocator prints model_config.max_model_len as "tokens per request";
    # see image-v5 vllm/v1/core/kv_cache_utils.py:2486 and K1's overlay equivalent.
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    rows = re.findall(r"GPU KV cache size:\s*([\d,]+) tokens, Maximum concurrency for "
                      r"([\d,]+) tokens per request:", clean)
    values = [(int(k.replace(",", "")), int(m.replace(",", ""))) for k, m in rows]
    expected = (expected_kv_tokens(profile, chunk), profile.max_model_len)
    if not values or any(row != expected for row in values):
        raise ValueError(f"engine KV/max_model_len log mismatch: {values!r}; expected {expected}")


def check_models(text: str, served: str, profile: Profile) -> None:
    payload: object = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("/v1/models has no data list")
    entries = payload["data"]
    if len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("/v1/models must expose exactly the production alias")
    entry = entries[0]
    if entry.get("id") != served or type(entry.get("max_model_len")) is not int or entry["max_model_len"] != profile.max_model_len:
        raise ValueError("/v1/models alias/max_model_len differs from the K1 production contract")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=tuple(PROFILES))
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--models", required=True, type=Path)
    parser.add_argument("--served", required=True)
    parser.add_argument("--serve", type=Path, help="the running container's /serve.sh; its prefill chunk selects the "
                        "engine KV figure (absent: the profile's 4096 figure)")
    args = parser.parse_args()
    try:
        profile = get_profile(args.profile)
        chunk = PROFILE_CHUNK if args.serve is None else launched_chunk(args.serve.read_text())
        check_log(args.log.read_text(), profile, chunk)
        check_models(args.models.read_text(), args.served, profile)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"K1 runtime REFUSED: {exc}\n")
    print(f"K1 profile {profile.name}: KV {expected_kv_tokens(profile, chunk):,} at chunk {chunk:,}, "
          f"max_model_len {profile.max_model_len:,}; /v1/models agrees")


if __name__ == "__main__":
    main()
