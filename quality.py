#!/usr/bin/env python3
"""Knowledge-work acceptance suite (fictional records only). Automatic checks + full outputs saved for human review.
  ./quality.py [--long 150000 250000]      -> logs/quality-<ts>.json"""
import argparse, json, random, re, time, urllib.request, uuid

URL = "http://localhost:8000/v1/chat/completions"
MODEL = "DeepSeek-V4.1-Flash-1017-EXL3-Spark-TP2"


def chat(messages, max_tokens=3000, thinking=False, temperature=1.0, tools=None, **kw):
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "top_p": 1.0,
            "chat_template_kwargs": {"thinking": thinking}, "cache_salt": uuid.uuid4().hex, **kw}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time(); r = json.load(urllib.request.urlopen(req, timeout=3600)); r["_secs"] = round(time.time() - t0, 1)
    return r


RECORD = """FICTIONAL CASE RECORD — In re the Marriage of Calloway (Family Court, fictional county), Case No. 2025-DR-99-0142

Exhibit 1 (Affidavit of Renata Calloway, sworn 2025-02-11): "I have been the primary caregiver since our daughter Juniper was
born on 2018-06-30. Since the separation on 2024-09-02, Tomas has exercised visitation only on alternating weekends. On
2024-12-21 he returned Juniper at 9:40 p.m., almost four hours late, and he smelled of alcohol."

Exhibit 2 (Affidavit of Tomas Calloway, sworn 2025-02-18): "We separated on 2024-08-15, not in September. I have had Juniper
every Wednesday overnight and alternating weekends. On December 21, 2024, I returned Juniper at 7:15 p.m. because of an ice
storm on I-26; I texted Renata at 5:52 p.m. I had one beer at lunch, more than six hours earlier."

Exhibit 3 (Text messages, 2024-12-21, phone extraction report DCN-448120): 5:52 p.m. Tomas -> Renata: "Roads iced over, running
late, sorry." 9:31 p.m. Renata -> Tomas: "Where are you??" 9:38 p.m. Tomas -> Renata: "Pulling in now."

Exhibit 4 (Riverbend Elementary attendance record): Juniper absent 2025-01-06, 2025-01-07, 2025-01-08 (illness, excused) and
2025-01-27 (unexcused). Tardy 6 times between 2024-09-03 and 2025-01-31; 5 of the 6 tardies were on Thursdays.

Exhibit 5 (Guardian ad litem interim note, 2025-03-04, GAL Priscilla Nwosu): "Both homes appropriate. Juniper reports she 'likes
Wednesday nights at Dad's.' Mother's concerns about alcohol not corroborated to date; I have requested Father's consent to a
hair-follicle test, which he gave on 2025-03-03. Results pending."

Exhibit 6 (Bank statement excerpt, joint account ending 4471): 2024-08-29 withdrawal $6,250.00 (teller, Tomas); 2024-09-05 deposit
$1,100.00 (Renata, payroll)."""

SYNTH_Q = ("You are assisting a family-law attorney. Using ONLY the record, write (A) a dated chronology, (B) a table of every "
           "factual conflict between the parties with the competing versions and the evidence bearing on each, and (C) what "
           "the record does NOT establish. Quote exact dates, times, amounts and exhibit numbers. Do not invent facts.")

ARG_Q = ("Using only the record, write a structured analysis for a temporary-custody hearing with headings: Known Facts, "
         "Disputed Facts, Issues, Analysis, Conclusion. Do not cite any real case law or statutes; where legal authority "
         "would be needed write [AUTHORITY NEEDED]. Flag every inference as an inference.")

DRAFT_Q = ("Draft a supplemental affidavit for Tomas Calloway responding to Exhibit 1, consistent with Exhibits 2, 3 and 5. "
           "Numbered paragraphs, first person, professional tone, a caption, and a jurat block with blanks. Do not add facts "
           "that are not in the record; where a fact would be needed, insert [TO BE CONFIRMED].")

FACTS = {"birth 2018-06-30": ["2018-06-30", "June 30, 2018"], "separation conflict 08-15 vs 09-02": ["08-15", "August 15"],
         "text 5:52": ["5:52"], "9:38 pull in": ["9:38"], "DCN-448120": ["448120"], "$6,250": ["6,250"],
         "unexcused 01-27": ["01-27", "January 27"], "5 of 6 Thursday tardies": ["Thursday"], "GAL Nwosu": ["Nwosu"],
         "hair-follicle pending": ["pending"]}
INVENTED = [r"\bv\.\s+[A-Z][a-z]+", r"S\.C\. Code", r"\d+\s+S\.E\.2d", r"§\s*\d", r"Ann\. §"]


def score_facts(text):
    t = text.replace("‑", "-")
    hits = {k: any(v.lower() in t.lower() for v in vs) for k, vs in FACTS.items()}
    inv = [p for p in INVENTED if re.search(p, text)]
    return hits, inv


def long_doc(n_tokens, seed):
    rng = random.Random(seed)
    lines, approx = [], 0
    while approx < n_tokens:
        s = (f"[Log {len(lines) + 1}] {rng.choice(['Mother', 'Father', 'GAL', 'Counselor', 'School'])} noted on "
             f"20{rng.randint(20, 25)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d} that "
             f"{rng.choice(['pickup', 'homework', 'a dentist visit', 'soccer practice', 'a reimbursement'])} was "
             f"{rng.choice(['discussed', 'rescheduled', 'confirmed', 'disputed'])} (ref {rng.randint(10000, 99999)}).")
        lines.append(s); approx += len(s) / 3.6
    needles = [(0.03, "SPECIAL NOTE A: the safe-deposit box is number 1187 at Palmetto Trust, opened 2019-04-02."),
               (0.5, "SPECIAL NOTE B: the father's new employer is Halvard Freight; start date 2025-01-13; salary $71,400."),
               (0.97, "SPECIAL NOTE C: the mother conceded on 2025-02-27 that the December 21 late return was weather-related.")]
    k = len(lines)
    for pos, s in sorted(needles, reverse=True):
        lines.insert(int(k * pos), s)
    return "\n".join(lines)


