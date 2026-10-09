"""Reproduction gate, then item-cluster bootstrap intervals for the primary rates. Reads only committed files of safelabs-trace/analysis/main_run:
tables/trial_level.csv, tables/t1_primary_risky_action.csv, tables/t2_primary_asr.csv, tables/t3_primary_verdict_coverage.csv.
Definitions (analysis/main_run/scripts/m.py, s03_primary_secondary.py): risky-action rate = risky (bucket included) or risky_excl (bucket excluded) over trials with a known action; text-only ASR = unsafe / decided;
action-aware flag rate (bucket excluded) = (unsafe or risky_excl) / decided, decided = known action and text verdict safe or unsafe (UNCERTAIN excluded); UNCERTAIN share = uncertain verdicts / all trials of the group.
Cluster bootstrap: the 300 items are resampled with replacement, every trial of a sampled item (all frameworks and repeats of the group) is kept, the rate is recomputed as a ratio of sums, 10,000 resamples, seed 20261009
(a fresh generator per group, shared by the five metrics of that group), percentile 95% interval. Wilson intervals are copied from the committed tables (z = 1.959964 is used only for the gate).
  python cluster_intervals.py            print the gate result and the tables (writes nothing)
  python cluster_intervals.py --write    also create cluster_intervals.csv/.md (or repro_failure.md if the gate fails), new files only. Needs numpy (safelabs-eval virtualenv)."""
import csv
import math
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np

