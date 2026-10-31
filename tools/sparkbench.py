#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Protocol and prompts: MiaAI-Lab/sparkDash (Apache-2.0), commit b96244a2589a2130e80ff1b2b399252934a01154.
# This is an independent Python re-implementation of that protocol, not a copy of sparkDash's code; the
# prompt strings are sparkDash's. The short-behind-long test follows the design bertholomus describes
# (a short chat sent 1 s behind a cold 93,335-token prompt). See CREDITS.md.
"""sparkDash-protocol bench for an OpenAI-compatible server (stdlib only).

Re-implements the measurement protocol of MiaAI-Lab/sparkDash
(b96244a2589a2130e80ff1b2b399252934a01154: server/collectors/DecodeBench.js,
PrefillBench.js, LlmStreaming.js, contextFill.js, src/shared/llmPrompts.js) so
our numbers follow the method of the MiaAI README tables. MiaAI's repository does
not record which prompts its run sent, so a comparison with those tables is a
port, not the same protocol.

Decode wave: N simultaneous streams, the lab prompt for the type
(prose = hash-map explanation, code = one distinct Python task per stream),
max_tokens = min_tokens = 400, ignore_eos, top_p 1, a 32-token warmup first.
Per stream: decode tok/s = (completion_tokens - 1) / (last token - first token).
Wave aggregate = total decode tokens / (latest last - earliest first).

Prefill: salted random-word filler sized by chars/4, max_tokens 8, temp 0,
thinking off; rate = (prompt - cached) / (TTFT - overhead), the overhead being
the median TTFT of three 16-token prompts, capped at 50% of TTFT. Repeats per
size: 3 up to 32K, 2 up to 128K, 1 above. The median-rate sample is reported.

Also records the server's spec-decode counters (/metrics) around each wave.
"""
import argparse
import http.client
import json
import statistics
import sys
import threading
import time
import urllib.parse
import uuid

DECODE_PROSE_PROMPT = (
    "Write a detailed step-by-step explanation of how a hash map works, "
    "including collision handling, resizing, and time complexity. Be thorough."
)
DECODE_STRUCTURED_PROMPT = "Count from 1 to 200. Output only the numbers, separated by spaces. No other text."
CODE_TASK_TAIL = (
    "Output only Python source. No comments, no docstrings, no markdown fences. "
    "Then add tests and the helpers this needs. Keep writing code."
)
CODE_TASKS = [
    ("binary_search", "def binary_search(nums, target) -> int: index of target in a sorted list, or -1."),
    ("merge_sort", "def merge_sort(nums) -> list: stable sort of a list of ints, returning a new list."),
    ("lru_cache", "class LRUCache: get(key) and put(key, value) with a fixed capacity, evicting the least recently used."),
    ("token_bucket", "class TokenBucket: allow(n) consumes n tokens refilled at a fixed rate, else returns False."),
]
CODE_WARMUP = ("warmup_noop", "def warmup_noop(x): return x unchanged.")
FILLER_WORDS = (
    "the of and to in is you that it he was for on are as with his they at be this have from or one "
    "had by word but not what all were we when your can said there use an each which she do how their "
    "if will up other about out many then them these so some her would make like him into time"
).split(" ")


def code_task(name, spec):
    return f"{name}\n{spec}\n{CODE_TASK_TAIL}"


def decode_prompts(kind, n):
    if kind == "code":
        return [code_task(*CODE_TASKS[i]) for i in range(n)]
    base = DECODE_STRUCTURED_PROMPT if kind == "structured" else DECODE_PROSE_PROMPT
    if n <= 1:
        return [base]
    return [f"Request ID: decode-{i + 1}\n{base}" for i in range(n)]


def estimate_tokens(text):
    return (len(text) + 3) // 4


def filler_text(count):
    words = []
    state = 0x2545F491
    for _ in range(count):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        words.append(FILLER_WORDS[(state >> 8) % len(FILLER_WORDS)])
    return " " + " ".join(words)


