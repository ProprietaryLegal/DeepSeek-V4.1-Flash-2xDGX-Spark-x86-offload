#!/usr/bin/env python3
"""Functional checks for the DSv4.1 TP2 serve. Writes logs/functest-<ts>.json with full outputs.
  ./functest.py [--long 150000]"""
import argparse, json, random, time, urllib.request, uuid

URL = "http://localhost:8000/v1"
MODEL = "DeepSeek-V4.1-Flash-1017-EXL3-Spark-TP2"


def post(body, stream=False, timeout=3600):
    body = {"model": MODEL, "temperature": 1.0, "top_p": 1.0, **body}
    req = urllib.request.Request(URL + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=timeout)
    if not stream:
        return json.load(r)
    chunks = []
    for line in r:
        line = line.decode().strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            chunks.append(json.loads(line[6:]))
    return chunks


def msg(r):
    return r["choices"][0]["message"]


RESULTS = []


def check(name, fn):
    t0 = time.time()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"EXCEPTION {e!r}"
    RESULTS.append({"test": name, "ok": ok, "secs": round(time.time() - t0, 1), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name} ({time.time() - t0:.0f}s): {str(detail)[:300]}", flush=True)


def t_basic():
    r = post({"messages": [{"role": "user", "content": "What is the capital of South Carolina? One word."}],
              "max_tokens": 400, "chat_template_kwargs": {"thinking": False}})
    c = msg(r)["content"]
    return "columbia" in c.lower(), {"content": c, "usage": r["usage"], "finish": r["choices"][0]["finish_reason"]}


def t_stream():
    ch = post({"messages": [{"role": "user", "content": "Count from 1 to 20 separated by commas."}], "max_tokens": 300,
               "stream": True, "chat_template_kwargs": {"thinking": False}}, stream=True)
    text = "".join((c["choices"][0]["delta"].get("content") or "") for c in ch if c.get("choices"))
    return ("20" in text and len(ch) > 5), {"chunks": len(ch), "text": text}


def t_json():
    r = post({"messages": [{"role": "user", "content": "Return JSON with keys name (string), filed (ISO date), "
                            "claims (array of strings) for: 'Jane Roe filed on March 3, 2025 claiming breach and fraud.'"}],
              "max_tokens": 600, "response_format": {"type": "json_object"}, "chat_template_kwargs": {"thinking": False}})
    c = msg(r)["content"]
    j = json.loads(c)
    return (j.get("filed") == "2025-03-03" and len(j.get("claims", [])) == 2), j


TOOLS = [{"type": "function", "function": {"name": "lookup_docket", "description": "Look up a court docket by case number",
          "parameters": {"type": "object", "properties": {"case_number": {"type": "string"},
                         "court": {"type": "string", "enum": ["family", "circuit", "magistrate"]}},
                         "required": ["case_number", "court"]}}}]


def t_tools():
    m = [{"role": "user", "content": "Look up family court case 2025-DR-23-0417 and tell me the next hearing date."}]
    r = post({"messages": m, "tools": TOOLS, "max_tokens": 1500, "chat_template_kwargs": {"thinking": False}})
    tc = msg(r).get("tool_calls") or []
    if not tc:
        return False, {"no tool call": msg(r)}
    args = json.loads(tc[0]["function"]["arguments"])
    ok1 = tc[0]["function"]["name"] == "lookup_docket" and args.get("case_number") == "2025-DR-23-0417" and args.get("court") == "family"
    m += [msg(r), {"role": "tool", "tool_call_id": tc[0]["id"],
                   "content": json.dumps({"case_number": "2025-DR-23-0417", "next_hearing": "2025-11-14T09:30",
                                          "judge": "Hon. A. Placeholder", "status": "temporary hearing"})}]
    r2 = post({"messages": m, "tools": TOOLS, "max_tokens": 1500, "chat_template_kwargs": {"thinking": False}})
    c2 = msg(r2)["content"] or ""
    ok2 = ("14" in c2 and "Nov" in c2) or "2025-11-14" in c2
    return ok1 and ok2, {"call": tc[0]["function"], "followup": c2, "finish": r2["choices"][0]["finish_reason"]}


def t_thinking(kw):
    def f():
        r = post({"messages": [{"role": "user", "content": "A train leaves at 9:40 and arrives at 13:05. How long is the trip?"}],
                  "max_tokens": 4000, "chat_template_kwargs": kw})
        m = msg(r)
        rc = m.get("reasoning_content") or m.get("reasoning") or ""
        c = m.get("content") or ""
        ok = ("3" in c and "25" in c)
        return ok, {"kw": kw, "reasoning_chars": len(rc), "content": c[-300:], "usage": r["usage"],
                    "finish": r["choices"][0]["finish_reason"]}
    return f


def t_prose():
    r = post({"messages": [{"role": "user", "content": "Write a 900-word professional letter from an attorney to a client "
              "explaining what to expect at a temporary custody hearing. Plain English, no legal citations."}],
              "max_tokens": 2500, "chat_template_kwargs": {"thinking": False}})
    c = msg(r)["content"]; words = c.split()
    # repetition check: share of repeated 8-grams
    grams = [" ".join(words[i:i + 8]) for i in range(len(words) - 8)]
    rep = 1 - len(set(grams)) / max(1, len(grams))
    return (len(words) > 600 and rep < 0.05 and r["choices"][0]["finish_reason"] == "stop"), \
        {"words": len(words), "rep8": round(rep, 4), "finish": r["choices"][0]["finish_reason"], "head": c[:300], "tail": c[-300:]}


def t_long(n_tokens):
    def f():
        rng = random.Random(7)
        needles = {"start": "The storage unit gate code is 4471-KESTREL.",
                   "middle": "Dr. Imogen Varga's invoice number was VX-90318 for $2,615.40.",
                   "end": "The child's soccer jersey number is 37 and the coach is named Bertrand Ollis."}
        filler = []
        approx = 0
        while approx < n_tokens:
            s = (f"[Entry {len(filler) + 1}] On 20{rng.randint(20, 25)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d} the "
                 f"parties exchanged messages about pickup times, school forms, and reimbursement of ${rng.randint(10, 900)}.")
            filler.append(s); approx += len(s) / 3.6
        k = len(filler)
        filler.insert(int(k * 0.9), needles["end"]); filler.insert(int(k * 0.5), needles["middle"]); filler.insert(int(k * 0.1), needles["start"])
        doc = f"Session {uuid.uuid4().hex}\n" + "\n".join(filler)
        q = ("Answer from the record only, in three numbered lines: (1) the storage unit gate code, (2) Dr. Varga's invoice "
             "number and amount, (3) the child's jersey number and the coach's name.")
        t0 = time.time()
        r = post({"messages": [{"role": "user", "content": doc + "\n\n" + q}], "max_tokens": 600, "temperature": 0.0,
                  "chat_template_kwargs": {"thinking": False}, "cache_salt": uuid.uuid4().hex})
        c = msg(r)["content"]
        hits = {"start": "4471-KESTREL" in c, "middle": "VX-90318" in c and "2,615.40" in c, "end": "37" in c and "Ollis" in c}
        return all(hits.values()), {"prompt_tokens": r["usage"]["prompt_tokens"], "secs": round(time.time() - t0, 1),
                                    "hits": hits, "answer": c}
    return f


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--long", type=int, nargs="*", default=[32000])
    a = ap.parse_args()
    check("basic chat", t_basic)
    check("streaming", t_stream)
    check("structured JSON", t_json)
    check("tool call + tool result round", t_tools)
    check("thinking default (on)", t_thinking({}))
    check("thinking off", t_thinking({"thinking": False}))
    for eff in ["none", "low", "high", "xhigh", "max"]:
        check(f"reasoning_effort={eff}", t_thinking({"reasoning_effort": eff}))
    check("long-form prose / repetition", t_prose)
    for n in a.long:
        check(f"long-doc needles ~{n} tokens", t_long(n))
    fn = f"logs/functest-{time.strftime('%Y%m%dT%H%M%S')}.json"
    json.dump(RESULTS, open(fn, "w"), indent=1)
    print(f"{sum(r['ok'] for r in RESULTS)}/{len(RESULTS)} passed -> {fn}")
