"""Billing / credit / quota errors and unknown exceptions end missing_infrastructure (never scored); --reclassify-errors repairs old folders; summaries count the repaired rows."""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from rt_helpers import SALT, make_cfg, make_runner, read_jsonl, run
from trace_runner.cli import main
from trace_runner.evidence import EvidenceWriter
from trace_runner.errors import is_billing
from trace_runner.fakes import FakeProvider
from trace_runner.orchestrator import Paths, build_divergence, summarize_to, verify_manifest
from trace_runner.repair import RUN_MARKER, RepairRefusal, mark_running, reclassify_errors

BILLING_KINDS = ["anthropic_credit", "openai_quota", "http402", "google_quota", "litellm_budget"]


def one_trial(tmp_path, error, openai_sdk, fw="langchain"):
    plan = {"by_trial": {f"{fw}|m1|ASI01-900|0": {"kind": "comply_tool", "fail_passes": [0, 1, 2], "fail_attempts": 99, "error": error}}}
    cfg = make_cfg(tmp_path, n_items=1, frameworks=[fw], plan=plan)
    prov = FakeProvider(cfg.fake_plan)
    r = make_runner(tmp_path, cfg, provider=prov)
    run(r.run())
    return [json.loads(x) for x in Paths(tmp_path / "out").results.read_text().splitlines()], prov, cfg


@pytest.mark.parametrize("fw", ["langchain", "adk", "openai_agents"])
@pytest.mark.parametrize("error", BILLING_KINDS)
def test_billing_error_ends_missing_at_once_and_is_not_retried(tmp_path, openai_sdk, error, fw):
    (row,), prov, _ = one_trial(tmp_path, error, openai_sdk, fw)
    assert row["status"] == "missing_infrastructure" and row["verdict"] is None and row["confidence"] is None and row["attack_success_weight"] is None
    assert row["error_class"] == "infrastructure" and row["error_subclass"] == "billing"
    assert row["attempts"] == 1 and row["attempt_errors"] == ["billing"]  # one real model call; no retry and no back-off
    assert len(prov.built) == 1


def test_unknown_exception_ends_missing_with_its_error_fields_kept(tmp_path, openai_sdk):
    (row,), prov, _ = one_trial(tmp_path, "unknown", openai_sdk)
    assert row["status"] == "missing_infrastructure" and row["verdict"] is None
    assert row["error_class"] == "other" and row["error_subclass"] == "other" and "kaboom" in row["error"]
    assert row["attempts"] == 1 and len(prov.built) == 1  # the harness does not retry an "other" error


def test_content_policy_stays_scored_by_convention(tmp_path, openai_sdk):
    (row,), _, _ = one_trial(tmp_path, "content_policy", openai_sdk)
    assert row["status"] in (None, "scored") and row["verdict"] == "uncertain" and row["error_class"] == "content_policy"


def test_a_transient_rate_limit_is_still_retried(tmp_path, openai_sdk):
    plan = {"by_prompt": {"ASI01-900": {"kind": "refuse_no_tool", "fail_attempts": 1}}}
    cfg = make_cfg(tmp_path, n_items=1, frameworks=["langchain"], plan=plan)
    run(make_runner(tmp_path, cfg).run())
    (row,) = read_jsonl(Paths(tmp_path / "out").results)
    assert row["status"] in (None, "scored") and row["attempts"] == 2 and row["error_class"] is None


def test_is_billing_texts():
    assert is_billing("Your credit balance is too low to access the Anthropic API")
    assert is_billing("error code: insufficient_quota") and is_billing("You exceeded your current quota")
    assert is_billing("429 RESOURCE_EXHAUSTED: quota exceeded for metric") and is_billing("x", {"status_code": 402})
    assert not is_billing("RESOURCE_EXHAUSTED: too many requests per minute") and not is_billing("rate limit reached, retry in 2s") and not is_billing(None)


# ---- repair -------------------------------------------------------------------------------------------------------
PLAN = {"by_trial": {"adk|m1|ASI01-901|0": {"kind": "comply_tool", "fail_passes": [0], "error": "anthropic_credit"},
                     "openai_agents|m1|ASI01-902|0": {"kind": "refuse_irreversible_tool", "fail_passes": [0], "error": "unknown"}}}


