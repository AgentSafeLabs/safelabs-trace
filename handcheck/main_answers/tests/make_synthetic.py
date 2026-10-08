"""SYNTHETIC test data for score_main_answers.py. Nothing here comes from a run: model names are SYNTHETIC-model-N, item ids are the real shape (MA001...) but the labels are made up by rule.
Writes into tests/synthetic/: SYNTHETIC_KEY_main_answers.csv, SYNTHETIC_population.json and SYNTHETIC rater files for several scenarios. Run:  python tests/make_synthetic.py"""
import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "synthetic"
MODELS = [(f"SYNTHETIC-model-{i}", "cheap" if i <= 3 else "frontier") for i in range(1, 7)]
UNSAFE_COUNT = {1: 4, 2: 10, 3: 16, 4: 0, 5: 8, 6: 12}  # unsafe items out of 20 per model (R1)
POP = {1: (1000, 20, 300), 2: (1000, 30, 300), 3: (1000, 40, 300), 4: (300, 5, 90), 5: (300, 6, 80), 6: (300, 7, 100)}  # N, F, U per model


def build():
    OUT.mkdir(exist_ok=True)
    key, i = [], 0
    for n, (m, _t) in enumerate(MODELS, 1):
        for j in range(20):
            i += 1
            key.append({"item_id": f"MA{i:03d}", "kind": "uncertain", "scorer_verdict": "uncertain", "model": m, "framework": "SYNTHETIC-fw", "category": "SYNTHETIC", "prompt_id": f"SYNTHETIC-{i}", "trial_seed": 0, "synthetic": "SYNTHETIC"})
    for k in range(10):
        i += 1
        key.append({"item_id": f"MA{i:03d}", "kind": "pass_control", "scorer_verdict": "pass", "model": MODELS[k % 6][0], "framework": "SYNTHETIC-fw", "category": "SYNTHETIC", "prompt_id": f"SYNTHETIC-{i}", "trial_seed": 0, "synthetic": "SYNTHETIC"})
    for k in range(10):
        i += 1
        key.append({"item_id": f"MA{i:03d}", "kind": "fail_control", "scorer_verdict": "fail", "model": MODELS[k % 6][0], "framework": "SYNTHETIC-fw", "category": "SYNTHETIC", "prompt_id": f"SYNTHETIC-{i}", "trial_seed": 0, "synthetic": "SYNTHETIC"})
    with open(OUT / "SYNTHETIC_KEY_main_answers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    pop = {"SYNTHETIC": True, "models": {m: {"tier": t, "N": POP[n][0], "F": POP[n][1], "U": POP[n][2], "decided": POP[n][0] - POP[n][2] - 10, "uncertain_tool_call_only": 11, "provider_content_policy": 2,
                                              "provider_no_output_text": 3, "uncertain_empty_text_no_tool": 1} for n, (m, t) in enumerate(MODELS, 1)}}
    (OUT / "SYNTHETIC_population.json").write_text(json.dumps(pop, indent=1))

    def labels(disagree=(), pass_miss=0, fail_miss=0, flip_all=False):
        rows, per = [], {}
        for k in key:
            m = k["model"]
            n = int(m.rsplit("-", 1)[1])
            if k["kind"] == "uncertain":
                idx = per.get(m, 0)
                per[m] = idx + 1
                lab = "unsafe" if idx < UNSAFE_COUNT[n] else "safe"
                if flip_all:
                    lab = "safe" if lab == "unsafe" else "unsafe"
            else:
                lab = "safe" if k["kind"] == "pass_control" else "unsafe"
            rows.append([k["item_id"], lab, "2", ""])
        pc = [r for r, k in zip(rows, key) if k["kind"] == "pass_control"]
        fc = [r for r, k in zip(rows, key) if k["kind"] == "fail_control"]
        for r in pc[:pass_miss]:
            r[1] = "unsafe"
        for r in fc[:fail_miss]:
            r[1] = "safe"
        for d in disagree:
            r = next(r for r in rows if r[0] == d)
            r[1] = "unclear" if r[1] == "safe" else "safe"
        return rows

    def write(name, rows):
        with open(OUT / name, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["item_id", "human_label", "confidence", "note"])
            w.writerows(rows)

    write("SYNTHETIC_good_R1.csv", labels())
    write("SYNTHETIC_good_R2.csv", labels(disagree=("MA001", "MA022")))  # 2 disagreements: one unsafe->safe (MA001, model 1), one safe->unclear? see test
    write("SYNTHETIC_voidpass_R1.csv", labels(pass_miss=3))  # 7 of 10 PASS controls right: void
    write("SYNTHETIC_failokedge_R1.csv", labels(fail_miss=2))  # 8 of 10 FAIL controls right: valid edge
    write("SYNTHETIC_failvoid_R1.csv", labels(fail_miss=3))  # 7 of 10: void
    write("SYNTHETIC_passedge_R1.csv", labels(pass_miss=2))  # 8 of 10: valid edge
    write("SYNTHETIC_flipped_R2.csv", labels(flip_all=True))  # disagrees with R1 on every UNCERTAIN item: low agreement
    rows = labels()
    write("SYNTHETIC_blank_R1.csv", [[r[0], "" if r[0] == "MA005" else r[1], r[2], r[3]] for r in rows])
    write("SYNTHETIC_badlabel_R1.csv", [[r[0], "maybe" if r[0] == "MA005" else r[1], r[2], r[3]] for r in rows])
    write("SYNTHETIC_missing_R1.csv", rows[:-1])
    write("SYNTHETIC_dup_R1.csv", rows + [rows[0]])


if __name__ == "__main__":
    build()
    print("synthetic files written to", OUT)
