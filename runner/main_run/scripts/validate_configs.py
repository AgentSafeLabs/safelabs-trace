"""Offline validation of the 1B main-run configs with the runner's own code. Run from 1b_main_run/ (so `price_table: price_table_main.yaml` resolves, as it does from runner/ in the repo), with
the safelabs-eval venv python and PYTHONPATH=<repo>/safelabs-trace/runner:<repo>/safelabs-trace/src:<repo>/safelabs-eval.
For every config: (1) load_config + load_items (the ids are checked against the seeded selection) and the trial count; (2) --estimate (every config is priced since 2026-10-07 and must give a figure; a config with a null price would be
REFUSED with 'no usable price'); (3) a --dry-run on a temporary copy under /tmp/safelabs-trace-tests/ (items cut to per_category 1, one trial, a fake price table; the dry run forces the three frameworks,
fake models and the fake scorer) followed by --verify. Writes validation_results.json and validation_results.md into 1b_main_run/."""
import contextlib, io, json, re, sys
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent.parent
TMP = Path("/tmp/safelabs-trace-tests"); TMP.mkdir(exist_ok=True)
from trace_runner.cli import main as runner_main
from trace_runner.config import load_config
from trace_runner.items import load_items
from trace_runner.pricing import n_trials

CFGS = ["smoke_openai_agents", "smoke_frontier", "main_cheap", "main_cheap_with_oa", "main_frontier", "main_frontier_with_oa"]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = runner_main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


res = {}
for name in CFGS:
    p = HERE / "configs" / f"{name}.yaml"
    cfg, sha = load_config(p)
    items = load_items(cfg.items)
    r = {"config_sha256": sha, "items": len(items), "frameworks": cfg.frameworks, "models": [m.id for m in cfg.models], "trials": cfg.trials, "max_model_calls": cfg.max_model_calls, "cap_usd": cfg.budget.cap_usd,
         "output_dir": cfg.output_dir, "run_name": cfg.run_name, "retry_profile": cfg.retry_profile, "n_trials": n_trials(cfg, len(items)), "verified_flags": [m.verified for m in cfg.models], "tiers": sorted({m.tier for m in cfg.models})}
    rc, out, err = run(["--config", str(p), "--estimate"])
    r["estimate_rc"] = rc
    if rc == 0:
        m = re.search(r"TOTAL (\d+) trials .*expected USD ([\d.]+)\s+worst-case USD ([\d.]+)\s+\(cap USD ([\d.]+)\)", out)
        r["estimate"] = {"trials": int(m.group(1)), "expected_usd": float(m.group(2)), "worst_case_usd": float(m.group(3)), "cap_usd": float(m.group(4))}
        assert r["estimate"]["trials"] == r["n_trials"]
    else:
        r["estimate_refusal"] = err.strip().splitlines()[-1][:300]
    # dry run on a temporary copy (items cut down; the runner forces the three frameworks and fake models)
    from trace_runner.items import select_ids
    from safelabs.prompts import get_library
    cats = {}
    for e in get_library().entries:
        cats.setdefault(e.category.value, []).append(e.id)
    ids1 = select_ids(cats, 1, cfg.items.seed)
    ft = TMP / f"fake_prices_r2_{name}.yaml"
    ft.write_text("fake: true\nprices:\n" + "".join(f"  {m.id}: {{input_per_mtok: 1.0, output_per_mtok: 2.0}}\n" for m in cfg.models))
    text = p.read_text()
    text = re.sub(r"per_category: \d+", "per_category: 1", text, count=1)
    text = re.sub(r"  ids:\n(?:    - .*\n)+", "  ids:\n" + "".join(f"    - {i}\n" for i in ids1), text, count=1)
    text = re.sub(r"^trials: \d+", "trials: 1", text, flags=re.M)
    text = re.sub(r"^price_table: .*$", f"price_table: {ft}", text, flags=re.M)
    tmpcfg = TMP / f"main_run_validate_r2_{name}.yaml"
    tmpcfg.write_text(text)
    outdir = TMP / f"main_run_validate_out_r2_{name}"
    ev = TMP / f"main_run_validate_ev_r2_{name}"
    rc1, o1, e1 = run(["--config", str(tmpcfg), "--dry-run", "--out", str(outdir), "--evidence-dir", str(ev)])
    rc2, o2, e2 = run(["--config", str(tmpcfg), "--dry-run", "--out", str(outdir), "--verify"])
    ran = re.search(r"ran (\d+) trial", o1)
    r["dry_run"] = {"rc": rc1, "trials_run": int(ran.group(1)) if ran else None, "verify_rc": rc2, "verify": o2.strip(), "evidence_lines": sum(1 for _ in open(ev / "evidence.jsonl")) if (ev / "evidence.jsonl").exists() else None,
                    "note": "temporary copy: per_category 1 (10 items), 1 trial, fake prices, the runner forces 3 frameworks, fake models"}
    res[name] = r
(HERE / "validation_results.json").write_text(json.dumps(res, indent=1))
L = ["# Config validation (offline, the runner's own loader, --estimate and --dry-run on temporary copies)", "",
     "| config | items | frameworks | models | trials per cell | trials in total | cap USD | --estimate | dry run of a cut-down copy |", "|---|---|---|---|---|---|---|---|---|"]
for n, r in res.items():
    est = (f"expected USD {r['estimate']['expected_usd']:.2f}, worst case USD {r['estimate']['worst_case_usd']:.2f}" if "estimate" in r else f"REFUSED (rc {r['estimate_rc']}): {r['estimate_refusal']}")
    d = r["dry_run"]
    L.append(f"| {n} | {r['items']} | {'+'.join(r['frameworks'])} | {len(r['models'])} ({', '.join(r['tiers'])}) | {r['trials']} | {r['n_trials']} | {r['cap_usd']:.0f} | {est} | rc {d['rc']}, {d['trials_run']} trials, evidence lines {d['evidence_lines']}, verify: {d['verify']} |")
seqs = {"langchain+adk only": ["smoke_openai_agents", "smoke_frontier", "main_cheap", "main_frontier"], "with openai_agents in the main runs": ["smoke_openai_agents", "smoke_frontier", "main_cheap_with_oa", "main_frontier_with_oa"]}
L += ["", "## Totals against the USD 100 total budget (caps and the runner's INFERRED expected / worst-case estimates)", "", "| sequence | trials | sum of caps | sum of expected | sum of worst case |", "|---|---|---|---|---|"]
tot = {}
for k, names in seqs.items():
    t = {"trials": sum(res[n]["n_trials"] for n in names), "caps": sum(res[n]["cap_usd"] for n in names), "expected": sum(res[n]["estimate"]["expected_usd"] for n in names), "worst": sum(res[n]["estimate"]["worst_case_usd"] for n in names)}
    tot[k] = t
    L.append(f"| {k} | {t['trials']:,} | {t['caps']:.2f} | {t['expected']:.2f} | {t['worst']:.2f} |")
res["_totals"] = tot
(HERE / "validation_results.json").write_text(json.dumps(res, indent=1))
(HERE / "validation_results.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
