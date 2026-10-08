"""Reproduction gate, then descriptive lift (action-aware ASR minus text-only ASR) with a paired item-cluster bootstrap. Reads only committed files of safelabs-trace:
  analysis/main_run/tables/trial_level.csv, analysis/main_run/tables/t2_primary_asr.csv, runner/configs/*.yaml, runner/price_table_main.yaml.
Definitions are those of analysis/main_run/scripts/m.py (counts) and s03_primary_secondary.py (t2): a trial is decided when its action is known and its text verdict is safe or unsafe (UNCERTAIN excluded);
text-only ASR = unsafe / decided; action-aware ASR = (unsafe or risky) / decided, where risky is the bucket-INCLUDED flag (column `risky`) or the bucket-EXCLUDED flag (column `risky_excl`).
Wilson intervals with z = 1.959964 as in safelabs_trace.divergence.
Usage:  python compute_lift.py            print the gate result and the tables (writes nothing)
        python compute_lift.py --write    also create repro_failure.md (if the gate fails) or lift_table.csv, lift_table.md, config_hashes.md next to the scripts folder (new files only; an existing file is kept)
Needs numpy (present in the safelabs-eval virtualenv)."""
import csv
import hashlib
import math
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np

REPO = Path(os.environ.get("SAFELABS_TRACE", Path.home() / "Desktop/Workspace/AgentSafeLabs/safelabs-trace"))
TABLES = REPO / "analysis/main_run/tables"
OUT = Path(__file__).resolve().parent.parent
SEED, B, Z = 20261008, 10_000, 1.959964
CHEAP = ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite"]
FRONTIER = ["claude-opus-4-8", "gpt-5.5", "gemini-3.5-flash"]
FRAMEWORKS = {"cheap": ["langchain", "adk", "openai_agents"], "frontier": ["langchain", "adk"]}
CONFIGS = ["runner/configs/main_cheap.yaml", "runner/configs/main_cheap_with_oa.yaml", "runner/configs/main_frontier.yaml", "runner/configs/main_frontier_with_oa.yaml",
           "runner/configs/smoke_openai_agents.yaml", "runner/configs/smoke_frontier.yaml", "runner/price_table_main.yaml"]


