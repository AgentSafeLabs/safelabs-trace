"""Cost projection for the 1B main-run configs from the REAL per-trial token usage of the pilot_v2 run (runs/pilot_v2/results.jsonl, digest-only) times prices. Cheap prices: price_table_main.yaml (copied from
runner/price_table.yaml). Frontier models (priced in price_table_main.yaml since 2026-10-07; list prices, confirm before running): no pilot usage, so their figure is an INDICATION from the same provider's cheap model's pilot tokens as a stand-in (INFERRED) times the frontier price; the frontier smoke's real usage replaces it (scripts/frontier_projection.py). openai_agents has no pilot usage:
the mean of the model's two pilot frameworks is used (INFERRED). Reads only runs/pilot_v2/{results.jsonl,trace_manifest.json}. Writes cost_projection.md/.json into 1b_main_run/. Run with any python3 that has PyYAML
(the safelabs-eval venv)."""
import json, sys, collections
from pathlib import Path
import yaml
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
RUN = Path.home() / "Desktop/Workspace/AgentSafeLabs/runs/pilot_v2"
rows = [json.loads(l) for l in (RUN / "results.jsonl").read_text().splitlines() if l.strip()]
tm = json.loads((RUN / "trace_manifest.json").read_text())
P = yaml.safe_load((HERE / "price_table_main.yaml").read_text())["prices"]
CHEAP = ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite"]
FRONT = [("claude-opus-4-8", "claude-haiku-4-5-20251001"), ("gpt-5.5", "gpt-5.4-nano"), ("gemini-3.5-flash", "gemini-3.1-flash-lite")]
assert len(rows) == 300 and all(r["status"] == "scored" for r in rows)
use = {}
for m in CHEAP:
    for fw in ("langchain", "adk"):
        ts = [r for r in rows if r["model"] == m and r["framework"] == fw]
        i = sum(r["usage"]["prompt_tokens"] for r in ts) / len(ts); o = sum(r["usage"]["completion_tokens"] + (r["usage"].get("reasoning_tokens") or 0) for r in ts) / len(ts)
        costs = sorted((r["usage"]["prompt_tokens"] * P[m]["input_per_mtok"] + (r["usage"]["completion_tokens"] + (r["usage"].get("reasoning_tokens") or 0)) * P[m]["output_per_mtok"]) / 1e6 for r in ts)
        use[(m, fw)] = {"n": len(ts), "in": i, "out": o, "cost": (i * P[m]["input_per_mtok"] + o * P[m]["output_per_mtok"]) / 1e6, "p95": costs[int(0.95 * len(costs)) - 1], "max": costs[-1]}
for m in CHEAP:
    a, b = use[(m, "langchain")], use[(m, "adk")]
    use[(m, "openai_agents")] = {k: (a[k] + b[k]) / 2 for k in ("in", "out", "cost", "p95", "max")} | {"n": 0}
pilot_v2_spend = tm["budget"]["spent_usd"]
chk = sum(use[(m, fw)]["cost"] * 50 for m in CHEAP for fw in ("langchain", "adk"))
def cheap(items, fws, trials):
    return {m: sum(items * trials * use[(m, fw)]["cost"] for fw in fws) for m in CHEAP}
def tokens(models_proxy, items, fws, trials):
    return (sum(items * trials * use[(p, fw)]["in"] for _, p in models_proxy for fw in fws), sum(items * trials * use[(p, fw)]["out"] for _, p in models_proxy for fw in fws))
RUNS = [("smoke_openai_agents", 20, ["openai_agents"], 1, 2), ("smoke_frontier", 20, ["langchain", "adk"], 1, 8), ("main_cheap", 300, ["langchain", "adk"], 3, 30), ("main_cheap_with_oa", 300, ["langchain", "adk", "openai_agents"], 3, 30),
        ("main_frontier", 300, ["langchain", "adk"], 1, 60), ("main_frontier_with_oa", 300, ["langchain", "adk", "openai_agents"], 1, 60)]
def front_usd(items, fws, trials):
    """INDICATION: stand-in tokens (same provider's cheap model, pilot_v2) x the frontier price."""
    per = {}
    for fm, proxy in FRONT:
        per[fm] = sum(items * trials * (use[(proxy, fw)]["in"] * P[fm]["input_per_mtok"] + use[(proxy, fw)]["out"] * P[fm]["output_per_mtok"]) / 1e6 for fw in fws)
    return per
