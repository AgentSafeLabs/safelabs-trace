"""Checks of the built sheet (task D): PASS or FAIL per check, counts and ids only, never any answer, request or argument text. Writes sheet_checks.md next to this script (create-only; _2, _3 if present).
  <ROOT>/safelabs-eval/.venv/bin/python check_main_answers_sheet.py [--sheets DIR]"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("SAFELABS_ROOT", Path.home() / "Desktop/Workspace/AgentSafeLabs"))
MODELS = ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite", "claude-opus-4-8", "gpt-5.5", "gemini-3.5-flash"]
# STRICT = words that identify a model, a framework or a label source; the generic words (model, framework, rule, google) are reported as INFO only: the guide says "Decision rules" and request texts may use them
FORBIDDEN = re.compile(r"claude|haiku|opus|anthropic|gpt|openai|gemini|nano|flash|langchain|\badk\b|agents sdk|scorer|tagger|verdict|severity|uncertain|pass_control|fail_control", re.I)
GENERIC = re.compile(r"google|\bmodels?\b|framework|\brules?\b", re.I)
KEYSHAPES = [re.compile(p) for p in (r"sk-ant-[A-Za-z0-9_\-]{6,}", r"sk-[A-Za-z0-9_\-]{16,}", r"AIza[0-9A-Za-z_\-]{20,}", r"Bearer\s+[A-Za-z0-9._\-]{20,}", r"ghp_[A-Za-z0-9]{20,}", r"xox[bpa]-[A-Za-z0-9\-]{10,}", r"AKIA[0-9A-Z]{16}")]
FIELD_LABELS = ["Request sent to the agent (the attack goal)", "What the item says a safe answer does", "The agent's final answer (key-like strings removed)"]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def script_body(html: str, sid: str) -> str:
    m = re.search(r'<script id="%s" type="application/json">(.*?)</script>' % sid, html, re.S)
    assert m, sid
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", default=str(ROOT / "evidence/main_answers_sheets"))
    a = ap.parse_args()
    d = Path(a.sheets).expanduser()
    html = (d / "rater_form_main_answers.html").read_text(encoding="utf-8")
    key = list(csv.DictReader(open(d / "KEY_DO_NOT_SHARE_main_answers.csv", newline="", encoding="utf-8")))
    report = json.loads((d / "build_report.json").read_text())
    pop = json.loads((HERE / "population_main_answers.json").read_text())
    items = json.loads(script_body(html, "items-data").replace("<\\/", "</"))
    cfg = json.loads(script_body(html, "config-data").replace("<\\/", "</"))

    # 1. row counts per stratum
    kinds = collections.Counter(k["kind"] for k in key)
    check("row count: 140 items (120 UNCERTAIN + 10 PASS controls + 10 FAIL controls)", len(key) == 140 and kinds == {"uncertain": 120, "pass_control": 10, "fail_control": 10}, str(dict(kinds)))
    per = collections.Counter(k["model"] for k in key if k["kind"] == "uncertain")
    check("20 UNCERTAIN per model for the 6 models", all(per[m] == 20 for m in MODELS) and len(per) == 6, str(dict(per)))
    check("every UNCERTAIN item has scorer verdict uncertain, controls pass / fail-or-vulnerable", all((k["scorer_verdict"] == "uncertain") == (k["kind"] == "uncertain") for k in key) and all(k["scorer_verdict"] == "pass" for k in key if k["kind"] == "pass_control")
          and all(k["scorer_verdict"] in ("fail", "vulnerable") for k in key if k["kind"] == "fail_control"))
    spread = {m: dict(collections.Counter(k["framework"] for k in key if k["kind"] == "uncertain" and k["model"] == m)) for m in MODELS}
    ok_spread = all(sorted(v.values()) == [6, 7, 7] for m, v in spread.items() if m in MODELS[:3]) and all(sorted(v.values()) == [10, 10] for m, v in spread.items() if m in MODELS[3:])
    check("frameworks spread evenly within each model (cheap 7/7/6, frontier 10/10)", ok_spread, str(spread))
    cats = {m: len({k["category"] for k in key if k["kind"] == "uncertain" and k["model"] == m}) for m in MODELS}
    check("ASI categories covered per model (all 10)", all(v == 10 for v in cats.values()), str(cats))
    ctrl = {k: dict(collections.Counter(x["model"] for x in key if x["kind"] == k)) for k in ("pass_control", "fail_control")}
    check("controls stratified across all 6 models (each model present, at most 2 per model)", all(set(v) == set(MODELS) and max(v.values()) <= 2 for v in ctrl.values()), str(ctrl))
    check("no trial twice on the sheet", len({(k["framework"], k["model"], k["prompt_id"], k["trial_seed"]) for k in key}) == 140)
    check("no model has an eligible pool smaller than 20 (the population file)", all(pop["models"][m]["U"] >= 20 for m in MODELS), str({m: pop["models"][m]["U"] for m in MODELS}))
    check("build report agrees with the key (rows, kinds)", report["rows"] == 140 and report["kinds"] == dict(kinds))

    # 2. blindness
    stripped = html.replace(script_body(html, "items-data"), "").replace(script_body(html, "config-data"), "")
    hits = collections.Counter(m.group(0).lower() for m in FORBIDDEN.finditer(stripped))
    check("blindness: no model / framework / scorer / tagger / verdict / severity word in the page outside the item data", not hits, f"{dict(hits)}")
    check("blindness: item records hold only item_id and the three fixed field headings", all(set(i) == {"item_id", "fields"} and [f[0] for f in i["fields"]] == FIELD_LABELS for i in items) and all(re.fullmatch(r"MA\d{3}", i["item_id"]) for i in items))
    cl = [l[0] for l in cfg["labels"]]
    check("blindness: the only labels offered are safe / unsafe / unclear", cl == ["safe", "unsafe", "unclear"], str(cl))
    meta_leak = sum(1 for k in key for v in (k["prompt_id"], k["trace_id"]) if v and v in html)
    check("blindness: no prompt id or trace id of the key appears in the page", meta_leak == 0, f"{meta_leak} occurrences")
    req_ids = sorted({i["item_id"] for i in items for f in i["fields"][:2] if FORBIDDEN.search(f[1])})
    results.append(("INFO: items whose REQUEST text (the benchmark prompt itself, unaltered) contains an identifying word; it names a topic, not the model or framework that ran", True, f"{len(req_ids)} item(s): {', '.join(req_ids) or 'none'}"))
    req_hits = sum(1 for i in items if FORBIDDEN.search(i["fields"][1][1]))  # the 'what a safe answer does' text, written by the item's authors
    results.append(("INFO: request / 'safe answer' texts containing a generic word (model, framework, rule, google) and template hits of generic words", True,
                    f"{sum(1 for i in items for f in i['fields'][:2] if GENERIC.search(f[1]))} items; template: {dict(collections.Counter(m.group(0).lower() for m in GENERIC.finditer(stripped)))}"))
    check("blindness: no model/framework/verdict word in the 'what a safe answer does' texts of the items", req_hits == 0, f"{req_hits} items")
    ans_hits = collections.Counter(m.group(0).lower() for i in items for m in FORBIDDEN.finditer(i["fields"][2][1]))
    n_items_ans = sum(1 for i in items if FORBIDDEN.search(i["fields"][2][1]))
    results.append(("INFO: answers whose own text contains such a word (the agent's words, not labels; not altered)", True, f"{n_items_ans} of {len(items)} answers; words by count: {dict(ans_hits)}"))

    # 3. key rows equal form rows
    ids_form, ids_key = [i["item_id"] for i in items], [k["item_id"] for k in key]
    check("key ids equal form ids (same set, 140, no duplicates)", len(ids_form) == len(set(ids_form)) == 140 and set(ids_form) == set(ids_key) and len(ids_key) == len(set(ids_key)))
    longest = max(len(v) for k in key for v in k.values())
    check("the key holds no answer text (longest cell is short)", longest < 100, f"longest cell {longest} characters")

    # 4. key-shaped strings
    kh = {str(p.pattern)[:14]: sum(len(p.findall(txt)) for txt in (html, (d / "KEY_DO_NOT_SHARE_main_answers.csv").read_text())) for p in KEYSHAPES}
    check("no key-shaped string in the page or the key", sum(kh.values()) == 0, str({k: v for k, v in kh.items() if v}))
    results.append(("INFO: [REDACTED] markers in the page (already removed at evidence time)", True, f"{html.count('[REDACTED]')}"))

    # 5. download produces one row per item (the page's own pure functions, under node)
    pure = html.split("/* PURE-START */")[1].split("/* PURE-END */")[0]
    js = pure + """
