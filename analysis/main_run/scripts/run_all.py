"""Reproduces everything from the read-only inputs:  <ROOT>/safelabs-eval/.venv/bin/python scripts/run_all.py   (ROOT = $SAFELABS_ROOT or ~/Desktop/Workspace/AgentSafeLabs).
Reads runs/main_cheap, runs/main_frontier, runs/smoke_*, their consoles and repair_log.jsonl, safelabs-trace/handcheck/*/results. Never opens evidence/, pilot_salt.txt, .env files or credentials.
Writes only inside this analysis folder. DEVIATIONS.md is written by hand (facts and dates) and is not regenerated. The long steps read ~10,000 trace files (a few minutes)."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["s02_build_trials", "s01_integrity", "s01b_all_attempt_gaps", "s03_primary_secondary", "s05_contrasts", "s06_exploratory", "s07_humancheck_context", "s08_spend_and_incidents", "make_citable", "make_report", "make_sha"]
env = {"PYTHONDONTWRITEBYTECODE": "1", **__import__("os").environ}
for s in STEPS:
    print(f"== {s}", flush=True)
    r = subprocess.run([sys.executable, "-B", str(HERE / f"{s}.py")], cwd=HERE, env=env)
    if r.returncode:
        sys.exit(f"{s} failed")
print("done")
