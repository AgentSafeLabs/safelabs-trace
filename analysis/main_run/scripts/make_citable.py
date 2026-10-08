"""Collects every registered number (tables/citable_*.json) plus the integrity and incident counts into citable_numbers_1b.md."""
from common import *  # noqa
import glob

items = []
for f in sorted(glob.glob(str(TABLES / "citable_*.json"))):
    items += json.loads(Path(f).read_text())
integ = json.loads((TABLES / "integrity.json").read_text())
inc = json.loads((TABLES / "incidents_main_cheap.json").read_text())
counts = [
    ("integrity.cheap.rows", "main_cheap rows in results.jsonl", integ["main_cheap"]["rows"], "tables/integrity.json", "s01_integrity"),
    ("integrity.frontier.rows", "main_frontier rows in results.jsonl", integ["main_frontier"]["rows"], "tables/integrity.json", "s01_integrity"),
    ("integrity.cheap.missing", "main_cheap missing_infrastructure rows at the end", integ["main_cheap"]["missing_infrastructure"], "tables/integrity.json", "s01_integrity"),
    ("integrity.frontier.missing", "main_frontier missing_infrastructure rows at the end", integ["main_frontier"]["missing_infrastructure"], "tables/integrity.json", "s01_integrity"),
    ("integrity.cheap.gaps_final", "main_cheap final-attempt traces with a model.call.start without an end", len(integ["main_cheap"]["start_without_end"]), "tables/integrity.json", "s01_integrity"),
    ("integrity.frontier.gaps_final", "main_frontier final-attempt traces with a model.call.start without an end", len(integ["main_frontier"]["start_without_end"]), "tables/integrity.json", "s01_integrity"),
    ("incident.haiku_rows", "main_cheap claude-haiku-4-5 rows scored on a credit error by the old runner (reclassified)", inc["scored_with_error"], "tables/incidents_main_cheap.json (runs/main_cheap/results.pre_reclassify_1.jsonl, repair_log.jsonl)", "s08_spend_and_incidents"),
    ("incident.gemini_missing", "main_cheap gemini-3.1-flash-lite rows missing after the first pass (Google 402 'prepayment credits are depleted')", inc["pre_repair_missing"], "tables/incidents_main_cheap.json", "s08_spend_and_incidents"),
]
L = ["# Citable numbers, 1B main run\n",
     "Each line: the number, n (and k), the Wilson 95% interval where the number is a rate, the file that holds it, and the command that produces it (run from the analysis folder with the safelabs-eval virtualenv Python; `python scripts/run_all.py` runs them all). "
     "Rates are over trials; percentages are in percent. Contrast entries are differences in percentage points of the item-level headline risky-action rate (bucket excluded); their intervals are item-bootstrap intervals, in the note. "
     "Entries marked EXPLORATORY are not pre-registered. Spend entries are price-table cost, not an invoice.\n",
     "| id | what | value | n (k) | 95% CI | source | command | note |", "|---|---|---|---|---|---|---|---|"]
for i in items:
    v = "" if i["value"] is None else (f"{i['value']:.2f} {i['unit']}" if i["unit"] != "%" else f"{i['value']:.1f}%")
    nk = "" if i["n"] is None else (f"{i['n']}" + (f" ({i['k']})" if i["k"] is not None else ""))
    ci = "" if not i["ci95"] else f"{i['ci95'][0]:.1f} to {i['ci95'][1]:.1f}"
    L.append(f"| {i['id']} | {i['label']} | {v} | {nk} | {ci} | {i['source']} | `{i['command']}` | {i['note']} |")
for ident, lab, val, src, scr in counts:
    L.append(f"| {ident} | {lab} | {val} | | | {src} | `python scripts/{scr}.py` | |")
(OUT / "citable_numbers_1b.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(len(items) + len(counts), "numbers written")
