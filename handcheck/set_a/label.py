import csv, os
src, dst = "handcheck_items.csv", "handcheck_items_labelled.csv"
rows = list(csv.DictReader(open(dst if os.path.exists(dst) else src, newline="", encoding="utf-8")))
fields = list(rows[0].keys())
M = {"r": "read_only", "s": "state_changing", "i": "irreversible"}
def save():
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
for n, r in enumerate(rows, 1):
    if r["human_label"]:
        continue
    print(f"\n[{n}/{len(rows)}] {r['item_id']}  {r['tool_name']}\n  {r['tool_description']}\n  args: {r['arguments_summary']}")
    while (k := input("label  r=read_only  s=state_changing  i=irreversible: ").strip().lower()) not in M: pass
    while (c := input("confidence 1-3: ").strip()) not in ("1", "2", "3"): pass
    r["human_label"], r["confidence"], r["note"] = M[k], c, input("note (Enter to skip): ").strip()
    save()
print("\nDone:", sum(1 for r in rows if r["human_label"]), "of", len(rows), "labelled ->", dst)
