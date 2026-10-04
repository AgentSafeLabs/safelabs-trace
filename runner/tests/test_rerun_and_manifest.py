"""--rerun-missing fills only the missing rows; the manifest, traces and results stay in agreement."""

import json

from rt_helpers import make_cfg, make_runner, model, read_jsonl, run
from trace_runner.fakes import FakeProvider
from trace_runner.orchestrator import Paths, verify_manifest

PLAN = {"by_prompt": {"ASI01-900": "refuse_no_tool", "ASI01-901": "comply_tool", "ASI01-902": "refuse_irreversible_tool"},
        "by_trial": {"adk|m1|ASI01-901|0": {"kind": "comply_tool", "fail_passes": [0]},
                     "openai_agents|m1|ASI01-902|0": {"kind": "refuse_irreversible_tool", "fail_passes": [0, 1]}}}  # fails again in the first rerun pass


def setup(tmp_path, openai_sdk):
    cfg = make_cfg(tmp_path, n_items=3, plan=PLAN)
    prov = FakeProvider(cfg.fake_plan)
    r = make_runner(tmp_path, cfg, provider=prov)
    run(r.run())
    return cfg, prov, r, Paths(tmp_path / "out")


def test_rerun_missing_fills_only_missing_rows_and_nothing_else_changes(tmp_path, openai_sdk):
    cfg, prov, r, paths = setup(tmp_path, openai_sdk)
    before = paths.results.read_text().splitlines()
    rows = [json.loads(x) for x in before]
    missing_idx = [i for i, x in enumerate(rows) if x["status"] == "missing_infrastructure"]
    assert len(missing_idx) == 2
    built_before = len(prov.built)
    r2 = make_runner(tmp_path, cfg, provider=prov)  # a new process in real life: nothing carried over except the files
    summary = run(r2.rerun_missing())
    after = paths.results.read_text().splitlines()
    assert summary.reattempted == 2 and summary.recovered == 1 and summary.still_missing == 1
    assert [i for i in range(len(before)) if before[i] != after[i]] == missing_idx  # scored rows are byte-identical
    assert len(prov.built) - built_before == 1 + 3  # adk row: 1 attempt; openai row: 3 attempts and still failing (fails in passes 0 and 1)
    new = [json.loads(after[i]) for i in missing_idx]
    adk = next(x for x in new if x["framework"] == "adk")
    oa = next(x for x in new if x["framework"] == "openai_agents")
    assert adk["status"] == "scored" and adk["verdict"] == "fail" and adk["attempts"] == 4 and adk["rerun_passes"] == 1
    assert oa["status"] == "missing_infrastructure" and oa["attempts"] == 6 and oa["rerun_passes"] == 1
    assert verify_manifest(paths) == []
    tm = json.loads(paths.trace_manifest.read_text())
    e = tm["trials"]["adk|m1|ASI01-901|0"]
    assert e["status"] == "scored" and len(e["trace_ids"]) == 4 and e["final_trace_id"] == e["trace_ids"][-1] and e["tools_called"] == ["fs_write_file"]
    hist = json.loads(paths.manifest.read_text())["rerun_history"]
    assert [h["kind"] for h in hist] == ["initial", "rerun"] and hist[1]["recovered"] == 1 and hist[1]["still_missing"] == 1
    s = json.loads(paths.summary_json.read_text())
    assert s["excluded"]["missing_infrastructure"] == 1 and s["overall"]["n_known"] == 8


def test_a_second_rerun_pass_recovers_the_rest_and_a_third_does_nothing(tmp_path, openai_sdk):
    cfg, prov, r, paths = setup(tmp_path, openai_sdk)
    run(make_runner(tmp_path, cfg, provider=prov).rerun_missing())
    s2 = run(make_runner(tmp_path, cfg, provider=prov).rerun_missing())
    assert s2.reattempted == 1 and s2.recovered == 1
    assert all(x["status"] == "scored" for x in read_jsonl(paths.results))
    assert verify_manifest(paths) == []
    sha = paths.results.read_bytes()
    built = len(prov.built)
    s3 = run(make_runner(tmp_path, cfg, provider=prov).rerun_missing())
    assert s3.reattempted == 0 and not s3.rewrote_file and paths.results.read_bytes() == sha and len(prov.built) == built


def test_manifest_integrity_detects_changes(tmp_path, openai_sdk):
    cfg, prov, r, paths = setup(tmp_path, openai_sdk)
    assert verify_manifest(paths) == []
    tm = json.loads(paths.trace_manifest.read_text())
    assert len(tm["trials"]) == 9 and tm["salt_id"] == "testsalt" and tm["capture"] == "digest"
    assert all(e["trace_file"] and e["trace_ids"] for e in tm["trials"].values())
    # a trace changed after the fact
    tf = paths.out / next(iter(tm["trials"].values()))["trace_file"]
    with tf.open("a") as f:
        f.write("\n")
    assert any("trace sha256 differs" in p for p in verify_manifest(paths))
    # a results row changed after the fact
    with paths.results.open("a") as f:
        f.write("\n")
    assert any("results file sha256 differs" in p for p in verify_manifest(paths))


def test_every_row_links_to_a_trace_whose_trial_fields_match(tmp_path, openai_sdk):
    from safelabs_trace.writer import read_trace

    cfg, prov, r, paths = setup(tmp_path, openai_sdk)
    tm = json.loads(paths.trace_manifest.read_text())
    for tid, e in tm["trials"].items():
        starts = [ev for ev in read_trace(paths.out / e["trace_file"]) if ev.type == "session.start"]
        assert [s.trial["attempt"] for s in starts] == list(range(1, len(starts) + 1))
        assert all(s.trial["trial_id"] == tid and s.trial["prompt_id"] == e["prompt_id"] and s.trial["framework"] == e["framework"] for s in starts)
