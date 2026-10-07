"""Check the OpenAI Agents smoke gate of MAIN_RUN_PLAN.md on a finished smoke run. Prints PASS/FAIL per gate item and the overall result; counts and file names only (never evidence content).
Two modes. --gate oa (default): the five-item OpenAI Agents smoke gate below. --gate frontier: the FRONTIER SMOKE check (cost and plumbing only; its data are not part of the main-run results): the only gating items are
(2) missing_infrastructure <= 5% and (3) manifest OK; the other lines are printed as INFO and do not gate. Default --expected-trials: 60 for oa, 120 for frontier.
Usage (from safelabs-trace/runner, safelabs-eval venv python, PYTHONPATH="$PWD:$PWD/../src:$PWD/../../safelabs-eval"):
  python <path>/check_smoke_gate.py --run ../../runs/smoke_openai_agents --evidence ../../evidence/smoke_openai_agents [--expected-trials 60] [--max-missing-share 0.05]
Gate (decided before the smoke): (1) all expected trials ended scored or missing_infrastructure (none not_run_budget, none absent); (2) missing_infrastructure <= 5% of the trials; (3) manifest OK (runner's verify_manifest);
(4) the OpenAI trace exporter was off: trace_manifest.safety.openai_export_off is true and the OpenAI Agents handler was strict (the runner refuses to start otherwise; the zero-call canary is tests/test_exporter_and_canaries.py, run before the smoke);
(5) evidence written for every trial (one record per trial key, folder mode 700, file mode 600). Exit 0 only if all five pass."""
import argparse, collections, json, stat, sys
from pathlib import Path
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser()
ap.add_argument("--run", required=True); ap.add_argument("--evidence", required=True); ap.add_argument("--expected-trials", type=int); ap.add_argument("--max-missing-share", type=float, default=0.05)
ap.add_argument("--gate", choices=["oa", "frontier"], default="oa")
a = ap.parse_args()
FRONT = a.gate == "frontier"
if a.expected_trials is None:
    a.expected_trials = 120 if FRONT else 60
run, ev = Path(a.run).expanduser().resolve(), Path(a.evidence).expanduser().resolve()
from trace_runner.orchestrator import Paths, verify_manifest
res = []
def item(name, ok, detail, gating=True):
    if gating:
        res.append(ok)
        print(("PASS " if ok else "FAIL ") + name + ": " + detail)
    else:
        print(("INFO ok   " if ok else "INFO NOTE ") + name + ": " + detail)
tm = json.loads((run / "trace_manifest.json").read_text())
st = collections.Counter(e["status"] for e in tm["trials"].values())
n = sum(st.values())
item("1 every trial ended scored or missing_infrastructure", n == a.expected_trials and set(st) <= {"scored", "missing_infrastructure"}, f"{n} trials (expected {a.expected_trials}); statuses {dict(st)}", gating=not FRONT)
miss = st.get("missing_infrastructure", 0)
item(f"2 missing_infrastructure <= {100 * a.max_missing_share:.0f}%", n > 0 and miss / n <= a.max_missing_share + 1e-12, f"{miss} of {n} ({100 * miss / max(n, 1):.1f}%)")
probs = verify_manifest(Paths(run))
item("3 manifest OK", not probs, "manifest OK" if not probs else f"{len(probs)} problem(s), first: {probs[0][:120]}")
sf = tm.get("safety") or {}
item("4 OpenAI trace exporter off, strict handler", sf.get("openai_export_off") is True and sf.get("strict_handler") is True and sf.get("exporter_env_clear") is True, f"safety = {{openai_export_off: {sf.get('openai_export_off')}, strict_handler: {sf.get('strict_handler')}, exporter_env_clear: {sf.get('exporter_env_clear')}}}" + ("" if not FRONT else " (openai_export_off is null when openai_agents is not in the run)"), gating=not FRONT and True) if not FRONT else item("4 safety fields", sf.get("exporter_env_clear") is True and sf.get("strict_handler") is True, f"safety = {sf}", gating=False)
keys = {(e["framework"], e["model"], e["prompt_id"], e["seed"]) for e in tm["trials"].values()}
got = set()
lines = 0
f = ev / "evidence.jsonl"
if f.exists():
    for l in f.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l); lines += 1; got.add((r["framework"], r["model"], r["prompt_id"], r["trial_seed"]))
modes = (stat.S_IMODE(ev.stat().st_mode) == 0o700 and stat.S_IMODE(f.stat().st_mode) == 0o600) if f.exists() else False
item("5 evidence written for every trial", f.exists() and keys <= got and modes, f"{lines} line(s), {len(keys & got)} of {len(keys)} trial keys covered, folder/file modes 700/600: {modes}", gating=not FRONT)
if FRONT:
    print("FRONTIER SMOKE CHECK PASSED (cost and plumbing only)" if all(res) else "FRONTIER SMOKE CHECK FAILED (main_frontier does not start until the cause is understood; see MAIN_RUN_PLAN.md)")
else:
    print("GATE PASSED" if all(res) else "GATE FAILED")
sys.exit(0 if all(res) else 1)
