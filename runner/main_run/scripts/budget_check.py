"""Sum the ACTUAL spend of finished or stopped runs against the total hard budget (default USD 100). Reads only each run folder's trace_manifest.json (digest-only; budget.spent_usd, stopped, unmetered_trials, trial statuses).
Usage: python3 budget_check.py [--limit 100] RUN_DIR [RUN_DIR ...]   e.g. the runs of smoke_openai_agents, main_cheap, main_frontier. Prints numbers only. Exit 1 if the total exceeds the limit."""
import argparse, json, sys, collections
from pathlib import Path
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=float, default=100.0); ap.add_argument("runs", nargs="+")
a = ap.parse_args()
tot = 0.0
for r in a.runs:
    p = Path(r).expanduser() / "trace_manifest.json"
    if not p.exists():
        print(f"{r}: no trace_manifest.json"); sys.exit(2)
    tm = json.loads(p.read_text()); b = tm["budget"]; st = collections.Counter(e["status"] for e in tm["trials"].values())
    tot += b["spent_usd"]
    print(f"{Path(r).name}: spent USD {b['spent_usd']:.4f} of cap {b['cap_usd']:.2f}; stopped for budget: {b['stopped']}; unmetered trials: {b['unmetered_trials']}; trials {dict(st)}")
print(f"TOTAL spent USD {tot:.4f} of limit {a.limit:.2f}; remaining USD {a.limit - tot:.4f}")
sys.exit(0 if tot <= a.limit else 1)
