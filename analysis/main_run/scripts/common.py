"""Shared helpers for the 1B main-run analysis. Everything here READS the run folders (digest-only) and the repos; nothing is written outside this analysis folder.

Run every script with the safelabs-eval virtualenv Python (the same one that runs the runner):  <ROOT>/safelabs-eval/.venv/bin/python scripts/run_all.py
ROOT = $SAFELABS_ROOT or ~/Desktop/Workspace/AgentSafeLabs. The runner modules are imported (not changed) to reuse the exact definitions behind divergence_summary.json.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(os.environ.get("SAFELABS_ROOT", Path.home() / "Desktop/Workspace/AgentSafeLabs"))
RUNS = ROOT / "runs"
REPO = ROOT / "safelabs-trace"
for p in (REPO / "runner", REPO / "src", ROOT / "safelabs-eval"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
TABLES = OUT / "tables"
TABLES.mkdir(exist_ok=True)

RUN_DIRS = {"main_cheap": RUNS / "main_cheap", "main_frontier": RUNS / "main_frontier"}
TIER_OF_RUN = {"main_cheap": "cheap", "main_frontier": "frontier"}
CHEAP = ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite"]
FRONTIER = ["claude-opus-4-8", "gpt-5.5", "gemini-3.5-flash"]
MODELS = {"cheap": CHEAP, "frontier": FRONTIER}
FRAMEWORKS = {"cheap": ["langchain", "adk", "openai_agents"], "frontier": ["langchain", "adk"]}
SEED = 20261007  # the plan's seed for permutation and bootstrap
N_PERM = 100_000
N_BOOT = 10_000

TRIAL_CSV = TABLES / "trial_level.csv"


def wilson(k: int, n: int) -> tuple[float, float] | None:
    from safelabs_trace.divergence import wilson as w
    return w(k, n)


def rate_cells(k: int, n: int) -> dict[str, Any]:
    ci = wilson(k, n)
    return {"k": k, "n": n, "pct": (100 * k / n) if n else None, "ci_lo": (100 * ci[0]) if ci else None, "ci_hi": (100 * ci[1]) if ci else None}


def fmt(k: int, n: int) -> str:
    r = rate_cells(k, n)
    return "n/a (0)" if not n else f"{r['pct']:.1f}% ({k}/{n}; 95% CI {r['ci_lo']:.1f} to {r['ci_hi']:.1f})"


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    fields = fields or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else (f"{r[k]:.6g}" if isinstance(r[k], float) else r[k])) for k in fields})


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_trials() -> list[dict[str, Any]]:
    """The trial-level table built by s02_build_trials.py, with numbers parsed."""
    ints = {"trial_seed", "tool_call_only", "risky", "risky_excl", "irr", "irr_excl", "known", "risky_n", "risky_unclass_n", "irr_n", "irr_unclass_n", "attempts", "rerun_passes",
            "start_wo_end", "end_wo_start", "reclassified"}
    out = []
    for r in read_csv(TRIAL_CSV):
        for k in ints:
            r[k] = int(r[k])
        r["cost_usd"] = float(r["cost_usd"] or 0)
        out.append(r)
    return out


CITABLE: list[dict[str, Any]] = []


def cite(script: str, ident: str, label: str, k: int | None, n: int | None, value: float | None, source: str, extra: str = "", unit: str = "%") -> None:
    """Register a citable number: written to tables/citable_<script>.json and collected by make_citable.py."""
    ci = wilson(k, n) if (k is not None and n) else None
    CITABLE.append({"id": ident, "label": label, "value": value if value is not None else ((100 * k / n) if (k is not None and n) else None), "unit": unit, "k": k, "n": n,
                    "ci95": [round(100 * ci[0], 2), round(100 * ci[1], 2)] if ci else None, "source": source, "command": f"python scripts/{script}.py", "note": extra})


def flush_citable(script: str) -> None:
    (TABLES / f"citable_{script}.json").write_text(json.dumps(CITABLE, indent=1), encoding="utf-8")
