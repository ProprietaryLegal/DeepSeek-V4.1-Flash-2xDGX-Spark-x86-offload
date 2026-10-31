#!/usr/bin/env python3
"""UPSTREAM-INSTALL sanity checks (synthetic prompts only; no client content). Run on Controller against the live serve.

    python3 offload/upstream_all/sanity.py models --url URL
    python3 offload/upstream_all/sanity.py tool   --url URL --out DIR
    python3 offload/upstream_all/sanity.py load   --url URL --out DIR [--long 150000 --short 32000 --nshort 3]

models: /v1/models max_model_len. tool: one tool call (auto tool choice) and one JSON-object reply, both must parse.
load: one ~150K-token and three ~32K-token synthetic prompts at once (distinct texts, no shared prefix), while both
ranks' MemAvailable is sampled every second over ssh; reports every request's outcome, prompt tokens, first-token and
total time, and the free-memory floor per rank. Rows hold numbers only (no generated text).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from pathlib import Path
import random
import subprocess
import threading
import time
import urllib.request

MODEL = "DeepSeek-V4.1-Flash-1017-EXL3-Spark-TP2"
TOKENIZER = "/opt/dsv41/data/d2/tokenizer/tokenizer.json"
NODES = ("sparkhead", "sparkworker-wired")
WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec "
         "romeo sierra tango uniform victor whiskey xray yankee zulu river stone maple cedar copper silver orange "
         "purple window garden market harbor bridge tunnel valley summit").split()


def post(url: str, body: dict[str, object], timeout: float = 1800) -> dict[str, object]:
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        value: dict[str, object] = json.load(r)
        return value


def models(url: str) -> None:
    with urllib.request.urlopen(url.rstrip("/") + "/v1/models", timeout=15) as r:
        data = json.load(r)["data"][0]
    print(f"/v1/models: id {data['id']} root {data['root']} max_model_len {data['max_model_len']:,}")
    if data["max_model_len"] != 327680:
        raise SystemExit("max_model_len is not 327,680")


def tool(url: str, out: Path) -> None:
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "Current weather for a city.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
            "required": ["city", "unit"]}}}]
    body: dict[str, object] = {"model": MODEL, "temperature": 0, "max_tokens": 200, "tools": tools,
                               "tool_choice": "auto", "chat_template_kwargs": {"thinking": False},
                               "messages": [{"role": "user", "content": "What is the weather in Oslo in celsius? "
                                             "Use the tool."}]}
    r = post(url, body, 300)
    msg = r["choices"][0]["message"]  # type: ignore[index]
    calls = msg.get("tool_calls") or []  # type: ignore[union-attr]
    ok_tool = bool(calls) and calls[0]["function"]["name"] == "get_weather"
    args = json.loads(calls[0]["function"]["arguments"]) if ok_tool else {}
    ok_tool = ok_tool and isinstance(args, dict) and str(args.get("city", "")).lower() == "oslo"
    body2: dict[str, object] = {"model": MODEL, "temperature": 0, "max_tokens": 200,
                                "response_format": {"type": "json_object"}, "chat_template_kwargs": {"thinking": False},
                                "messages": [{"role": "user", "content": "Return only a JSON object with keys "
                                              "\"colors\" (a list of three color names) and \"count\" (the integer 3)."}]}
    r2 = post(url, body2, 300)
    text = r2["choices"][0]["message"]["content"]  # type: ignore[index]
    try:
        obj = json.loads(text)
        ok_json = isinstance(obj, dict) and obj.get("count") == 3 and len(obj.get("colors", [])) == 3
    except (ValueError, TypeError):
        obj, ok_json = None, False
    result = {"tool_call_parsed": ok_tool, "tool_name": calls[0]["function"]["name"] if calls else None,
              "tool_args": args, "finish_reason": r["choices"][0]["finish_reason"],  # type: ignore[index]
              "json_object_parsed": ok_json, "json_keys": sorted(obj) if isinstance(obj, dict) else None}
    (out / "tool.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result))
    if not (ok_tool and ok_json):
        raise SystemExit("tool/JSON call did not parse")


def synthetic(seed: int, tokens: int) -> str:
    import tokenizers  # Controller miniconda; the served model's tokenizer
    tok = tokenizers.Tokenizer.from_file(TOKENIZER)
    r = random.Random(seed)
    words: list[str] = []
    step = max(1000, tokens // 2)
    while len(tok.encode(" ".join(words)).ids) < tokens:
        words.extend(r.choice(WORDS) for _ in range(step))
        step = max(200, step // 2)
    while len(tok.encode(" ".join(words)).ids) > tokens:
        del words[-50:]
    return " ".join(words)


def sampler(stop: threading.Event, rows: dict[str, list[tuple[float, int]]]) -> list[subprocess.Popen[str]]:
    procs = []
    for node in NODES:
        p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", node,
                              "while true; do awk '/^MemAvailable:/{print $2}' /proc/meminfo; sleep 1; done"],
                             stdout=subprocess.PIPE, text=True)
        procs.append(p)

        def read(node: str = node, p: subprocess.Popen[str] = p) -> None:
            assert p.stdout is not None
            for line in p.stdout:
                if stop.is_set():
                    break
                rows[node].append((time.time(), int(line.strip())))
        threading.Thread(target=read, daemon=True).start()
    return procs


def load(url: str, out: Path, long: int, short: int, nshort: int) -> None:
    prompts = [("long", synthetic(1000, long))] + [(f"short{i}", synthetic(2000 + i, short)) for i in range(nshort)]
    mem: dict[str, list[tuple[float, int]]] = {n: [] for n in NODES}
    stop = threading.Event()
    procs = sampler(stop, mem)
    time.sleep(3)
    t0 = time.time()

    def one(name: str, text: str) -> dict[str, object]:
        body = {"model": MODEL, "temperature": 0, "max_tokens": 64, "stream": True,
                "stream_options": {"include_usage": True}, "chat_template_kwargs": {"thinking": False},
                "messages": [{"role": "user", "content": "Here is a list of words.\n\n" + text +
                              "\n\nHow many times does the word 'zulu' appear in the first line? Answer briefly."}]}
        req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        start = time.time(); first = None; usage = None; finish = None; chars = 0
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                for raw in r:
                    line = raw.decode().strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    ev = json.loads(line[6:])
                    for ch in ev.get("choices") or []:
                        piece = (ch.get("delta") or {}).get("content") or ""
                        if piece and first is None:
                            first = time.time() - start
                        chars += len(piece)
                        finish = ch.get("finish_reason") or finish
                    usage = ev.get("usage") or usage
            return {"name": name, "ok": finish in ("stop", "length"), "finish": finish, "ttft_s": first,
                    "total_s": round(time.time() - start, 2), "reply_chars": chars,
                    "prompt_tokens": (usage or {}).get("prompt_tokens"),
                    "completion_tokens": (usage or {}).get("completion_tokens")}
        except Exception as exc:  # noqa: BLE001 - every failure is recorded as a failed row, never hidden
            return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "total_s": round(time.time() - start, 2)}

    with cf.ThreadPoolExecutor(len(prompts)) as ex:
        results = list(ex.map(lambda p: one(*p), prompts))
    time.sleep(5)
    stop.set()
    for p in procs:
        p.terminate()
    floor = {n: (min(v for _, v in rows) // 1024 if rows else None) for n, rows in mem.items()}
    start_free = {n: (rows[0][1] // 1024 if rows else None) for n, rows in mem.items()}
    summary = {"wall_s": round(time.time() - t0, 1), "requests": results,
               "mem_available_floor_mib": floor, "mem_available_at_start_mib": start_free,
               "samples": {n: len(r) for n, r in mem.items()}, "all_ok": all(r["ok"] for r in results)}
    (out / "load.json").write_text(json.dumps(summary, indent=1) + "\n")
    (out / "load-mem.jsonl").write_text("".join(json.dumps({"node": n, "t": t, "kib": v}) + "\n"
                                                for n, rows in mem.items() for t, v in rows))
    print(json.dumps(summary, indent=1))
    if not summary["all_ok"]:
        raise SystemExit("a concurrent long request failed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", choices=("models", "tool", "load"))
    ap.add_argument("--url", default="http://HEAD_IP:8000")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--long", type=int, default=150000)
    ap.add_argument("--short", type=int, default=32000)
    ap.add_argument("--nshort", type=int, default=3)
    a = ap.parse_args()
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
    if a.what == "models":
        models(a.url)
    elif a.what == "tool":
        tool(a.url, a.out)
    else:
        load(a.url, a.out, a.long, a.short, a.nshort)


if __name__ == "__main__":
    main()
