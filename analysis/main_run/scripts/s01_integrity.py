"""A. Integrity: --verify (the runner's own verify_manifest), row counts, missing_infrastructure, trace integrity recomputed over the FINAL-attempt trace of every trial, smoke gate evidence."""
from common import *  # noqa
import collections

from trace_runner.orchestrator import Paths, read_rows, verify_manifest
from safelabs_trace.writer import read_trace

out = {}
trace_rows = []
for name, d in RUN_DIRS.items():
    paths = Paths(d)
    probs = verify_manifest(paths)
    rows = read_rows(paths.results)
    tm = json.loads(paths.trace_manifest.read_text())
    st = collections.Counter(r.status for r in rows)
    start_wo_end, end_wo_start, checked, no_trace = [], [], 0, 0
    for e in tm["trials"].values():
        if not e["final_trace_id"]:
            no_trace += 1
            continue
        ev = [x for x in read_trace(d / e["trace_file"]) if x.trace_id == e["final_trace_id"]]
        checked += 1
        s = {x.call_id for x in ev if x.type == "model.call.start"}
        en = {x.call_id for x in ev if x.type == "model.call.end"}
        if s - en:
            start_wo_end.append((e["trial_id"], len(s - en)))
        if en - s:
            end_wo_start.append((e["trial_id"], len(en - s)))
    out[name] = {"verify": "manifest OK" if not probs else probs, "rows": len(rows), "status": dict(st), "missing_infrastructure": st.get("missing_infrastructure", 0),
                 "not_run_budget": sum(1 for e in tm["trials"].values() if e["status"] == "not_run_budget"), "traces_checked": checked, "trials_without_trace": no_trace,
                 "start_without_end": start_wo_end, "end_without_start": end_wo_start, "config_sha256": tm["config_sha256"], "safety": tm["safety"],
                 "budget_block_last_pass_only": tm["budget"], "rerun_history": [(h["kind"], h["timestamp"], h["rows_attempted"], h["recovered"], h["still_missing"]) for h in json.loads(paths.manifest.read_text())["rerun_history"]]}
    for t, n in start_wo_end:
        trace_rows.append({"run": name, "trial": t, "model_call_start_without_end": n})
# smoke gate evidence (openai_agents smoke): the gate's items 1-4 from the smoke folder
sm = RUNS / "smoke_openai_agents"
sp = Paths(sm)
srows = read_rows(sp.results)
stm = json.loads(sp.trace_manifest.read_text())
out["smoke_openai_agents"] = {"verify": "manifest OK" if not verify_manifest(sp) else verify_manifest(sp), "rows": len(srows), "missing_infrastructure": sum(r.is_missing for r in srows),
                              "not_run_budget": sum(1 for e in stm["trials"].values() if e["status"] == "not_run_budget"), "safety": stm["safety"], "frameworks": sorted({r.framework for r in srows})}
sf = RUNS / "smoke_frontier"
fp = Paths(sf)
frows = read_rows(fp.results)
out["smoke_frontier"] = {"verify": "manifest OK" if not verify_manifest(fp) else verify_manifest(fp), "rows": len(frows), "missing_infrastructure": sum(r.is_missing for r in frows)}
(TABLES / "integrity.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
write_csv(TABLES / "integrity_trace_gaps.csv", trace_rows, ["run", "trial", "model_call_start_without_end"])
write_csv(TABLES / "integrity_summary.csv", [{"run": k, "verify": v["verify"], "rows": v["rows"], "missing_infrastructure": v["missing_infrastructure"], "not_run_budget": v.get("not_run_budget"),
                                              "traces_checked": v.get("traces_checked"), "trials_without_trace": v.get("trials_without_trace"),
                                              "start_without_end_trials": len(v.get("start_without_end", [])), "end_without_start_trials": len(v.get("end_without_start", []))} for k, v in out.items()])
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("verify", "rows", "missing_infrastructure", "traces_checked", "start_without_end", "end_without_start")} for k, v in out.items()}, indent=1, default=str))