TOOLS = [{"type": "function", "function": {"name": "search_exhibits", "description": "Full-text search of the case exhibits",
          "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                         "exhibit_numbers": {"type": "array", "items": {"type": "integer"}}}, "required": ["query"]}}},
         {"type": "function", "function": {"name": "compute_days_between", "description": "Days between two ISO dates",
          "parameters": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
                         "required": ["start", "end"]}}}]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--long", type=int, nargs="*", default=[150000])
    a = ap.parse_args(); out = []

    def rec(name, r, auto):
        m = r["choices"][0]["message"]
        row = {"test": name, "secs": r["_secs"], "usage": r["usage"], "finish": r["choices"][0]["finish_reason"],
               "auto": auto, "content": m.get("content"), "tool_calls": m.get("tool_calls")}
        out.append(row); print(json.dumps({k: row[k] for k in ("test", "secs", "finish", "auto")})[:600], flush=True)

    for name, q in [("synthesis", SYNTH_Q), ("argument", ARG_Q), ("drafting", DRAFT_Q)]:
        r = chat([{"role": "user", "content": RECORD + "\n\n" + q}], max_tokens=4000)
        hits, inv = score_facts(r["choices"][0]["message"]["content"] or "")
        auto = {"facts_hit": f"{sum(hits.values())}/{len(hits)}", "missed": [k for k, v in hits.items() if not v],
                "invented_authority_patterns": inv}
        if name == "argument":
            c = r["choices"][0]["message"]["content"]
            auto["headings"] = all(h.lower() in c.lower() for h in ["Known Facts", "Disputed Facts", "Issues", "Analysis", "Conclusion"])
            auto["authority_needed_marks"] = c.count("[AUTHORITY NEEDED]")
        if name == "drafting":
            c = r["choices"][0]["message"]["content"]
            auto["to_be_confirmed_marks"] = c.count("[TO BE CONFIRMED]"); auto["numbered_paras"] = len(re.findall(r"^\s*\d+\.", c, re.M))
        rec(name, r, auto)

    # synthesis with thinking on (quality comparison)
    r = chat([{"role": "user", "content": RECORD + "\n\n" + SYNTH_Q}], max_tokens=12000, thinking=True)
    hits, inv = score_facts(r["choices"][0]["message"]["content"] or "")
    rec("synthesis_thinking", r, {"facts_hit": f"{sum(hits.values())}/{len(hits)}", "missed": [k for k, v in hits.items() if not v],
                                  "invented_authority_patterns": inv})

    # tool calling: search -> result -> compute -> result -> answer
    msgs = [{"role": "system", "content": "Use the tools; answer only from tool results."},
            {"role": "user", "content": "How many days passed between the date the father says the parties separated and "
                                        "the date the mother's affidavit was sworn? Search the exhibits first."}]
    steps = []
    for _ in range(4):
        r = chat(msgs, max_tokens=2000, tools=TOOLS); m = r["choices"][0]["message"]; msgs.append(m)
        if not m.get("tool_calls"):
            break
        for tc in m["tool_calls"]:
            fn, args = tc["function"]["name"], json.loads(tc["function"]["arguments"])
            steps.append({"fn": fn, "args": args})
            if fn == "search_exhibits":
                res = {"results": [{"exhibit": 2, "text": "We separated on 2024-08-15, not in September."},
                                   {"exhibit": 1, "text": "Affidavit of Renata Calloway, sworn 2025-02-11"}]}
            else:
                from datetime import date
                res = {"days": (date.fromisoformat(args["end"]) - date.fromisoformat(args["start"])).days}
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res)})
    final = msgs[-1].get("content") or ""
    out.append({"test": "tool_chain", "steps": steps, "final": final,
                "auto": {"correct_180_days": "180" in final, "n_calls": len(steps)}})
    print(json.dumps(out[-1])[:600], flush=True)

    for n in a.long:
        doc = long_doc(n, seed=n)
        q = ("From the log above only: (1) the safe-deposit box number and bank, (2) the father's new employer, start date "
             "and salary, (3) what the mother conceded and when. Then explain in two sentences how note C bears on Exhibit 1 "
             "of the Calloway matter if it were part of that record.")
        r = chat([{"role": "user", "content": f"Session {uuid.uuid4().hex}\n" + doc + "\n\n" + q}], max_tokens=800, temperature=0.0)
        c = r["choices"][0]["message"]["content"] or ""
        auto = {"prompt_tokens": r["usage"]["prompt_tokens"], "A": "1187" in c and "Palmetto" in c,
                "B": "Halvard" in c and "71,400" in c and "2025-01-13" in c.replace("January 13, 2025", "2025-01-13"),
                "C": "2025-02-27" in c.replace("February 27, 2025", "2025-02-27") and "weather" in c.lower()}
        rec(f"long_retrieval_{n}", r, auto)

    fn = f"logs/quality-{time.strftime('%Y%m%dT%H%M%S')}.json"; json.dump(out, open(fn, "w"), indent=1); print("->", fn)


if __name__ == "__main__":
    main()
