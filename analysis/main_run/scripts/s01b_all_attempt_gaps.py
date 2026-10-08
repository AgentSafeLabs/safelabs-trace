"""A (cont.). The console of main_cheap (first pass, before the repair and the rerun) reported 3 model.call.start without an end among the final-attempt traces. This scans EVERY attempt's trace
(every trace_id in every trace file) of both runs, lists the attempts with a start without an end, and says whether that attempt is still the trial's final attempt now."""
from common import *  # noqa
import collections

from safelabs_trace.writer import read_trace

rows = []
for name, d in RUN_DIRS.items():
    tm = json.loads((d / "trace_manifest.json").read_text())
    for tid, e in tm["trials"].items():
        if not e["trace_file"]:
            continue
        by = collections.defaultdict(lambda: {"s": set(), "e": set(), "attempt": None})
        for ev in read_trace(d / e["trace_file"]):
            b = by[ev.trace_id]
            if ev.type == "model.call.start":
                b["s"].add(ev.call_id)
            elif ev.type == "model.call.end":
                b["e"].add(ev.call_id)
            elif ev.type == "session.start" and getattr(ev, "trial", None):
                b["attempt"] = int(ev.trial.get("attempt", 0))
        for trace_id, b in by.items():
            if b["s"] - b["e"] or b["e"] - b["s"]:
                rows.append({"run": name, "trial": tid, "attempt": b["attempt"], "attempts_in_file": len(by), "start_without_end": len(b["s"] - b["e"]), "end_without_start": len(b["e"] - b["s"]),
                             "is_final_attempt_now": int(trace_id == e["final_trace_id"]), "trial_rerun_passes": None})
write_csv(TABLES / "integrity_trace_gaps_all_attempts.csv", rows, ["run", "trial", "attempt", "attempts_in_file", "start_without_end", "end_without_start", "is_final_attempt_now", "trial_rerun_passes"])
print(len(rows), "attempt traces with a call-pairing gap")
for r in rows:
    print(r)