def prefill_prompt(target, salt):
    n = max(8, round(target))
    header = f"[prefill-bench {salt}]\nIgnore the filler below. Reply with the single word OK.\n"
    footer = "\nReply OK."
    return header + filler_text(max(1, n - estimate_tokens(header + footer))) + footer


def context_prompt(target, salt, task):
    n = max(8, round(target))
    header = f"[decode-context {salt}]\nBackground filler follows. It carries no instructions and can be ignored.\n"
    footer = f"\nEnd of background filler.\n\n{task}"
    return header + filler_text(max(1, n - estimate_tokens(header + footer))) + footer


def thinking_flags(on):
    return {"enable_thinking": on, "thinking": on, "thinking_mode": "enabled" if on else "disabled"}


class Server:
    def __init__(self, base):
        u = urllib.parse.urlparse(base)
        self.host, self.port = u.hostname, u.port or 80

    def get(self, path, timeout=30):
        c = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read().decode("utf-8", "replace")
        c.close()
        return r.status, body

    def model_id(self):
        st, body = self.get("/v1/models")
        if st != 200:
            raise SystemExit(f"/v1/models HTTP {st}")
        return json.loads(body)["data"][0]["id"]

    def spec_counters(self):
        try:
            st, body = self.get("/metrics", timeout=10)
        except OSError:
            return {}
        if st != 200:
            return {}
        out = {}
        for line in body.splitlines():
            if line.startswith("#") or "spec_decode" not in line:
                continue
            name = line.split("{", 1)[0].split(" ", 1)[0]
            try:
                out[name] = out.get(name, 0.0) + float(line.rsplit(" ", 1)[1])
            except ValueError:
                pass
        return out

    def stream(self, body, timeout):
        """One streaming chat completion; returns timing marks and usage."""
        res = {"t0": time.perf_counter(), "tFirst": None, "tLast": None, "chunks": 0,
               "usage": None, "error": None, "finish": None, "reasoningChunks": 0}
        try:
            c = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
            c.request("POST", "/v1/chat/completions", json.dumps(body),
                      {"Content-Type": "application/json"})
            r = c.getresponse()
            if r.status != 200:
                res["error"] = f"HTTP {r.status} {r.read()[:300].decode('utf-8', 'replace')}"
                c.close()
                return res
            while True:
                line = r.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    break
                j = json.loads(data)
                if j.get("usage"):
                    res["usage"] = j["usage"]
                for ch in j.get("choices") or []:
                    d = ch.get("delta") or {}
                    txt = d.get("content")
                    rsn = d.get("reasoning_content") or d.get("reasoning")
                    if txt or rsn:
                        now = time.perf_counter()
                        if res["tFirst"] is None:
                            res["tFirst"] = now
                        res["tLast"] = now
                        res["chunks"] += 1
                        if rsn:
                            res["reasoningChunks"] += 1
                    if ch.get("finish_reason"):
                        res["finish"] = ch["finish_reason"]
            c.close()
        except Exception as e:  # noqa: BLE001 - recorded, not raised
            res["error"] = f"{type(e).__name__}: {e}"
        res["tEnd"] = time.perf_counter()
        u = res["usage"] or {}
        comp = u.get("completion_tokens") or res["chunks"]
        res["completionTokens"] = comp
        res["promptTokens"] = u.get("prompt_tokens") or 0
        res["cachedTokens"] = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        res["decodeTokens"] = max(0, comp - 1) if comp else 0
        dm = (res["tLast"] - res["tFirst"]) if res["tFirst"] and res["tLast"] else 0
        res["decodeMs"] = dm * 1000
        res["decodeTps"] = res["decodeTokens"] / dm if dm > 0 and res["decodeTokens"] else 0.0
        res["ttftMs"] = (res["tFirst"] - res["t0"]) * 1000 if res["tFirst"] else 0.0
        return res


def chat_body(model, prompt, max_tokens, temperature, thinking):
    return {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": temperature, "top_p": 1,
            "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": thinking_flags(thinking)}