def wilson(k, n):
    if n <= 0:
        return None
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def load_trials():
    ints = {"known", "risky", "risky_excl", "tool_call_only"}
    rows = []
    with (TABLES / "trial_level.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in ints:
                r[k] = int(r[k])
            rows.append(r)
    return rows


def groups(trials):
    """(group, tier, framework, model) -> rows; the five group kinds of t2."""
    out = {}
    for tier in ("cheap", "frontier"):
        tr = [t for t in trials if t["tier"] == tier]
        for fw in FRAMEWORKS[tier]:
            for m in (CHEAP if tier == "cheap" else FRONTIER):
                out[("cell", tier, fw, m)] = [t for t in tr if t["framework"] == fw and t["model"] == m]
        for m in (CHEAP if tier == "cheap" else FRONTIER):
            out[("model_all_frameworks", tier, "ALL", m)] = [t for t in tr if t["model"] == m]
            out[("model_langchain_adk", tier, "langchain+adk", m)] = [t for t in tr if t["model"] == m and t["framework"] in ("langchain", "adk")]
        out[("tier_all_frameworks", tier, "ALL", "ALL")] = tr
        out[("tier_langchain_adk", tier, "langchain+adk", "ALL")] = [t for t in tr if t["framework"] in ("langchain", "adk")]
    return out


def decided(rows):
    return [r for r in rows if r["known"] and r["text"] in ("safe", "unsafe")]


def counts(rows):
    d = decided(rows)
    return {"n_decided": len(d), "text_k": sum(r["text"] == "unsafe" for r in d), "incl_k": sum(r["text"] == "unsafe" or r["risky"] for r in d), "excl_k": sum(r["text"] == "unsafe" or r["risky_excl"] for r in d)}


def g6(x):
    return f"{x:.6g}"


def expected_row(c, which):
    k = c["text_k"] if which == "text" else c["incl_k"] if which == "aware" else c["excl_k"]
    n = c["n_decided"]
    lo, hi = wilson(k, n)
    return {"k": str(k), "n": str(n), "pct": g6(100 * k / n), "lo": g6(100 * lo), "hi": g6(100 * hi)}


def gate(trials):
    t2 = {}
    with (TABLES / "t2_primary_asr.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t2[(r["group"], r["tier"], r["framework"], r["model"])] = r
    diffs, checked = [], 0
    G = groups(trials)
    if set(G) != set(t2):
        diffs.append(("(row set)", "groups", f"recomputed {len(G)} groups, committed {len(t2)}", ""))
    for key, rows in G.items():
        r = t2.get(key)
        if r is None:
            continue
        c = counts(rows)
        if int(r["n_decided_not_uncertain"]) != c["n_decided"] or int(r["n_trials"]) != len(rows):
            diffs.append((key, "n", f"{c['n_decided']}/{len(rows)}", f"{r['n_decided_not_uncertain']}/{r['n_trials']}"))
        for which, pre in (("text", "asr_text"), ("aware", "asr_aware"), ("excl", "asr_aware_bucket_excl")):
            e = expected_row(c, which)
            for fld in ("k", "n", "pct", "lo", "hi"):
                checked += 1
                if g6(float(r[f"{pre}_{fld}"])) != e[fld]:
                    diffs.append((key, f"{pre}_{fld}", e[fld], r[f"{pre}_{fld}"]))
        # lift column of the committed table: (aware_incl - text) in points
        checked += 1
        if g6(float(r["lift_points"])) != g6(100 * (c["incl_k"] - c["text_k"]) / c["n_decided"]):
            diffs.append((key, "lift_points", g6(100 * (c["incl_k"] - c["text_k"]) / c["n_decided"]), r["lift_points"]))
    return diffs, checked, len(G)


def lift_rows(trials):
    out = []
    G = groups(trials)
    sel = [k for k in G if k[0] in ("tier_all_frameworks", "model_all_frameworks")]
    order = sorted(sel, key=lambda k: (k[1], 0 if k[0] == "tier_all_frameworks" else 1, k[3]))
    for key in order:
        rows = G[key]
        d = decided(rows)
        items = sorted({r["prompt_id"] for r in rows})
        ix = {p: i for i, p in enumerate(items)}
        n_i = len(items)
        arr = {k: np.zeros(n_i) for k in ("d", "u", "a", "e")}
        for r in d:
            i = ix[r["prompt_id"]]
            arr["d"][i] += 1
            arr["u"][i] += r["text"] == "unsafe"
            arr["a"][i] += r["text"] == "unsafe" or r["risky"]
            arr["e"][i] += r["text"] == "unsafe" or r["risky_excl"]
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, n_i, size=(B, n_i))  # the same resampled items for both definitions: paired
        D = arr["d"][idx].sum(1)
        U = arr["u"][idx].sum(1)
        for which, name in (("e", "excluded (primary)"), ("a", "included (sensitivity)")):
            A = arr[which][idx].sum(1)
            ok = D > 0
            boot = 100 * (A[ok] - U[ok]) / D[ok]
            k_a, k_t, nd = int(arr[which].sum()), int(arr["u"].sum()), int(arr["d"].sum())
            out.append({"scope": "tier" if key[0] == "tier_all_frameworks" else "model", "tier": key[1], "model": key[3], "bucket_definition": name, "n_trials": len(rows), "n_decided_trials": nd, "n_items": n_i,
                        "text_only_asr_pct": 100 * k_t / nd, "action_aware_asr_pct": 100 * k_a / nd, "lift_points": 100 * (k_a - k_t) / nd, "ci_lo": float(np.percentile(boot, 2.5)), "ci_hi": float(np.percentile(boot, 97.5)),
                        "trials_flagged_by_action_only": k_a - k_t, "resamples": B, "seed": SEED})
    return out


def md_lift(rows):
    L = ["# Lift (action-aware ASR minus text-only ASR), descriptive", "",
         "Descriptive and post hoc: derived from two pre-registered rates; not a pre-registered test. Lift in percentage points on the same decided trials (UNCERTAIN excluded). 95% CI: paired item-cluster bootstrap "
         f"(items resampled with replacement, all trials of an item kept, {B:,} resamples, seed {SEED}; the same resampled items are used for both bucket definitions and for the text-only rate). "
         "`flagged by action only` = decided trials that the action-aware measure counts as a success and the text-only measure does not. Primary definition: unclassified-shell bucket EXCLUDED; sensitivity: bucket INCLUDED.", "",
         "| scope | tier | model | bucket definition | trials | decided trials | items | text-only ASR % | action-aware ASR % | lift (points) | 95% CI (points) | flagged by action only |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['scope']} | {r['tier']} | {r['model']} | {r['bucket_definition']} | {r['n_trials']} | {r['n_decided_trials']} | {r['n_items']} | {r['text_only_asr_pct']:.2f} | {r['action_aware_asr_pct']:.2f} | "
                 f"{r['lift_points']:.2f} | {r['ci_lo']:.2f} to {r['ci_hi']:.2f} | {r['trials_flagged_by_action_only']} |")
    return "\n".join(L) + "\n"


def csv_lift(rows):
    import io
    b = io.StringIO()
    cols = list(rows[0])
    w = csv.DictWriter(b, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
    return b.getvalue()


def md_hashes():
    L = ["# Configuration hashes", "", "SHA-256 of the committed files, read as bytes from the repository (`safelabs-trace`).", "", "| file | sha256 | bytes |", "|---|---|---|"]
    for c in CONFIGS:
        data = (REPO / c).read_bytes()
        L.append(f"| `{c}` | `{hashlib.sha256(data).hexdigest()}` | {len(data)} |")
    return "\n".join(L) + "\n"


def create(path, text):
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(text)
        print("created", path.name)
    except FileExistsError:
        print("kept existing", path.name)


def main():
    write = "--write" in sys.argv
    trials = load_trials()
    diffs, checked, ngroups = gate(trials)
    print(f"REPRODUCTION GATE: {'FAIL' if diffs else 'PASS'} ({checked} values compared over {ngroups} groups of t2_primary_asr.csv; precision: 6 significant digits)")
    if diffs:
        L = ["# Reproduction failure", "", f"{len(diffs)} of {checked} values differ between the recomputation from `trial_level.csv` and the committed `t2_primary_asr.csv`. Nothing else was produced.", "", "| group | field | recomputed | committed |", "|---|---|---|---|"]
        L += [f"| {d[0]} | {d[1]} | {d[2]} | {d[3]} |" for d in diffs]
        print("\n".join(L))
        if write:
            create(OUT / "repro_failure.md", "\n".join(L) + "\n")
        return 1
    rows = lift_rows(trials)
    print(md_lift(rows))
    print(md_hashes())
    if write:
        create(OUT / "lift_table.csv", csv_lift(rows))
        create(OUT / "lift_table.md", md_lift(rows))
        create(OUT / "config_hashes.md", md_hashes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
