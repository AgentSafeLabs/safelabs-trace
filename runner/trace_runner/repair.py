"""``--reclassify-errors``: repair an existing run folder whose rows were scored although the final attempt ended in an error (the main_cheap billing incident, 2026-10-07).

Offline: no model is called, no trace is read or written, no evidence file is touched. A row with status "scored" and a non-null error_class (by default error_class other or infrastructure,
see errors.RECLASSIFY_CLASSES) becomes status "missing_infrastructure" with its verdict, confidence, weight, indicators and usage cleared (as the harness writes a missing row), its error fields and
payload_hash kept, and a ``reclassified`` record {from_status, from_verdict, reason, timestamp, runner_version}. Every other line of results.jsonl is kept byte for byte.

A real repair also: writes repair_log.jsonl (one line per changed row), keeps the old file as results.pre_reclassify_<n>.jsonl, rewrites results.jsonl atomically, updates the changed trial entries and
results_sha256 in trace_manifest.json (so ``--verify`` passes; the traces are not touched), recomputes the counts in results.manifest.json, and records the repair in trace_manifest.json
("reclassify_history"). It refuses to start while a run may still be writing the folder: the run marker ``.run_in_progress`` exists (the runner writes it for the whole of a run / rerun), or
the manifests are missing (the older runner writes them only at the end of a run), or results.jsonl changed less than ``--min-idle-seconds`` ago (default 600).
``--dry-run`` only prints the rows it would change and needs only results.jsonl.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentport_bench.harness import MISSING_EXCLUDED_NOTE, RunManifest, _replace_file_atomically, summarize_rows, write_manifest

from trace_runner.errors import RECLASSIFY_CLASSES, reclassify_reason, to_missing_fields

RUN_MARKER = ".run_in_progress"
DEFAULT_MIN_IDLE_S = 600.0


class RepairRefusal(Exception):
    pass


def mark_running(out: Path, what: str) -> None:
    """Called by the runner at the start of a run / rerun: a repair refuses while this file exists."""
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / RUN_MARKER).write_text(json.dumps({"pid": os.getpid(), "what": what, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n", encoding="utf-8")


def clear_running(out: Path) -> None:
    try:
        (Path(out) / RUN_MARKER).unlink()
    except FileNotFoundError:
        pass


@dataclass
class Change:
    index: int
    key: tuple[str, str, str, int]
    error_subclass: str | None
    error_class: str | None
    from_verdict: str | None
    reason: str
    new_line: str


def _verdict(v: Any) -> str | None:
    return None if v is None else str(getattr(v, "value", v))


def plan_changes(results: Path, runner_version: str, classes: tuple[str, ...] = RECLASSIFY_CLASSES, stamp: str | None = None) -> tuple[list[str], list[Change]]:
    from trace_runner.orchestrator import RunnerRow, now

    stamp = stamp or now()
    lines = results.read_text(encoding="utf-8").splitlines(keepends=True)
    changes: list[Change] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        row = RunnerRow(**json.loads(line))
        reason = reclassify_reason(row, classes)
        if reason is None:
            continue
        d = to_missing_fields(row)
        d["reclassified"] = {"from_status": row.status or "scored", "from_verdict": _verdict(row.verdict), "reason": reason, "timestamp": stamp, "runner_version": runner_version}
        new = RunnerRow(**d)
        changes.append(Change(i, (row.model, row.framework, row.prompt_id, row.trial_seed), row.error_subclass, row.error_class, _verdict(row.verdict), reason,
                              new.model_dump_json() + ("\n" if line.endswith("\n") else "")))
    return lines, changes


def format_changes(changes: list[Change]) -> list[str]:
    out = [f"{len(changes)} row(s) would be changed (scored with an error_class -> missing_infrastructure)"]
    for c in changes:
        m, fw, pid, seed = c.key
        out.append(f"  framework={fw} model={m} prompt_id={pid} trial_seed={seed} error_subclass={c.error_subclass}")
    return out


def _next_free(path: Path) -> Path:
    n = 1
    while True:
        p = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not p.exists():
            return p
        n += 1


def check_idle(out: Path, min_idle_s: float, *, now_ts: float | None = None) -> None:
    out = Path(out)
    if (out / RUN_MARKER).exists():
        raise RepairRefusal(f"{out / RUN_MARKER} exists: a run may still be writing this folder (if no run is active, the marker is stale: check, then remove it yourself)")
    for need in ("results.manifest.json", "trace_manifest.json"):
        if not (out / need).exists():
            raise RepairRefusal(f"{out / need} does not exist: the run has not finished (the manifests are written at its end)")
    age = (now_ts or time.time()) - (out / "results.jsonl").stat().st_mtime
    if age < min_idle_s:
        raise RepairRefusal(f"results.jsonl changed {age:.0f} s ago (< --min-idle-seconds {min_idle_s:.0f}): a run may still be writing this folder")


def reclassify_errors(out: Path, runner_version: str, *, dry_run: bool, min_idle_s: float = DEFAULT_MIN_IDLE_S, classes: tuple[str, ...] = RECLASSIFY_CLASSES,
                      now_ts: float | None = None) -> list[str]:
    """Returns the lines to print. Raises RepairRefusal."""
    from trace_runner.orchestrator import Paths, read_rows, sha256_file, write_json_atomic, now
    from trace_runner.agents import STOP_ERROR

    paths = Paths(Path(out))
    if not paths.results.exists():
        raise RepairRefusal(f"{paths.results} does not exist")
    if dry_run:
        _lines, changes = plan_changes(paths.results, runner_version, classes)
        return format_changes(changes) + ["dry run: nothing was changed"]
    check_idle(paths.out, min_idle_s, now_ts=now_ts)
    stamp = now()
    lines, changes = plan_changes(paths.results, runner_version, classes, stamp)
    if not changes:
        return ["0 row(s) to change; nothing written"]
    tm = json.loads(paths.trace_manifest.read_text(encoding="utf-8"))
    by_key = {(e["result_key"]["model"], e["result_key"]["framework"], e["result_key"]["prompt_id"], e["result_key"]["trial_seed"]): e for e in tm["trials"].values()}
    unknown = [c.key for c in changes if c.key not in by_key]
    if unknown:
        raise RepairRefusal(f"{len(unknown)} row(s) to change have no trace manifest entry (first: {unknown[0]}); nothing written")
    backup = _next_free(paths.out / "results.pre_reclassify.jsonl")
    backup.write_text("".join(lines), encoding="utf-8")
    with (paths.out / "repair_log.jsonl").open("a", encoding="utf-8") as f:
        for c in changes:
            m, fw, pid, seed = c.key
            f.write(json.dumps({"framework": fw, "model": m, "prompt_id": pid, "trial_seed": seed, "from_status": "scored", "from_verdict": c.from_verdict, "error_class": c.error_class,
                                "error_subclass": c.error_subclass, "reason": c.reason, "timestamp": stamp, "runner_version": runner_version}, sort_keys=True) + "\n")
    for c in changes:
        lines[c.index] = c.new_line
    _replace_file_atomically(paths.results, "".join(lines))
    for c in changes:
        e = by_key[c.key]
        e.update(status="missing_infrastructure", verdict=None, final_text_len=None, stop_status=STOP_ERROR)
    tm.setdefault("reclassify_history", []).append({"timestamp": stamp, "runner_version": runner_version, "rows": len(changes), "backup": backup.name})
    tm.update(updated=stamp, results_sha256=sha256_file(paths.results))
    write_json_atomic(paths.trace_manifest, tm)
    rows = read_rows(paths.results)
    s = summarize_rows(rows)
    old = RunManifest.model_validate_json(paths.manifest.read_text(encoding="utf-8"))
    write_manifest(paths.results, old.model_copy(update={
        "scored_trials": s.scored, "missing_infrastructure": s.missing_infrastructure, "missing_by_cell": s.missing_by_cell, "retries": s.retries,
        "tool_call_only": s.tool_call_only, "missing_trials_excluded": MISSING_EXCLUDED_NOTE, "rerun_passes": max((r.rerun_passes for r in rows), default=0)}))
    return [f"{len(changes)} row(s) changed to missing_infrastructure; repair_log.jsonl written; old results kept as {backup.name}",
            "next: --verify, then --rerun-missing (see report.md)"]
