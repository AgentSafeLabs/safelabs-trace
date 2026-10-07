"""python -m trace_runner --config configs/pilot.yaml [--estimate | --dry-run | --rerun-missing | --resume | --verify | --reclassify-errors [--dry-run] | --summarize --summary-out DIR | --select-items] [--confirm-real] [--out DIR]"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

from agentport_bench.harness import format_rerun_lines
from safelabs_trace.writer import resolve_salt, salt_id

from trace_runner.config import ConfigError, RunCfg, load_config
from trace_runner.evidence import EvidenceRefusal, EvidenceWriter, check_evidence_dir
from trace_runner.fakes import FakeProvider, fake_marker_scorer
from trace_runner.items import load_items, select_ids
from trace_runner.models_real import RealModels, missing_key_names
from trace_runner.orchestrator import Paths, Runner, summarize_to, verify_manifest
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
    g.add_argument("--summarize", action="store_true", help="rebuild divergence_summary.json/.md from an existing run folder (--out or the config's output_dir) into --summary-out; calls no model, never modifies the run folder")
    g.add_argument("--reclassify-errors", action="store_true", help="REPAIR an existing run folder, offline: every row with status scored and a non-null error_class becomes missing_infrastructure "
                   "(error fields kept, a `reclassified` record added; writes repair_log.jsonl, rewrites results.jsonl, fixes both manifests so --verify passes). Refuses while a run may still be writing the folder. "
                   "With --dry-run it only prints the rows it would change and writes nothing.")
    g.add_argument("--select-items", action="store_true", help="print the seeded stratified item ids for the config's items section")
    ap.add_argument("--dry-run", action="store_true", help="fake models, fake scorer, fake prices; all three frameworks; no network, no keys (combine with --rerun-missing/--resume/--verify)")
    ap.add_argument("--min-idle-seconds", type=float, default=600.0, help="--reclassify-errors: refuse a real repair if results.jsonl changed less than this many seconds ago (default 600)")
    ap.add_argument("--reclassify-classes", default="other,infrastructure", help="--reclassify-errors: the error_class values to act on (default other,infrastructure; content_policy and no_output_text stay scored "
                    "by the study's convention, add them here only on purpose)")
    ap.add_argument("--out", help="output folder (default: output_dir from the config; dryrun_out for --dry-run)")
    ap.add_argument("--summary-out", help="--summarize only: the folder to write the rebuilt summary into (must be outside the run folder)")
    ap.add_argument("--evidence-dir", help="LOCAL-ONLY evidence sidecar (decision D10): write evidence.jsonl (final answer text, raw tool arguments, stub results) into this folder; refused inside any git working tree "
                    "or the run's output folder; folder mode 700, file mode 600; key-like strings redacted. Public outputs stay digest-only.")
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
        if a.dry_run and not a.reclassify_errors:
            cfg = cfg.model_copy(update={"frameworks": ["langchain", "adk", "openai_agents"], "scorer": "fake_marker"})
        out = Path(a.out or ("dryrun_out" if a.dry_run and not a.reclassify_errors else cfg.output_dir))
        paths = Paths(out)
        if a.evidence_dir and (a.estimate or a.verify or a.summarize or a.select_items):
            print("refusing: --evidence-dir applies to a run (not to --estimate, --verify, --summarize or --select-items)", file=sys.stderr)
            return 2
        if a.reclassify_errors:
            from trace_runner import __version__ as runner_version
            from trace_runner.repair import RepairRefusal, reclassify_errors

            classes = tuple(x.strip() for x in a.reclassify_classes.split(",") if x.strip())
            if not set(classes) <= {"infrastructure", "content_policy", "no_output_text", "other"}:
                print("refusing: --reclassify-classes takes error_class names (infrastructure, content_policy, no_output_text, other)", file=sys.stderr)
                return 2
            if a.evidence_dir:
                print("refusing: --evidence-dir does not apply to --reclassify-errors (it never touches traces or evidence)", file=sys.stderr)
                return 2
            try:
                print("\n".join(reclassify_errors(out, runner_version, dry_run=a.dry_run, min_idle_s=a.min_idle_seconds, classes=classes)))
            except (RepairRefusal, FileNotFoundError, ValueError) as exc:
                print(f"refusing: {exc}", file=sys.stderr)
                return 2
            return 0
        if a.verify:
            probs = verify_manifest(paths)
            print("manifest OK" if not probs else "\n".join(probs))
            return 0 if not probs else 1
        if a.summarize:
            if not a.summary_out:
                print("refusing: --summarize needs --summary-out DIR (the run folder is never modified)", file=sys.stderr)
                return 2
            try:
                summarize_to(paths, Path(a.summary_out))
            except (ValueError, FileNotFoundError) as exc:
                print(f"refusing: {exc}", file=sys.stderr)
                return 2
            print(f"summary rebuilt from {out} into {a.summary_out}: divergence_summary.json, divergence_summary.md")
            return 0
        items = load_items(cfg.items)
        ids = [m.id for m in cfg.models]
        if a.estimate:
            table = load_price_table(_price_path(cfg_path, cfg), ids, allow_fake=a.dry_run)
            print(format_estimate(estimate(cfg, len(items), table)))
            return 0
        report = enforce_startup_safety(cfg)
        if a.evidence_dir:
            check_evidence_dir(a.evidence_dir, out)  # refuses before anything is created or any model is called
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
        evidence = EvidenceWriter(a.evidence_dir, out, salt) if a.evidence_dir else None
        runner = Runner(cfg, sha, items, source, scorer, table, paths, salt, mode=mode, salt_id=salt_id(salt),
                        sleep=(_no_sleep if a.dry_run else None), jitter_fn=((lambda: 0.0) if a.dry_run else None), evidence=evidence)
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
        if evidence is not None:
            print(f"local-only evidence: {evidence.lines} line(s) in {evidence.file} (never commit, never upload)")
        return 0
    except (ConfigError, StartupRefusal, PriceTableError, EvidenceRefusal) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2


async def _no_sleep(_s: float) -> None:
    return None
