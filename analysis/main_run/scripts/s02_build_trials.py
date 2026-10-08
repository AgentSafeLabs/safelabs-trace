"""Builds tables/trial_level.csv: one digest-only line per trial (no text, no arguments) from results.jsonl + trace_manifest.json + the final-attempt trace of each trial, using the runner's own
definitions (action_verdict, risky_call_counts, text_verdict). Then cross-checks the cell counts against each run folder's own divergence_summary.json (read only)."""
from common import *  # noqa

from safelabs_trace.divergence import action_verdict, text_verdict
from safelabs_trace.writer import read_trace
from trace_runner.orchestrator import Paths, read_rows, risky_call_counts

rows_out = []
for name, d in RUN_DIRS.items():
    paths = Paths(d)
    tm = json.loads(paths.trace_manifest.read_text())
    rows = {(r.model, r.framework, r.prompt_id, r.trial_seed): r for r in read_rows(paths.results)}
    for e in tm["trials"].values():
        r = rows[(e["model"], e["framework"], e["prompt_id"], e["seed"])]
        events = []
        if e["final_trace_id"]:
            events = [ev for ev in read_trace(d / e["trace_file"]) if ev.trace_id == e["final_trace_id"]]
        av = action_verdict(events) if events else None
        action = av.level if av else "unknown"
        c = risky_call_counts(events) if events else {"risky_n": 0, "risky_unclass_n": 0, "irr_n": 0, "irr_unclass_n": 0}
        starts = {ev.call_id for ev in events if ev.type == "model.call.start"}
        ends = {ev.call_id for ev in events if ev.type == "model.call.end"}
        known = action in ("none", "read", "state", "irreversible")
        risky = action in ("state", "irreversible")
        only_un = c["risky_n"] > 0 and c["risky_unclass_n"] == c["risky_n"]
        irr = action == "irreversible"
        only_un_irr = c["irr_n"] > 0 and c["irr_unclass_n"] == c["irr_n"]
        rows_out.append({
            "run": name, "tier": TIER_OF_RUN[name], "framework": r.framework, "model": r.model, "category": r.category, "prompt_id": r.prompt_id, "trial_seed": r.trial_seed,
            "status": r.status, "verdict": str(getattr(r.verdict, "value", r.verdict) or "").lower(), "text": text_verdict(r.verdict) or "", "tool_call_only": int(bool(r.tool_call_only)),
            "action": action, "stop_status": e.get("stop_status") or "", "known": int(known), "risky": int(risky), "risky_excl": int(risky and not only_un), "irr": int(irr), "irr_excl": int(irr and not only_un_irr),
            "risky_n": c["risky_n"], "risky_unclass_n": c["risky_unclass_n"], "irr_n": c["irr_n"], "irr_unclass_n": c["irr_unclass_n"],
            "error_class": r.error_class or "", "attempts": r.attempts or 1, "rerun_passes": r.rerun_passes, "reclassified": int(getattr(r, "reclassified", None) is not None),
            "final_text_len": e.get("final_text_len") if e.get("final_text_len") is not None else "", "cost_usd": e.get("cost_usd") or 0,
            "start_wo_end": len(starts - ends), "end_wo_start": len(ends - starts)})
write_csv(TRIAL_CSV, rows_out)
print(len(rows_out), "trial lines written to", TRIAL_CSV)

# cross-check against the runs' own divergence_summary.json (extended.by_cell): n scored, risky (incl.), excluding-as-not-risky, uncertain
from collections import defaultdict
agg = defaultdict(lambda: defaultdict(int))
for r in rows_out:
    k = f"{r['framework']}|{r['model']}"
    a = agg[(r["run"], k)]
    a["n"] += 1
    a["known"] += r["known"]
    a["risky"] += r["risky"]
    a["risky_excl"] += r["risky_excl"]
    a["uncertain"] += r["verdict"] == "uncertain"
    a["irr"] += r["irr"]
bad = 0
for name, d in RUN_DIRS.items():
    s = json.loads((d / "divergence_summary.json").read_text())
    for cell, t in s["extended"]["by_cell"].items():
        a = agg[(name, cell)]
        u = t["unclassified_shell"]
        ok = (t["n_scored"] == a["n"] and t["n_known_action"] == a["known"] and u["risky_trials"] == a["risky"] and u["risky_action_rate"]["excluding_as_not_risky"]["k"] == a["risky_excl"]
              and t["verdict_coverage"]["uncertain"] == a["uncertain"] and u["irreversible_trials"] == a["irr"])
        bad += not ok
        if not ok:
            print("MISMATCH", name, cell, t["n_scored"], a["n"])
print("cross-check against the run folders' divergence_summary.json:", "all cells agree" if not bad else f"{bad} cells DISAGREE")
