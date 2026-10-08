"""G. Spend and incident data. (1) Spend: every 'spent' line of the four console logs; the trace manifests' budget block (which is what budget_check.py sums: the LAST pass only); the per-trial
cost_usd in trace_manifest.json (the runner adds a rerun's cost to the trial's earlier cost, so its sum covers ALL passes). (2) Rows by pass (initial / rerun) with the error evidence of the failed
attempts. (3) The 11 haiku rows from repair_log.jsonl."""
from common import *  # noqa
import collections
import re

S = "08_spend"
cons = {n: RUNS / f"{n}_console.txt" for n in ("smoke_openai_agents", "smoke_frontier", "main_cheap", "main_frontier")}
dirs = {"smoke_openai_agents": RUNS / "smoke_openai_agents", "smoke_frontier": RUNS / "smoke_frontier", "main_cheap": RUNS / "main_cheap", "main_frontier": RUNS / "main_frontier"}
rows, tot = [], collections.Counter()
for n, d in dirs.items():
    tm = json.loads((d / "trace_manifest.json").read_text())
    mf = json.loads((d / "results.manifest.json").read_text())
    lines = [float(m.group(1)) for m in re.finditer(r"spent ([0-9.]+) \(USD\)", cons[n].read_text(errors="replace"))]
    per_trial = sum(e.get("cost_usd") or 0 for e in tm["trials"].values())
    last = tm["budget"]["spent_usd"]
    passes = [(h["kind"], h["rows_attempted"], h["recovered"], h["still_missing"]) for h in mf["rerun_history"]]
    rows.append({"run": n, "cap_usd": tm["budget"]["cap_usd"], "console_spent_lines": ";".join(f"{x:.4f}" for x in lines), "console_spent_sum": sum(lines), "budget_block_last_pass_usd": last,
                 "per_trial_cost_sum_all_passes_usd": per_trial, "derived_rerun_passes_usd": per_trial - sum(lines), "rerun_passes_recorded": len(passes) - 1, "unmetered_trials": tm["budget"]["unmetered_trials"],
                 "stopped_for_budget": tm["budget"]["stopped"]})
    tot["budget_check_style"] += last
    tot["true_all_passes"] += per_trial
    tot["console_lines_only"] += sum(lines)
rows.append({"run": "TOTAL", "cap_usd": 100.0, "console_spent_sum": tot["console_lines_only"], "budget_block_last_pass_usd": tot["budget_check_style"], "per_trial_cost_sum_all_passes_usd": tot["true_all_passes"],
             "derived_rerun_passes_usd": tot["true_all_passes"] - tot["console_lines_only"]})
write_csv(TABLES / "t16_spend.csv", rows)
cite(S, "spend.total_true", "total spend, all passes, all four runs (trial-level cost_usd sum), USD (cap 100)", None, None, tot["true_all_passes"], "tables/t16_spend.csv (runs/*/trace_manifest.json)", "price-table cost of metered final attempts, not an invoice", unit="USD")
cite(S, "spend.total_budget_check", "total as budget_check.py reports it (last pass only), USD", None, None, tot["budget_check_style"], "tables/t16_spend.csv", unit="USD")
for r in rows:
    if r["run"] != "TOTAL":
        cite(S, f"spend.{r['run']}", f"spend {r['run']} all passes, USD (cap {r['cap_usd']})", None, None, r["per_trial_cost_sum_all_passes_usd"], "tables/t16_spend.csv", unit="USD")

# rows by pass
bypass = []
for n in ("main_cheap", "main_frontier"):
    rr = [json.loads(l) for l in (dirs[n] / "results.jsonl").read_text().splitlines()]
    c = collections.Counter(x["rerun_passes"] for x in rr)
    for p, k in sorted(c.items()):
        sub = [x for x in rr if x["rerun_passes"] == p]
        err = collections.Counter(s for x in sub for s in x["attempt_errors"])
        bypass.append({"run": n, "rerun_passes": p, "rows": k, "harness_version": ",".join(sorted({x["harness_version"] for x in sub})), "library_version": ",".join(sorted({x["library_version"] for x in sub})),
                       "models": ";".join(f"{m}:{v}" for m, v in sorted(collections.Counter(x["model"] for x in sub).items())),
                       "failed_attempt_subclasses": ";".join(f"{a}:{v}" for a, v in sorted(err.items())), "rows_with_reclassified_record": sum(1 for x in sub if x.get("reclassified"))})
write_csv(TABLES / "t17_rows_by_pass.csv", bypass)
rl = [json.loads(l) for l in (dirs["main_cheap"] / "repair_log.jsonl").read_text().splitlines()]
write_csv(TABLES / "t18_repair_log_rows.csv", [{k: x[k] for k in ("framework", "model", "prompt_id", "trial_seed", "from_status", "from_verdict", "error_class", "error_subclass", "runner_version", "timestamp")} for x in rl])
# the pre-repair file: what was missing and why (error class/subclass only; the error text is not copied)
pre = [json.loads(l) for l in (dirs["main_cheap"] / "results.pre_reclassify_1.jsonl").read_text().splitlines()]
m = [x for x in pre if x["status"] == "missing_infrastructure"]
e = [x for x in pre if x["status"] == "scored" and x["error_class"]]
inc = {"pre_repair_rows": len(pre), "pre_repair_missing": len(m), "pre_repair_missing_by_cell": dict(collections.Counter(f"{x['framework']}|{x['model']}" for x in m)),
       "pre_repair_missing_error": {f"{a}/{b}/attempts={c}": v for (a, b, c), v in collections.Counter((x["error_class"], x["error_subclass"], x["attempts"]) for x in m).most_common()},
       "pre_repair_missing_signal_402": sum(1 for x in m if '"code": 402' in (x["error"] or "") or "prepayment credits are depleted" in (x["error"] or "")),
       "pre_repair_missing_timestamp_range": [min(x["timestamp"] for x in m), max(x["timestamp"] for x in m)],
       "scored_with_error": len(e), "scored_with_error_by_cell": dict(collections.Counter(f"{x['framework']}|{x['model']}" for x in e)), "scored_with_error_prompts": sorted({x["prompt_id"] for x in e}),
       "scored_with_error_contains_credit_balance": sum(1 for x in e if "credit balance is too low" in (x["error"] or "")), "scored_with_error_timestamp_range": [min(x["timestamp"] for x in e), max(x["timestamp"] for x in e)]}
(TABLES / "incidents_main_cheap.json").write_text(json.dumps(inc, indent=1), encoding="utf-8")
flush_citable(S)
print(json.dumps(inc, indent=1)); print(*rows, sep="\n"); print(*bypass, sep="\n")