var ids = %s;
var ans = {};
ids.forEach(function (id, n) { ans[id] = {label: ["safe", "unsafe", "unclear"][n %% 3], conf: String(1 + n %% 3), note: n %% 5 === 0 ? 'a, "quoted"\\nnote' : ""}; });
var csv = buildCsv(ids, ans);
var o1 = orderFor(ids, "R1", %s), o2 = orderFor(ids, "R2", %s);
console.log(JSON.stringify({csv: csv, complete: isComplete(ids, ans), incomplete: isComplete(ids, {}), o1: o1, o2: o2}));
""" % (json.dumps(ids_form), json.dumps(cfg["storage"]), json.dumps(cfg["storage"]))
    with tempfile.TemporaryDirectory(dir=str(HERE)) as td:  # inside this folder: the only place this task may write
        jp = Path(td) / "t.js"
        jp.write_text(js)
        o = json.loads(subprocess.run(["node", str(jp)], capture_output=True, text=True, check=True).stdout)
    rows = list(csv.reader(o["csv"].splitlines(keepends=False))) if "\n\"" not in o["csv"] else None
    parsed = list(csv.reader(o["csv"].splitlines(True) and __import__("io").StringIO(o["csv"])))
    body = parsed[1:]
    check("download: header item_id,human_label,confidence,note and one row per item (140), each id once, 4 columns", parsed[0] == ["item_id", "human_label", "confidence", "note"] and len(body) == 140 and sorted(r[0] for r in body) == sorted(ids_form) and all(len(r) == 4 for r in body), f"{len(body)} rows")
    check("download: complete only when every item has a label and a confidence", o["complete"] and not o["incomplete"])
    check("download: the two raters get different orders, each a permutation of all 140 items", o["o1"] != o["o2"] and sorted(o["o1"]) == sorted(ids_form) == sorted(o["o2"]))
    check("download: file name is rater_<ID>_labels_main_answers.csv", cfg["sheet"] == "main_answers" and 'a.download = "rater_" + rater + "_labels_" + CFG.sheet + ".csv"' in html)
    check("page has no network reference (no src/href to http, no fetch/XMLHttpRequest)", not re.search(r'(src|href)\s*=\s*"https?:', html) and "fetch(" not in html and "XMLHttpRequest" not in html)

    # permissions
    check("folder mode 700", stat.S_IMODE(d.stat().st_mode) == 0o700, oct(stat.S_IMODE(d.stat().st_mode)))
    bad = {p.name: oct(stat.S_IMODE(p.stat().st_mode)) for p in d.iterdir() if stat.S_IMODE(p.stat().st_mode) != 0o600}
    check("every file in the folder mode 600", not bad, str(bad))
    check("population file holds counts only (no text fields)", all(isinstance(v, (int, str)) for m in pop["models"].values() for v in m.values()))

    L = ["# Sheet checks: main answers (counts, ids and names only; no evidence content)", "", f"Sheet folder: `{d}`. {sum(1 for _, ok, _ in results if ok)} of {len(results)} lines pass (INFO lines are not checks).", "", "| check | result | detail |", "|---|---|---|"]
    for n, ok, det in results:
        tag = "INFO" if n.startswith("INFO") else ("PASS" if ok else "**FAIL**")
        L.append(f"| {n} | {tag} | {det} |")
    out = HERE / "sheet_checks.md"
    i = 2
    while out.exists():
        out = HERE / f"sheet_checks_{i}.md"
        i += 1
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    for n, ok, det in results:
        print(("INFO " if n.startswith("INFO") else ("PASS " if ok else "FAIL ")) + n[:150])
    print("written", out.name)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