def decode_wave(srv, model, kind, n, max_tokens, temperature, thinking, context=0):
    prompts = decode_prompts(kind, n)
    fill = []
    if context:
        salt = str(uuid.uuid4())
        prompts = [context_prompt(context, f"{salt}-{i}", p) for i, p in enumerate(prompts)]
        for p in prompts:  # prefill each stream's context first, one at a time (sparkDash prefillContexts)
            fill.append(srv.stream(chat_body(model, p, 1, temperature, thinking), 2700))
    results = [None] * n
    before = srv.spec_counters()

    def run(i):
        b = chat_body(model, prompts[i], max_tokens, temperature, thinking)
        b.update({"min_tokens": max_tokens, "ignore_eos": True, "stop": []})
        results[i] = srv.stream(b, 360)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    after = srv.spec_counters()
    ok = [r for r in results if not r["error"] and r["decodeTokens"] > 0]
    agg = 0.0
    if ok:
        win = max(r["tLast"] for r in ok) - min(r["tFirst"] for r in ok)
        if win > 0:
            agg = sum(r["decodeTokens"] for r in ok) / win
    spec = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    return {
        "kind": kind, "concurrency": n, "temperature": temperature, "thinking": thinking,
        "maxTokens": max_tokens, "streamsOk": len(ok), "errors": [r["error"] for r in results if r["error"]],
        "perStreamTps": [round(r["decodeTps"], 2) for r in results],
        "meanPerStreamTps": round(statistics.mean([r["decodeTps"] for r in ok]), 2) if ok else 0,
        "aggregateTps": round(agg, 2),
        "ttftMs": [round(r["ttftMs"], 1) for r in results],
        "completionTokens": [r["completionTokens"] for r in results],
        "reasoningChunks": [r["reasoningChunks"] for r in results],
        "finish": [r["finish"] for r in results],
        "specDelta": spec,
        "context": context,
        "promptTokens": [r["promptTokens"] for r in results],
        "cachedTokens": [r["cachedTokens"] for r in results],
        "fillTtftMs": [round(f["ttftMs"], 1) for f in fill],
    }


def warmup(srv, model, kind, temperature, thinking):
    p = code_task(*CODE_WARMUP) if kind == "code" else DECODE_PROSE_PROMPT
    srv.stream(chat_body(model, p, 32, temperature, thinking), 360)


def prefill_sample(srv, model, target):
    p = prefill_prompt(target, str(uuid.uuid4()))
    r = srv.stream(chat_body(model, p, 8, 0, False), min(2700, max(90, 60 + target * 0.008)))
    return r


