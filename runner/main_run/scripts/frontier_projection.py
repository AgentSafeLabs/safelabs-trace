"""Project the main_frontier cost from the REAL per-trial usage of the frontier smoke (smoke_frontier run: 120 trials = 20 items x langchain+adk x 3 frontier models x 1 trial). Reads only that run folder's results.jsonl
(digest-only: token counts per trial, no text) and price_table_main.yaml. Prints numbers and the plan's decision; writes nothing unless --write PATH is given (a new file; refuses to overwrite).
Usage: python3 frontier_projection.py --run ~/Desktop/Workspace/AgentSafeLabs/runs/smoke_frontier [--cap 60] [--spent-before 0] [--items 300] [--trials 1] [--prices price_table_main.yaml] [--write FILE]
  --cap: the cap you intend for main_frontier (the plan: the smaller of 60 and 100 minus the actual spend of the earlier runs; pass --spent-before with that spend and the cap is computed for you if --cap is not given).
Needs PyYAML (the safelabs-eval venv python). Method: per (model, framework) the mean cost per trial = (prompt tokens x input price + (completion + reasoning tokens) x output price) / 1e6 over that cell's scored smoke trials;
projection = items x trials x mean, summed. openai_agents (no frontier smoke data for it): the mean of the model's langchain and adk cells (INFERRED). A 95th-percentile figure (every trial at that cell's p95 cost) is printed as headroom, not used in the decision.
Decision (MAIN_RUN_PLAN.md section 3b): if main_frontier_with_oa projects above the cap, main_frontier runs with langchain+adk only; if langchain+adk alone projects above the cap, the plan does not decide: Waqar records a dated addendum before the run; the cap is never raised."""
import argparse, json, sys
from pathlib import Path
import yaml
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--run", required=True); ap.add_argument("--cap", type=float); ap.add_argument("--spent-before", type=float, default=0.0); ap.add_argument("--items", type=int, default=300)
ap.add_argument("--trials", type=int, default=1); ap.add_argument("--prices", default=str(HERE / "price_table_main.yaml")); ap.add_argument("--write")
a = ap.parse_args()
FRONT = ["claude-opus-4-8", "gpt-5.5", "gemini-3.5-flash"]
P = yaml.safe_load(Path(a.prices).read_text())["prices"]
for m in FRONT:
    if not all(isinstance(P[m][k], (int, float)) and P[m][k] > 0 for k in ("input_per_mtok", "output_per_mtok")):
        sys.exit(f"price missing for {m} in {a.prices}")
cap = a.cap if a.cap is not None else min(60.0, 100.0 - a.spent_before)
rows = [json.loads(l) for l in (Path(a.run).expanduser() / "results.jsonl").read_text().splitlines() if l.strip()]
cost = {}
for r in rows:
    if r.get("status") != "scored" or r["model"] not in FRONT or r["framework"] not in ("langchain", "adk") or not r.get("usage"):
        continue
    u, p = r["usage"], P[r["model"]]
    c = (u["prompt_tokens"] * p["input_per_mtok"] + (u["completion_tokens"] + (u.get("reasoning_tokens") or 0)) * p["output_per_mtok"]) / 1e6
    cost.setdefault((r["model"], r["framework"]), []).append(c)
missing = [(m, f) for m in FRONT for f in ("langchain", "adk") if not cost.get((m, f))]
if missing:
    sys.exit(f"no scored smoke trials with usage for: {missing}")
cell = {}
for (m, f), cs in cost.items():
    cs = sorted(cs)
    cell[(m, f)] = {"n": len(cs), "mean": sum(cs) / len(cs), "p95": cs[max(0, int(0.95 * len(cs)) - 1)], "max": cs[-1], "min": cs[0]}
for m in FRONT:
    cell[(m, "openai_agents")] = {k: (cell[(m, "langchain")][k] + cell[(m, "adk")][k]) / 2 for k in ("mean", "p95", "max", "min")} | {"n": 0}
def proj(fws, key="mean"):
    return {m: sum(a.items * a.trials * cell[(m, f)][key] for f in fws) for m in FRONT}
la, oa = proj(["langchain", "adk"]), proj(["langchain", "adk", "openai_agents"])
la95, oa95 = proj(["langchain", "adk"], "p95"), proj(["langchain", "adk", "openai_agents"], "p95")
L = [f"Frontier smoke: {sum(c['n'] for c in cell.values())} scored trials with usage (langchain+adk). Real cost per trial, USD (price table {Path(a.prices).name}):", ""]
for m in FRONT:
    for f in ("langchain", "adk", "openai_agents"):
        c = cell[(m, f)]
        L.append(f"  {m:<18} {f:<14} n={c['n'] or '-':<3} mean {c['mean']:.5f}  p95 {c['p95']:.5f}  max {c['max']:.5f}" + ("   (INFERRED: mean of langchain and adk)" if f == "openai_agents" else ""))
L += ["", f"Projection for {a.items} items x {a.trials} trial(s) per cell, cap USD {cap:.2f} (spent before: USD {a.spent_before:.2f}):",
      f"  main_frontier (langchain+adk, {a.items * a.trials * 2 * 3:,} trials):                 USD {sum(la.values()):.2f}   (p95 headroom USD {sum(la95.values()):.2f})   per model " + ", ".join(f"{m} {v:.2f}" for m, v in la.items()),
      f"  main_frontier_with_oa (+openai_agents, {a.items * a.trials * 3 * 3:,} trials): USD {sum(oa.values()):.2f}   (p95 headroom USD {sum(oa95.values()):.2f})   per model " + ", ".join(f"{m} {v:.2f}" for m, v in oa.items()), ""]
if sum(la.values()) > cap:
    d = f"DECISION: even langchain+adk projects above the cap (USD {sum(la.values()):.2f} > {cap:.2f}). The plan does not decide this: record a dated addendum before running; the cap is never raised."
elif sum(oa.values()) > cap:
    d = f"DECISION: with openai_agents the projection (USD {sum(oa.values()):.2f}) is above the cap (USD {cap:.2f}); langchain+adk alone (USD {sum(la.values()):.2f}) fits: run main_frontier.yaml (langchain+adk only) and say so in the report."
else:
    d = f"DECISION: the projection fits the cap (langchain+adk USD {sum(la.values()):.2f}; with openai_agents USD {sum(oa.values()):.2f}; cap USD {cap:.2f}): run main_frontier_with_oa.yaml if the OpenAI Agents smoke gate passed, else main_frontier.yaml."
L.append(d)
print("\n".join(L))
if a.write:
    pth = Path(a.write)
    with open(pth, "x", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