def old_style_folder(tmp_path, openai_sdk):
    """A finished run folder as the OLD runner left it: the two failing trials are scored UNCERTAIN rows with an error_class (manifests and evidence consistent with that)."""
    cfg = make_cfg(tmp_path, n_items=3, plan=PLAN)
    prov = FakeProvider(cfg.fake_plan)
    r = make_runner(tmp_path, cfg, provider=prov)
    r.evidence = EvidenceWriter(tmp_path / "evid", tmp_path / "out", SALT)
    run(r.run())
    paths = Paths(tmp_path / "out")
    lines = paths.results.read_text().splitlines(keepends=True)
    tm = json.loads(paths.trace_manifest.read_text())
    n = 0
    for i, line in enumerate(lines):
        o = json.loads(line)
        if o["status"] == "missing_infrastructure":
            n += 1
            o.update(status="scored", verdict="uncertain", confidence=0.0, attack_success_weight=0.0, error_class="other", error_subclass="other")
            lines[i] = json.dumps(o) + "\n"
            e = next(e for e in tm["trials"].values() if e["result_key"]["prompt_id"] == o["prompt_id"] and e["framework"] == o["framework"])
            e.update(status="scored", verdict="uncertain")
    assert n == 2
    paths.results.write_text("".join(lines))
    import hashlib
    tm["results_sha256"] = hashlib.sha256(paths.results.read_bytes()).hexdigest()
    paths.trace_manifest.write_text(json.dumps(tm, indent=2, sort_keys=True))
    assert verify_manifest(paths) == []
    return cfg, prov, paths


def snapshot(folder: Path):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_dry_run_changes_nothing_and_lists_the_rows(tmp_path, openai_sdk, capsys):
    _, _, paths = old_style_folder(tmp_path, openai_sdk)
    before = snapshot(paths.out)
    out = reclassify_errors(paths.out, "t", dry_run=True)
    assert snapshot(paths.out) == before
    assert out[0].startswith("2 row(s) would be changed") and "framework=adk model=m1 prompt_id=ASI01-901 trial_seed=0 error_subclass=other" in "\n".join(out)
    cfgp = tmp_path / "c.yaml"
    assert main(["--config", "configs/dryrun.yaml", "--reclassify-errors", "--dry-run", "--out", str(paths.out)]) == 0
    assert "2 row(s) would be changed" in capsys.readouterr().out and snapshot(paths.out) == before


def test_repair_changes_exactly_the_error_rows_verify_passes_rerun_recovers_second_repair_finds_nothing(tmp_path, openai_sdk):
    cfg, prov, paths = old_style_folder(tmp_path, openai_sdk)
    before = paths.results.read_text().splitlines(keepends=True)
    traces_before = {k: v for k, v in snapshot(paths.out).items() if k.startswith("traces")}
    ev_before = (tmp_path / "evid" / "evidence.jsonl").read_bytes()
    out = reclassify_errors(paths.out, "9.9", dry_run=False, min_idle_s=0)
    assert out[0].startswith("2 row(s) changed")
    after = paths.results.read_text().splitlines(keepends=True)
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    assert len(changed) == 2 and all(json.loads(before[i])["error_class"] == "other" for i in changed)  # every other line is byte-identical
    for i in changed:
        o, was = json.loads(after[i]), json.loads(before[i])
        assert o["status"] == "missing_infrastructure" and o["verdict"] is None and o["confidence"] is None and o["attack_success_weight"] is None
        assert o["error_class"] == "other" and o["error_subclass"] == "other" and o["error"] == was["error"] and o["payload_hash"] == was["payload_hash"]
        rc = o["reclassified"]
        assert set(rc) == {"from_status", "from_verdict", "reason", "timestamp", "runner_version"} and rc["from_status"] == "scored" and rc["from_verdict"] == "uncertain" and rc["runner_version"] == "9.9"
    assert all("reclassified" not in json.loads(after[i]) for i in range(len(after)) if i not in changed)
    log = read_jsonl(paths.out / "repair_log.jsonl")
    assert len(log) == 2 and {x["framework"] for x in log} == {"adk", "openai_agents"} and all(x["from_verdict"] == "uncertain" for x in log)
    assert verify_manifest(paths) == []
    mf = json.loads(paths.manifest.read_text())
    assert mf["missing_infrastructure"] == 2 and mf["scored_trials"] == len(after) - 2
    assert {k: v for k, v in snapshot(paths.out).items() if k.startswith("traces")} == traces_before
    assert (tmp_path / "evid" / "evidence.jsonl").read_bytes() == ev_before
    assert len(list(paths.out.glob("results.pre_reclassify*.jsonl"))) == 1
    # second repair: nothing to do, nothing written
    snap = snapshot(paths.out)
    assert reclassify_errors(paths.out, "9.9", dry_run=False, min_idle_s=0)[0].startswith("0 row(s)")
    assert snapshot(paths.out) == snap
    # the rerun picks them up like any missing row, writes a new attempt's trace and a new evidence line; the last evidence line per trial is the final attempt
    r2 = make_runner(tmp_path, cfg, provider=prov)
    r2.evidence = EvidenceWriter(tmp_path / "evid", paths.out, SALT)
    s = run(r2.rerun_missing())
    assert s.reattempted == 2 and s.recovered == 2 and s.still_missing == 0
    assert verify_manifest(paths) == []
    rows = read_jsonl(paths.results)
    rec = [x for x in rows if x.get("reclassified")]
    assert len(rec) == 2 and all(x["status"] == "scored" and x["error_class"] is None and x["attempts"] == 2 and x["rerun_passes"] == 1 for x in rec)
    tm = json.loads(paths.trace_manifest.read_text())
    e = tm["trials"]["adk|m1|ASI01-901|0"]
    assert e["status"] == "scored" and len(e["trace_ids"]) == 2 and e["final_trace_id"] == e["trace_ids"][-1]
    ev = read_jsonl(tmp_path / "evid" / "evidence.jsonl")
    for fw, pid in (("adk", "ASI01-901"), ("openai_agents", "ASI01-902")):
        mine = [x for x in ev if x["framework"] == fw and x["prompt_id"] == pid]
        assert [x["attempt"] for x in mine] == [1, 2] and mine[-1]["status"] == "scored" and mine[-1]["run_pass"] == 1
    assert reclassify_errors(paths.out, "9.9", dry_run=False, min_idle_s=0)[0].startswith("0 row(s)")  # recovered rows no longer carry an error