out = {"pilot_v2_spend_usd": pilot_v2_spend, "recomputed_pilot_v2_usd": chk, "per_trial": {f"{m}|{fw}": v for (m, fw), v in use.items()}, "runs": {}}
L = ["# Cost projection for the 1B main run (from pilot_v2 real per-trial usage x prices)", "",
     f"Inputs: `runs/pilot_v2/results.jsonl` (300 scored trials: prompt, completion and reasoning tokens per trial) and the prices of `price_table_main.yaml`. The pilot_v2 manifest spent **USD {pilot_v2_spend:.4f}**; usage x price recomputed over the 300 trials gives USD {chk:.4f} (check). "
     "Cheap-tier figures come from the real pilot_v2 usage (openai_agents: the mean of the model's two pilot frameworks, INFERRED). **Frontier figures are INDICATIONS only** (INFERRED): no frontier model has been run, so the tokens per trial are those of the same provider's cheap model times the frontier list price of 2026-10-07 "
     "(confirm the prices before running); a frontier model may call more tools, answer at greater length, or use reasoning tokens (charged as output), so the real cost can differ a lot. The frontier smoke (120 trials) gives the real usage; `scripts/frontier_projection.py` turns it into the main_frontier projection. "
     "All figures are projections, not limits: the limit is each config's `cap_usd`, enforced by the runner from actual usage.", "",
     "## Pilot_v2 per-trial usage (real) and cost per trial", "", "| model | framework | trials | mean prompt tokens | mean output+reasoning tokens | USD per trial | 95th percentile trial | max trial |", "|---|---|---|---|---|---|---|---|"]
for m in CHEAP:
    for fw in ("langchain", "adk", "openai_agents"):
        u = use[(m, fw)]
        L.append(f"| {m} | {fw}{' (INFERRED: mean of the two)' if fw == 'openai_agents' else ''} | {u['n'] or '-'} | {u['in']:.0f} | {u['out']:.0f} | {u['cost']:.5f} | {u['p95']:.5f} | {u['max']:.5f} |")
L += ["", "## Per run (cap = the config's hard limit)", "", "| run | trials | USD, projection | of which per model | runner `--estimate` (its own INFERRED token model; expected / worst case) | cap USD |", "|---|---|---|---|---|---|"]
est = json.loads((HERE / "validation_results.json").read_text())
for name, items, fws, trials, cap in RUNS:
    n = items * len(fws) * 3 * trials
    r = {"trials": n, "cap": cap}
    if "frontier" in name:
        c = front_usd(items, fws, trials)
        r.update(usd_indication=sum(c.values()), per_model=c)
        usd = f"**{sum(c.values()):.2f} (INDICATION, stand-in tokens x list price)**"
    else:
        c = cheap(items, fws, trials)
        r.update(usd=sum(c.values()), per_model=c)
        usd = f"{sum(c.values()):.2f}"
    per = ", ".join(f"{k.split('-')[0]} {v:.2f}" for k, v in c.items())
    e = est[name]["estimate"]
    out["runs"][name] = r
    L.append(f"| {name} | {n:,} | {usd} | {per} | {e['expected_usd']:.2f} / {e['worst_case_usd']:.2f} | {cap} |")
sm_oa, sm_f = out["runs"]["smoke_openai_agents"]["usd"], out["runs"]["smoke_frontier"]["usd_indication"]
ch, ch_oa = out["runs"]["main_cheap"]["usd"], out["runs"]["main_cheap_with_oa"]["usd"]
fr, fr_oa = out["runs"]["main_frontier"]["usd_indication"], out["runs"]["main_frontier_with_oa"]["usd_indication"]
L += ["", f"Whole series (projection; frontier = indication): without openai_agents in the main runs USD {sm_oa + sm_f + ch + fr:.2f}; with it USD {sm_oa + sm_f + ch_oa + fr_oa:.2f}; against the total hard budget of USD 100 (the four caps add to exactly USD 100).", "",
      "**Note on the runner's `--estimate`.** Its expected figures (main_cheap USD 16.94, main_cheap_with_oa 25.40, main_frontier 44.49, main_frontier_with_oa 66.74 which is **above its cap of 60**) assume 3 model calls per trial each carrying the full 1,570-token overhead and output tokens equal to the config's `est_output_tokens`; "
      "the real pilot_v2 cheap trials used far fewer prompt tokens on average, so for the cheap tier the usage-based projection is about half of the runner's expected figure. Its worst-case figures (e.g. USD 200.14 for main_frontier) are bounds under the INFERRED model, not predictions. "
      "The runner stops cleanly at the cap from actual usage whichever figure is right: trials it could not start are recorded `not_run_budget` and reported per cell (plan, section 6).", "",
      "**Caps and the total.** smoke_openai_agents 2 + smoke_frontier 8 + main_cheap 30 + main_frontier 60 = USD 100 (the same with the `_with_oa` configs). Per-run caps are hard stops; the plan sets the main_frontier cap to the smaller of 60 and (100 minus the actual spend of the earlier runs) and never raises a cap (MAIN_RUN_PLAN.md section 9).", ""]
(HERE / "cost_projection.md").write_text("\n".join(L) + "\n")
json.dump(out, open(HERE / "cost_projection.json", "w"), indent=1)
print("\n".join(L[-14:]))