REPO = Path(os.environ.get("SAFELABS_TRACE", Path.home() / "Desktop/Workspace/AgentSafeLabs/safelabs-trace"))
TB = REPO / "analysis/main_run/tables"
OUT = Path(__file__).resolve().parent.parent
SEED, B, Z = 20261009, 10_000, 1.959964
MODELS = {"cheap": ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite"], "frontier": ["claude-opus-4-8", "gpt-5.5", "gemini-3.5-flash"]}
# metric -> (table, committed column prefix, numerator rule, denominator rule)
METRICS = {
    "risky_action_rate_bucket_excluded (headline)": ("t1_primary_risky_action.csv", "risky_excl", "risky_excl", "known"),
    "risky_action_rate_bucket_included (upper bound)": ("t1_primary_risky_action.csv", "risky_incl", "risky", "known"),
    "text_only_asr": ("t2_primary_asr.csv", "asr_text", "unsafe", "decided"),
    "action_aware_flag_rate_bucket_excluded": ("t2_primary_asr.csv", "asr_aware_bucket_excl", "unsafe_or_risky_excl", "decided"),
    "uncertain_share": ("t3_primary_verdict_coverage.csv", "uncertain_share", "uncertain", "all"),
}


def wilson(k, n):
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def load_trials():
    rows = []
    with (TB / "trial_level.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in ("known", "risky", "risky_excl"):
                r[k] = int(r[k])
            rows.append(r)
    return rows


def flags(r):
    """per-trial indicators: numerators and denominators of every metric."""
    decided = r["known"] and r["text"] in ("safe", "unsafe")
    unsafe = r["text"] == "unsafe"
    return {"num": {"risky_excl": r["risky_excl"] if r["known"] else 0, "risky": r["risky"] if r["known"] else 0, "unsafe": int(decided and unsafe),
                    "unsafe_or_risky_excl": int(decided and (unsafe or r["risky_excl"])), "uncertain": int(r["verdict"] == "uncertain")},
            "den": {"known": int(r["known"]), "decided": int(decided), "all": 1}}


def groups(trials):
    out = []
    for tier in ("cheap", "frontier"):
        tr = [t for t in trials if t["tier"] == tier]
        for m in MODELS[tier]:
            out.append(("model", "model_all_frameworks", tier, "ALL", m, [t for t in tr if t["model"] == m]))
        out.append(("tier", "tier_all_frameworks", tier, "ALL", "ALL", tr))
    return out


def committed(table, group, tier, model):
    with (TB / table).open(newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            if r["group"] == group and r["tier"] == tier and r["model"] == model:
                return i + 2, r
    raise KeyError((table, group, tier, model))


g6 = lambda x: f"{x:.6g}"


def main():
    write = "--write" in sys.argv
    trials = load_trials()
    G = groups(trials)
    # ---- A. reproduction gate
    diffs, checked = [], 0
    for scope, grp, tier, fw, model, rows in G:
        fl = [flags(r) for r in rows]
        for name, (table, pre, nrule, drule) in METRICS.items():
            k = sum(f["num"][nrule] for f in fl)
            n = sum(f["den"][drule] for f in fl)
            ln, c = committed(table, grp, tier, model)
            exp = {"k": str(k), "n": str(n), "pct": g6(100 * k / n), "lo": g6(100 * wilson(k, n)[0]), "hi": g6(100 * wilson(k, n)[1])}
            for fld in ("k", "n", "pct", "lo", "hi"):
                checked += 1
                if g6(float(c[f"{pre}_{fld}"])) != exp[fld]:
                    diffs.append((f"{grp}/{tier}/{model}", name, fld, exp[fld], c[f"{pre}_{fld}"]))
    print(f"REPRODUCTION GATE: {'FAIL' if diffs else 'PASS'} ({checked} values compared over {len(G)} groups x {len(METRICS)} metrics against t1, t2 and t3; precision: 6 significant digits)")
    if diffs:
        L = ["# Reproduction failure", "", f"{len(diffs)} of {checked} values differ from the committed tables. Nothing else was produced.", "", "| group | metric | field | recomputed | committed |", "|---|---|---|---|---|"] + [f"| {' | '.join(d)} |" for d in diffs]
        print("\n".join(L))
        if write:
            create(OUT / "repro_failure.md", "\n".join(L) + "\n")
        return 1
    # ---- B/C. cluster intervals
    out = []
    for scope, grp, tier, fw, model, rows in G:
        items = sorted({r["prompt_id"] for r in rows})
        ix = {p: i for i, p in enumerate(items)}
        n_i = len(items)
        fl = [flags(r) for r in rows]
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, n_i, size=(B, n_i))
        for name, (table, pre, nrule, drule) in METRICS.items():
            num, den = np.zeros(n_i), np.zeros(n_i)
            for r, f in zip(rows, fl):
                i = ix[r["prompt_id"]]
                num[i] += f["num"][nrule]
                den[i] += f["den"][drule]
            Nn, Dd = num[idx].sum(1), den[idx].sum(1)
            ok = Dd > 0
            boot = 100 * Nn[ok] / Dd[ok]
            k, n = int(num.sum()), int(den.sum())
            lo, hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
            ln, c = committed(table, grp, tier, model)
            wlo, whi = float(c[f"{pre}_lo"]), float(c[f"{pre}_hi"])
            out.append({"metric": name, "scope": scope, "tier": tier, "model": model, "n_trials": len(rows), "n_denominator": n, "n_items": n_i, "k": k, "point_pct": 100 * k / n,
                        "wilson_lo": wlo, "wilson_hi": whi, "wilson_source": f"analysis/main_run/tables/{table} row {ln} columns {pre}_lo,{pre}_hi", "cluster_lo": lo, "cluster_hi": hi,
                        "wilson_width": whi - wlo, "cluster_width": hi - lo, "width_ratio_cluster_over_wilson": (hi - lo) / (whi - wlo), "resamples": B, "seed": SEED})
    md = render(out)
    print(md)
    if write:
        create(OUT / "cluster_intervals.csv", csvtext(out))
        create(OUT / "cluster_intervals.md", md)
    return 0


def csvtext(rows):
    import io
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=list(rows[0]))
    w.writeheader()
    for r in rows:
        w.writerow({k: (g6(v) if isinstance(v, float) else v) for k, v in r.items()})
    return b.getvalue()


def render(rows):
    L = ["# Item-cluster bootstrap intervals for the primary rates", "",
         f"Descriptive robustness check added after the analysis (deviation D15); point estimates are those of the committed tables, and the pre-registered Wilson intervals (copied from the committed tables) remain the reported intervals. "
         f"Cluster interval: the 300 items are resampled with replacement and every trial of a sampled item (all frameworks and repeats of the group) is kept; the rate is recomputed as a ratio of sums; {B:,} resamples, seed {SEED}, percentile 95% interval. "
         "ASR-type rates use decided trials (UNCERTAIN excluded) as in the committed definitions. Ratio = cluster width / Wilson width.", "",
         "| metric | scope | tier | model | trials | denominator | point % | Wilson 95% (committed) | cluster 95% | width ratio |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['metric']} | {r['scope']} | {r['tier']} | {r['model']} | {r['n_trials']} | {r['n_denominator']} | {r['point_pct']:.2f} | {r['wilson_lo']:.2f} to {r['wilson_hi']:.2f} | {r['cluster_lo']:.2f} to {r['cluster_hi']:.2f} | {r['width_ratio_cluster_over_wilson']:.2f} |")
    return "\n".join(L) + "\n"


def create(path, text):
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(text)
        print("created", path.name)
    except FileExistsError:
        print("kept existing", path.name)


if __name__ == "__main__":
    sys.exit(main())