def test_repair_refuses_while_a_run_may_be_writing(tmp_path, openai_sdk):
    _, _, paths = old_style_folder(tmp_path, openai_sdk)
    snap = snapshot(paths.out)
    mark_running(paths.out, "run")
    with pytest.raises(RepairRefusal, match=RUN_MARKER):
        reclassify_errors(paths.out, "t", dry_run=False, min_idle_s=0)
    os.unlink(paths.out / RUN_MARKER)
    with pytest.raises(RepairRefusal, match="min-idle-seconds"):
        reclassify_errors(paths.out, "t", dry_run=False, min_idle_s=600)
    shutil.copy(paths.manifest, tmp_path / "mf.json")
    os.unlink(paths.manifest)
    with pytest.raises(RepairRefusal, match="not finished"):
        reclassify_errors(paths.out, "t", dry_run=False, min_idle_s=0)
    shutil.copy(tmp_path / "mf.json", paths.manifest)
    assert snapshot(paths.out) == snap  # refusals write nothing
    assert main(["--config", "configs/dryrun.yaml", "--reclassify-errors", "--out", str(paths.out)]) == 2  # the CLI default idle time refuses a folder written just now


def test_the_runner_writes_and_clears_the_run_marker(tmp_path, openai_sdk, monkeypatch):
    cfg = make_cfg(tmp_path, n_items=1, frameworks=["langchain"])
    r = make_runner(tmp_path, cfg)
    seen = []
    orig = r._run_one

    async def spy(*a, **k):
        seen.append((Paths(tmp_path / "out").out / RUN_MARKER).exists())
        return await orig(*a, **k)

    monkeypatch.setattr(r, "_run_one", spy)
    run(r.run())
    assert seen == [True] and not (tmp_path / "out" / RUN_MARKER).exists()
    run(make_runner(tmp_path, cfg).rerun_missing())
    assert not (tmp_path / "out" / RUN_MARKER).exists()


def test_summaries_count_reclassified_rows_as_missing_per_cell(tmp_path, openai_sdk):
    cfg, prov, paths = old_style_folder(tmp_path, openai_sdk)
    d = build_divergence(paths)  # not repaired yet: the scored rows with an error are already counted as missing
    assert d["excluded"]["missing_infrastructure"] == 2 and d["reclassified"]["unrepaired_error_rows"] == 2 and d["reclassified"]["total"] == 0
    reclassify_errors(paths.out, "t", dry_run=False, min_idle_s=0)
    d = summarize_to(paths, tmp_path / "sum")
    assert d["excluded"]["missing_infrastructure"] == 2 and d["reclassified"]["total"] == 2 and d["reclassified"]["still_missing"] == 2 and d["reclassified"]["unrepaired_error_rows"] == 0
    assert d["reclassified"]["by_cell"]["adk|m1"] == {"reclassified": 1, "still_missing": 1, "unrepaired_error_rows": 0}
    assert "| adk | m1 | 1 | 1 | 0 |" in (tmp_path / "sum" / "divergence_summary.md").read_text()
    run(make_runner(tmp_path, cfg, provider=prov).rerun_missing())
    d = build_divergence(paths)
    assert d["excluded"]["missing_infrastructure"] == 0 and d["reclassified"]["total"] == 2 and d["reclassified"]["still_missing"] == 0
