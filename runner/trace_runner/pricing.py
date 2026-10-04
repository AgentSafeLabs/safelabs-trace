"""Price table, cost estimate and budget tracking. Prices come only from a table the user fills; nothing here knows or invents a price."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from trace_runner.config import RunCfg


class PriceTableError(RuntimeError):
    """The price table is missing, unfilled or unusable; the runner refuses to estimate or to make a real run."""


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


@dataclass
class PriceTable:
    prices: dict[str, Price]
    fake: bool = False  # a table for dry runs only

    def cost(self, model: str, in_tokens: int, out_tokens: int) -> float:
        p = self.prices[model]
        return (in_tokens * p.input_per_mtok + out_tokens * p.output_per_mtok) / 1_000_000


def load_price_table(path: str | Path, model_ids: list[str], *, allow_fake: bool = False) -> PriceTable:
    p = Path(path)
    if not p.is_file():
        raise PriceTableError(f"price table {p} not found; copy price_table.yaml and fill in the prices")
    data: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
    fake = bool(data.get("fake", False))
    if fake and not allow_fake:
        raise PriceTableError("this price table is marked fake (dry run only); a real run or --estimate needs a table you filled in")
    rows = data.get("prices") or {}
    out: dict[str, Price] = {}
    bad: list[str] = []
    for m in model_ids:
        row = rows.get(m) or {}
        i, o = row.get("input_per_mtok"), row.get("output_per_mtok")
        ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in (i, o))
        if not ok:
            bad.append(m)
        else:
            out[m] = Price(float(i), float(o))
    if bad:
        raise PriceTableError("price table has no usable price (a positive number for input_per_mtok and output_per_mtok) for: " + ", ".join(bad))
    return PriceTable(out, fake)


def trial_tokens_expected(cfg: RunCfg, model_id: str) -> tuple[int, int]:
    """INFERRED expected tokens for one trial: calls_per_trial calls each carrying the schemas and the prompt; output = est_output_tokens."""
    m = next(x for x in cfg.models if x.id == model_id)
    b = cfg.budget
    return b.calls_per_trial * (b.schema_tokens + b.prompt_tokens), m.est_output_tokens


def trial_tokens_worst(cfg: RunCfg, model_id: str) -> tuple[int, int]:
    """INFERRED upper bound for one trial: max_model_calls calls, each re-sending the schemas, the prompt and every earlier output."""
    m = next(x for x in cfg.models if x.id == model_id)
    b, n = cfg.budget, cfg.max_model_calls
    per_out = m.est_output_tokens
    return n * (b.schema_tokens + b.prompt_tokens + per_out), n * per_out


def n_trials(cfg: RunCfg, n_items: int) -> int:
    return n_items * len(cfg.frameworks) * len(cfg.models) * cfg.trials


def estimate(cfg: RunCfg, n_items: int, table: PriceTable) -> dict[str, Any]:
    cells = []
    tot = {"trials": 0, "in": 0, "out": 0, "usd": 0.0, "usd_worst": 0.0}
    for fw in cfg.frameworks:
        for m in cfg.models:
            n = n_items * cfg.trials
            ti, to = trial_tokens_expected(cfg, m.id)
            wi, wo = trial_tokens_worst(cfg, m.id)
            usd, worst = n * table.cost(m.id, ti, to), n * table.cost(m.id, wi, wo)
            cells.append({"framework": fw, "model": m.id, "trials": n, "input_tokens": n * ti, "output_tokens": n * to, "usd_expected": usd, "usd_worst_case": worst})
            tot["trials"] += n
            tot["in"] += n * ti
            tot["out"] += n * to
            tot["usd"] += usd
            tot["usd_worst"] += worst
    return {"basis": "INFERRED token model from the config (budget.*, models[].est_output_tokens) and the user-filled price table",
            "price_table_fake": table.fake, "cells": cells, "total": {"trials": tot["trials"], "input_tokens": tot["in"], "output_tokens": tot["out"],
            "usd_expected": tot["usd"], "usd_worst_case": tot["usd_worst"]}, "cap_usd": cfg.budget.cap_usd,
            "expected_within_cap": tot["usd"] <= cfg.budget.cap_usd, "worst_case_within_cap": tot["usd_worst"] <= cfg.budget.cap_usd}


def format_estimate(est: dict[str, Any]) -> str:
    lines = ["Cost estimate (" + est["basis"] + ")" + ("  [DRY RUN: fake prices]" if est["price_table_fake"] else "")]
    for c in est["cells"]:
        lines.append(f"  {c['framework']:<14} {c['model']:<32} {c['trials']:>5} trials  in {c['input_tokens']:>10,}  out {c['output_tokens']:>9,}  expected {c['usd_expected']:>9.2f}  worst-case {c['usd_worst_case']:>9.2f}")
    t = est["total"]
    lines.append(f"  TOTAL {t['trials']} trials  in {t['input_tokens']:,}  out {t['output_tokens']:,}  expected USD {t['usd_expected']:.2f}  worst-case USD {t['usd_worst_case']:.2f}  (cap USD {est['cap_usd']:.2f})")
    if not est["worst_case_within_cap"]:
        lines.append("  NOTE: the worst case exceeds the cap; the run will stop cleanly before crossing it and mark the rest not_run_budget (resumable).")
    return "\n".join(lines)


class BudgetTracker:
    """Tracks actual spend from reported token usage and says when the next trial must not start.

    The check before a trial is: spent + max(INFERRED worst case for that model, the largest actual trial cost seen for it) > cap.
    A trial whose usage is not reported is charged its worst case (conservative) and counted in ``unmetered``."""

    def __init__(self, cfg: RunCfg, table: PriceTable) -> None:
        self.cfg, self.table, self.cap = cfg, table, cfg.budget.cap_usd
        self.spent = 0.0
        self.unmetered = 0
        self.max_seen: dict[str, float] = {}
        self.stopped = False

    def projected(self, model_id: str) -> float:
        wi, wo = trial_tokens_worst(self.cfg, model_id)
        return max(self.table.cost(model_id, wi, wo), self.max_seen.get(model_id, 0.0))

    def can_start(self, model_id: str) -> bool:
        return self.spent + self.projected(model_id) <= self.cap

    def record(self, model_id: str, usage: dict[str, Any] | None) -> float:
        if usage is None or usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None:
            self.unmetered += 1
            wi, wo = trial_tokens_worst(self.cfg, model_id)
            cost = self.table.cost(model_id, wi, wo)
        else:
            cost = self.table.cost(model_id, int(usage["prompt_tokens"]), int(usage["completion_tokens"]) + int(usage.get("reasoning_tokens") or 0))
        self.spent += cost
        self.max_seen[model_id] = max(self.max_seen.get(model_id, 0.0), cost)
        return cost