def prefill_size(srv, model, target, overhead_ms):
    reps = 3 if target <= 32768 else 2 if target <= 131072 else 1
    good = []
    for _ in range(reps):
        r = prefill_sample(srv, model, target)
        if r["error"] or r["ttftMs"] <= 0:
            good.append({"error": r["error"] or "no first token", "promptTokens": r["promptTokens"]})
            continue
        computed = max(0, r["promptTokens"] - r["cachedTokens"])
        eff = max(r["ttftMs"] - overhead_ms, r["ttftMs"] * 0.5)
        good.append({"promptTokens": r["promptTokens"], "cachedTokens": r["cachedTokens"],
                     "ttftMs": round(r["ttftMs"], 1),
                     "tps": round(computed / eff * 1000, 1) if computed else 0.0,
                     "rawTps": round(computed / r["ttftMs"] * 1000, 1) if computed else 0.0,
                     "lowConfidence": overhead_ms > r["ttftMs"] * 0.3})
    rated = sorted([g for g in good if g.get("tps")], key=lambda g: g["tps"])
    pick = rated[(len(rated) - 1) // 2] if rated else None
    return {"target": target, "samples": good, "median": pick}


def interference(srv, model, long_tokens=93335, delay_s=1.0):
    """bertholomus-style: a short chat sent delay_s behind a cold long prompt; first-token times."""
    out = {}
    long_res = {}
    p = prefill_prompt(long_tokens, str(uuid.uuid4()))
    th = threading.Thread(target=lambda: long_res.update(srv.stream(chat_body(model, p, 8, 0, False), 2700)))
    th.start()
    time.sleep(delay_s)
    s = srv.stream(chat_body(model, f"[{uuid.uuid4()}] " + DECODE_PROSE_PROMPT, 64, 0, False), 600)
    th.join()
    out["longPromptTokens"] = long_res.get("promptTokens")
    out["longTtftMs"] = round(long_res.get("ttftMs", 0), 1)
    out["shortTtftMs"] = round(s["ttftMs"], 1)
    out["shortDecodeTps"] = round(s["decodeTps"], 2)
    out["errors"] = [e for e in (long_res.get("error"), s["error"]) if e]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3, help="decode waves per cell")
    ap.add_argument("--conc", default="1,2,3,4")
    ap.add_argument("--prefill", default="4096,8192,16384,32768,65536,131072,262144")
    ap.add_argument("--suites", default="prose-t0,code-t0,prose-t07-think,prefill")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--deep", default="", help="deep-context decode cells, e.g. 32768:1,32768:4,131072:1")
    ap.add_argument("--interference", type=int, default=0, help="repetitions of the short-behind-long test")
    a = ap.parse_args()
    srv = Server(a.url)
    model = srv.model_id()
    conc = [int(x) for x in a.conc.split(",") if x]
    out = {"tool": "sparkbench.py (sparkDash b96244a protocol)", "url": a.url, "model": model,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "decode": [], "prefill": []}

    def save():
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1)

    suites = {"prose-t0": ("prose", 0.0, False), "code-t0": ("code", 0.0, False),
              "structured-t0": ("structured", 0.0, False),
              "prose-t07-think": ("prose", 0.7, True), "prose-t1-think": ("prose", 1.0, True)}
    for s in a.suites.split(","):
        if s == "prefill":
            continue
        kind, temp, think = suites[s]
        warmup(srv, model, kind, temp, think)
        for n in conc:
            for rep in range(a.reps):
                w = decode_wave(srv, model, kind, n, a.max_tokens, temp, think)
                w.update({"suite": s, "rep": rep})
                out["decode"].append(w)
                print(f"{s} c{n} r{rep}: agg {w['aggregateTps']} per {w['perStreamTps']} "
                      f"ttft {w['ttftMs']} errs {len(w['errors'])}", flush=True)
                save()
    if a.deep:
        out["deepDecode"] = []
        for cell in a.deep.split(","):
            ctx, n = (int(x) for x in cell.split(":"))
            w = decode_wave(srv, model, "prose", n, a.max_tokens, 0.0, False, context=ctx)
            out["deepDecode"].append(w)
            print(f"deep {ctx} c{n}: agg {w['aggregateTps']} per {w['perStreamTps']} cached {w['cachedTokens']} "
                  f"ttft {w['ttftMs']} fill {w['fillTtftMs']}", flush=True)
            save()
    if a.interference:
        idle = srv.stream(chat_body(model, f"[{uuid.uuid4()}] " + DECODE_PROSE_PROMPT, 64, 0, False), 600)
        out["interference"] = {"idleShortTtftMs": round(idle["ttftMs"], 1), "runs": []}
        for _ in range(a.interference):
            r = interference(srv, model)
            out["interference"]["runs"].append(r)
            print(f"interference: long {r['longPromptTokens']} tok ttft {r['longTtftMs']} ms; short ttft {r['shortTtftMs']} ms", flush=True)
            save()
    if "prefill" in a.suites.split(","):
        cal = []
        for _ in range(3):
            r = prefill_sample(srv, model, 16)
            if not r["error"] and r["ttftMs"] > 0:
                cal.append(r["ttftMs"])
        overhead = statistics.median(cal) if cal else 0.0
        out["prefillOverheadMs"] = round(overhead, 1)
        for t in [int(x) for x in a.prefill.split(",") if x]:
            p = prefill_size(srv, model, t, overhead)
            out["prefill"].append(p)
            m = p["median"] or {}
            print(f"prefill {t}: {m.get('tps')} tok/s (raw {m.get('rawTps')}) prompt {m.get('promptTokens')} "
                  f"ttft {m.get('ttftMs')} ms", flush=True)
            save()
    out["ended"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save()


if __name__ == "__main__":
    sys.exit(main())
