"""python -m trace_runner --config configs/pilot.yaml [--estimate | --dry-run | --rerun-missing | --resume | --verify | --select-items] [--confirm-real] [--out DIR]"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

from agentport_bench.harness import format_rerun_lines
from safelabs_trace.writer import resolve_salt, salt_id

from trace_runner.config import ConfigError, RunCfg, load_config
from trace_runner.fakes import FakeProvider, fake_marker_scorer
from trace_runner.items import load_items, select_ids
from trace_runner.models_real import RealModels, missing_key_names
from trace_runner.orchestrator import Paths, Runner, verify_manifest
from trace_runner.pricing import PriceTableError, estimate, format_estimate, load_price_table, n_trials
from trace_runner.safety import StartupRefusal, enforce_startup_safety


def _price_path(cfg_path: Path, cfg: RunCfg) -> Path:
    p = Path(cfg.price_table)
    return p if p.is_absolute() or p.exists() else cfg_path.parent / p


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trace_runner", description="1B traces-on benchmark runner (digest-only traces, text-vs-action divergence)")
    ap.add_argument("--config", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--estimate", action="store_true", help="print the projected cost from the user-filled price table; calls nothing")
    g.add_argument("--rerun-missing", action="store_true", help="re-run only the missing_infrastructure rows of an earlier run")
    g.add_argument("--resume", action="store_true", help="run only trials with no result row (after a budget stop or a crash)")
    g.add_argument("--verify", action="store_true", help="check that the trace manifest, the traces and the results file agree")
    g.add_argument("--select-items", action="store_true", help="print the seeded stratified item ids for the config's items section")
    ap.add_argument("--dry-run", action="store_true", help="fake models, fake scorer, fake prices; all three frameworks; no network, no keys (combine with --rerun-missing/--resume/--verify)")
    ap.add_argument("--out", help="output folder (default: output_dir from the config; dryrun_out for --dry-run)")
    ap.add_argument("--confirm-real", action="store_true", help="required for a run that calls real models")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    cfg_path = Path(a.config)
    try:
        cfg, sha = load_config(cfg_path)
        if a.select_items:
            from safelabs.prompts import get_library

            cats: dict[str, list[str]] = {}
            for e in get_library().entries:
                cats.setdefault(e.category.value, []).append(e.id)
            print("\n".join(select_ids(cats, cfg.items.per_category, cfg.items.seed, cfg.items.categories)))
            return 0
        if a.dry_run:
            cfg = cfg.model_copy(update={"frameworks": ["langchain", "adk", "openai_agents"], "scorer": "fake_marker"})
        out = Path(a.out or ("dryrun_out" if a.dry_run else cfg.output_dir))
        paths = Paths(out)
        if a.verify:
            probs = verify_manifest(paths)
            print("manifest OK" if not probs else "\n".join(probs))
            return 0 if not probs else 1
        items = load_items(cfg.items)
        ids = [m.id for m in cfg.models]
        if a.estimate:
            table = load_price_table(_price_path(cfg_path, cfg), ids, allow_fake=a.dry_run)
            print(format_estimate(estimate(cfg, len(items), table)))
            return 0
        report = enforce_startup_safety(cfg)
        if a.dry_run:
            table = load_price_table(_price_path(cfg_path, cfg), ids, allow_fake=True)
            salt = secrets.token_bytes(32)
            source, scorer, mode = FakeProvider(cfg.fake_plan), fake_marker_scorer(), "dry_run"
        else:
            table = load_price_table(_price_path(cfg_path, cfg), ids)
            if not a.confirm_real:
                print("refusing: a real run calls real models and spends money; add --confirm-real (see report.md checklist)", file=sys.stderr)
                return 2
            miss = missing_key_names(cfg)
            if miss:
                print("refusing: environment variables not set (names only): " + ", ".join(miss), file=sys.stderr)
                return 2
            salt = resolve_salt()
            if salt is None:
                print("refusing: no trace salt; set SAFELABS_TRACE_SALT (a random secret kept outside the repo)", file=sys.stderr)
                return 2
            from safelabs.scoring.scorer import Scorer

            source, scorer, mode = RealModels(), Scorer(), "real"
        runner = Runner(cfg, sha, items, source, scorer, table, paths, salt, mode=mode, salt_id=salt_id(salt),
                        sleep=(_no_sleep if a.dry_run else None), jitter_fn=((lambda: 0.0) if a.dry_run else None))
        runner.safety = report.as_dict()
        if not (a.rerun_missing or a.resume) and paths.results.exists() and paths.results.stat().st_size:
            print(f"refusing: {paths.results} already has rows; use --resume or --rerun-missing, or choose a new --out", file=sys.stderr)
            return 2
        if a.rerun_missing:
            summary = asyncio.run(runner.rerun_missing())
            print("\n".join(format_rerun_lines(summary)))
        else:
            res = asyncio.run(runner.run(resume=True))
            print(f"ran {res['ran']} trial(s); not_run_budget {res['not_run_budget']}; spent {res['spent_usd']:.4f} ({'fake units' if table.fake else 'USD'})")
        print(f"outputs in {out}: results.jsonl, results.manifest.json, trace_manifest.json, divergence_summary.json/.md, traces/")
        return 0
    except (ConfigError, StartupRefusal, PriceTableError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2


async def _no_sleep(_s: float) -> None:
    return None
