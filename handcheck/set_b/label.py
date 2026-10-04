"""Terminal labeller for hand-check set B.

Run:  python label.py [items.csv [labelled.csv]]
Defaults: handcheck_b_items.csv and handcheck_b_items_labelled.csv in this folder. It shows one item at a time, asks for a label (r, s or i), a confidence (1, 2 or 3) and a note,
and saves after every item. If the labelled file exists it resumes at the first item that has no label. At the label prompt, typing b goes back to redo the previous item.
It reads nothing but the items file and the labelled file, and writes only the labelled file."""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = {"r": "read_only", "s": "state_changing", "i": "irreversible"}
COLUMNS = ["item_id", "tool_name", "tool_description", "arguments_summary", "human_label", "confidence", "note"]


def load_items(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_progress(items: list[dict], out: Path) -> dict[str, dict]:
    progress: dict[str, dict] = {}
    if out.exists():
        ids = {r["item_id"] for r in items}
        with open(out, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["item_id"] in ids and (r.get("human_label") or "").strip():
                    progress[r["item_id"]] = {"human_label": r["human_label"].strip(), "confidence": (r.get("confidence") or "").strip(), "note": r.get("note") or ""}
    return progress


def save(items: list[dict], progress: dict[str, dict], out: Path) -> None:
    tmp = out.with_name(out.name + ".part")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in items:
            p = progress.get(r["item_id"], {})
            w.writerow({**{c: r.get(c, "") for c in COLUMNS[:4]}, "human_label": p.get("human_label", ""), "confidence": p.get("confidence", ""), "note": p.get("note", "")})
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


def ask(prompt: str, valid: set[str], input_fn, print_fn) -> str:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in valid:
            return answer
        print_fn(f"Please type one of: {', '.join(sorted(valid))}")


def main(argv: list[str] | None = None, input_fn=input, print_fn=print) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    items_path = Path(args[0]) if args else HERE / "handcheck_b_items.csv"
    out_path = Path(args[1]) if len(args) > 1 else HERE / "handcheck_b_items_labelled.csv"
    items = load_items(items_path)
    n = len(items)
    progress = load_progress(items, out_path)
    if progress:
        print_fn(f"Resuming: {len(progress)} of {n} already labelled.")
    idx = next((i for i, r in enumerate(items) if r["item_id"] not in progress), n)
    try:
        while idx < n:
            r = items[idx]
            print_fn("")
            print_fn(f"Item {idx + 1} of {n}   ({r['item_id']})   Back: type b to redo the previous item")
            print_fn(f"  tool:        {r['tool_name']}")
            print_fn(f"  description: {r['tool_description']}")
            print_fn(f"  arguments:   {r['arguments_summary']}")
            done = progress.get(r["item_id"])
            if done:
                print_fn(f"  (current answer: {done['human_label']}, confidence {done['confidence']})")
            choice = ask("Label  r = read_only, s = state_changing, i = irreversible: ", set(LABELS) | {"b"}, input_fn, print_fn)
            if choice == "b":
                if idx == 0:
                    print_fn("There is no previous item.")
                else:
                    idx -= 1
                continue
            conf = ask("Confidence  1 = guess, 2 = fairly sure, 3 = certain: ", {"1", "2", "3"}, input_fn, print_fn)
            note = input_fn("Note (press Enter for none): ").strip()
            progress[r["item_id"]] = {"human_label": LABELS[choice], "confidence": conf, "note": note}
            save(items, progress, out_path)
            idx += 1
    except EOFError:
        print_fn("Input ended. Everything answered so far is saved.")
        return 1
    except KeyboardInterrupt:
        print_fn("\nStopped. Everything answered so far is saved.")
        return 130
    print_fn(f"\nAll {n} items labelled. Saved to {out_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
