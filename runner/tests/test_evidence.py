"""The local-only evidence sidecar (D10): content, redaction, permissions, refusals, final_text_len, and that nothing of it reaches a public output."""

import json
import os
import stat

import pytest

from rt_helpers import FRAMEWORKS, SALT, make_cfg, make_runner, model, read_jsonl, run
from trace_runner.cli import main
from trace_runner.evidence import REDACTED, EvidenceRefusal, EvidenceWriter, Redactor, check_evidence_dir
from trace_runner.fakes import COMPLY_TEXT, REFUSE_TEXT
from safelabs_trace.writer import read_trace
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FAKE_ANT = "sk-ant-api03-FAKEFAKEFAKEFAKE0123456789"
FAKE_SK = "sk-proj-FAKEFAKEFAKEFAKEFAKE0123"
FAKE_AIZA = "AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKE0123"
CMD_UNCLASSIFIED = "frobnicate --widgets CANARY-CMD-5521"
PLAN = {"by_prompt": {
    "ASI01-900": {"kind": "comply_tool", "tool": "shell_exec", "args": {"command": CMD_UNCLASSIFIED}, "text": "FAKE-COMPLY CANARY-ANSWER-3377 done"},
    "ASI01-901": {"kind": "refuse_irreversible_tool", "tool": "fs_delete_file", "args": {"path": "/data/CANARY-PATH-8842.db"}},
    "ASI01-902": {"kind": "comply_tool", "tool": "fs_write_file", "args": {"path": "/x", "content": f"token {FAKE_ANT} and key={FAKE_SK} and {FAKE_AIZA} and Bearer abc.def-ghi123456 and {SALT.decode()}"}},
    "ASI01-903": "silent_irreversible", "ASI01-904": "unclear_text", "ASI01-905": {"kind": "refuse_no_tool", "text": f"FAKE-REFUSE no. {FAKE_ANT}"}}}
CANARIES = ("CANARY-CMD-5521", "CANARY-ANSWER-3377", "CANARY-PATH-8842")


@pytest.fixture
def done(tmp_path, openai_sdk):
    cfg = make_cfg(tmp_path, n_items=6, plan=PLAN)
    r = make_runner(tmp_path, cfg)
    r.evidence = EvidenceWriter(tmp_path / "evidence", tmp_path / "out", SALT)
    run(r.run())
    lines = read_jsonl(tmp_path / "evidence" / "evidence.jsonl")
    return tmp_path, lines


def test_evidence_has_one_line_per_trial_with_the_raw_arguments_the_stub_result_and_the_trace_ids(done):
    tmp, lines = done
    assert len(lines) == 18 and {(x["framework"], x["prompt_id"]) for x in lines} == {(f, f"ASI01-90{i}") for f in FRAMEWORKS for i in range(6)}
    tm = json.loads((tmp / "out" / "trace_manifest.json").read_text())
    for x in lines:
        e = tm["trials"][f"{x['framework']}|m1|{x['prompt_id']}|0"]
        assert x["attempt"] == 1 and x["trial_seed"] == 0 and x["model"] == "m1" and x["trace_id"] == e["final_trace_id"] and x["schema"] == "1b-evidence/1"
        ev = {v.event_id: v for v in read_trace(tmp / "out" / e["trace_file"])}
        assert len(x["tool_calls"]) == len(e["tools_called"])
        for c in x["tool_calls"]:
            rq, ex = ev[c["requested_event_id"]], ev[c["executed_event_id"]]
            assert rq.type == "tool.call.requested" and ex.type == "tool.call.executed" and rq.tool.name == c["tool"] == ex.tool_name
            assert c["severity"] == rq.severity and c["rule_ids"] == list(rq.rule_ids) and c["severity_basis"] == rq.severity_basis and c["matched_to_trace"]
            assert c["stub_result"].startswith(f"inert:{c['tool']}:ok:")
    by = {(x["framework"], x["prompt_id"]): x for x in lines}
    a = by[("langchain", "ASI01-900")]
    assert a["final_text"] == "FAKE-COMPLY CANARY-ANSWER-3377 done" and a["tool_calls"][0]["arguments"] == {"command": CMD_UNCLASSIFIED}
    assert a["tool_calls"][0]["rule_ids"][0] in ("N-EXEC", "A-SHELL-OTHER") and a["tool_calls"][0]["severity"] == "irreversible"
    assert by[("adk", "ASI01-901")]["tool_calls"][0]["arguments"] == {"path": "/data/CANARY-PATH-8842.db"}
    assert by[("openai_agents", "ASI01-903")]["final_text"] == "" and by[("openai_agents", "ASI01-903")]["tool_call_only"] is True and by[("adk", "ASI01-904")]["verdict"] == "uncertain"
    assert by[("adk", "ASI01-905")]["tool_calls"] == [] and by[("adk", "ASI01-905")]["final_text"].startswith("FAKE-REFUSE no.")


def test_key_like_strings_and_the_salt_come_out_redacted_in_arguments_and_text(done):
    tmp, lines = done
    raw = (tmp / "evidence" / "evidence.jsonl").read_text()
    for secret in (FAKE_ANT, FAKE_SK, FAKE_AIZA, "abc.def-ghi123456", SALT.decode()):
        assert secret not in raw, secret
    x = next(x for x in lines if x["prompt_id"] == "ASI01-902")
    content = x["tool_calls"][0]["arguments"]["content"]
    assert content.count(REDACTED) == 5 and content.startswith("token [REDACTED] and key=[REDACTED] and [REDACTED] and [REDACTED] and [REDACTED]") and x["redactions"] == 5
    t = next(x for x in lines if x["prompt_id"] == "ASI01-905")
    assert t["final_text"] == "FAKE-REFUSE no. [REDACTED]" and t["redactions"] == 1


def test_folder_mode_700_file_mode_600_and_a_readme(done):
    tmp, _ = done
    d = tmp / "evidence"
    assert stat.S_IMODE(d.stat().st_mode) == 0o700 and stat.S_IMODE((d / "evidence.jsonl").stat().st_mode) == 0o600 and stat.S_IMODE((d / "README.txt").stat().st_mode) == 0o600
    t = (d / "README.txt").read_text()
    assert "LOCAL ONLY" in t and "NEVER COMMIT" in t and "NEVER UPLOAD" in t


def test_nothing_from_the_evidence_reaches_a_public_output_and_final_text_len_is_only_in_the_trace_manifest(done):
    from agentport_bench.schema import BenchTrialResult

    tmp, lines = done
    for p in (tmp / "out").rglob("*"):
        if p.is_file():
            text = p.read_text(errors="replace")
            for c in CANARIES + (FAKE_ANT, FAKE_SK, FAKE_AIZA, REFUSE_TEXT, COMPLY_TEXT):
                assert c not in text, f"{c} in {p.name}"
    raw = read_jsonl(tmp / "out" / "results.jsonl")
    assert len(raw) == 18 and all("final_text_len" not in r for r in raw)  # results rows stay plain AgentPort-Bench rows
    assert [BenchTrialResult(**r) for r in raw]  # and validate as such, with no field dropped
    tm = json.loads((tmp / "out" / "trace_manifest.json").read_text())["trials"]
    assert "final_text_len" not in (tmp / "out" / "divergence_summary.json").read_text() and "final_text_len" not in (tmp / "out" / "results.manifest.json").read_text()
    for x in lines:
        e = tm[f"{x['framework']}|{x['model']}|{x['prompt_id']}|{x['trial_seed']}"]
        assert isinstance(e["final_text_len"], int)
        if not x["redactions"]:
            assert e["final_text_len"] == len(x["final_text"]), x["prompt_id"]
    g = lambda fw, pid: tm[f"{fw}|m1|{pid}|0"]["final_text_len"]
    assert g("langchain", "ASI01-900") == len("FAKE-COMPLY CANARY-ANSWER-3377 done")
    assert g("adk", "ASI01-903") == 0 and g("adk", "ASI01-901") == len(REFUSE_TEXT)
    assert g("adk", "ASI01-905") == len(f"FAKE-REFUSE no. {FAKE_ANT}")  # the length is of the text as the model sent it (before redaction)
    # the evidence record carries the same original length, whatever was cut
    assert next(x for x in lines if x["framework"] == "adk" and x["prompt_id"] == "ASI01-905")["final_text_len"] == g("adk", "ASI01-905")


def test_a_missing_infrastructure_row_has_no_final_text_len_in_the_manifest_and_a_rerun_appends_a_line(tmp_path, openai_sdk):
    plan = {"by_prompt": {"ASI01-900": {"kind": "refuse_no_tool", "fail_passes": [0]}}}
    cfg = make_cfg(tmp_path, n_items=1, plan=plan, frameworks=["langchain"])
    r = make_runner(tmp_path, cfg)
    r.evidence = EvidenceWriter(tmp_path / "ev", tmp_path / "out", SALT)
    run(r.run())
    row = read_jsonl(tmp_path / "out" / "results.jsonl")[0]
    tm = lambda: json.loads((tmp_path / "out" / "trace_manifest.json").read_text())["trials"]["langchain|m1|ASI01-900|0"]
    assert row["status"] == "missing_infrastructure" and "final_text_len" not in row and tm()["final_text_len"] is None
    first = read_jsonl(tmp_path / "ev" / "evidence.jsonl")
    assert len(first) == 1 and first[0]["status"] == "missing_infrastructure" and first[0]["final_text"] == ""
    r2 = make_runner(tmp_path, cfg)
    r2.evidence = r.evidence
    run(r2.rerun_missing())
    row = read_jsonl(tmp_path / "out" / "results.jsonl")[0]
    assert row["status"] == "scored" and "final_text_len" not in row and tm()["final_text_len"] == len(REFUSE_TEXT)
    lines = read_jsonl(tmp_path / "ev" / "evidence.jsonl")
    assert len(lines) == 2 and lines[-1]["run_pass"] == 1 and lines[-1]["final_text"] == REFUSE_TEXT and lines[-1]["attempt"] > 1


def test_long_answers_and_arguments_are_cut_at_the_cap_with_truncated_flags(tmp_path, openai_sdk):
    """Default cap 20,000 characters per final answer and per raw-argument string; the original length is kept; short fields say truncated: false."""
    from trace_runner.evidence import MAX_FIELD_CHARS

    assert MAX_FIELD_CHARS == 20_000
    long_text, long_arg = "FAKE-COMPLY " + "a" * 25_000, "b" * 20_001
    plan = {"by_prompt": {"ASI01-900": {"kind": "comply_tool", "tool": "fs_write_file", "args": {"path": "/short", "content": long_arg}, "text": long_text},
                          "ASI01-901": {"kind": "comply_tool", "tool": "fs_write_file", "args": {"path": "/p", "content": "c" * 20_000}, "text": "FAKE-COMPLY " + "d" * 19_988}}}
    cfg = make_cfg(tmp_path, n_items=2, plan=plan, frameworks=["langchain"])
    r = make_runner(tmp_path, cfg)
    r.evidence = EvidenceWriter(tmp_path / "ev", tmp_path / "out", SALT)
    run(r.run())
    a, b = (next(x for x in read_jsonl(tmp_path / "ev" / "evidence.jsonl") if x["prompt_id"] == pid) for pid in ("ASI01-900", "ASI01-901"))
    assert a["max_field_chars"] == 20_000 and a["final_text_truncated"] is True and len(a["final_text"]) == 20_000 and a["final_text"] == long_text[:20_000] and a["final_text_len"] == len(long_text)
    c = a["tool_calls"][0]
    assert c["arguments_truncated"] is True and c["arguments_truncated_fields"] == ["content"] and len(c["arguments"]["content"]) == 20_000 and c["arguments"]["path"] == "/short"
    # exactly at the cap: nothing is cut
    assert b["final_text_truncated"] is False and len(b["final_text"]) == 20_000 and b["tool_calls"][0]["arguments_truncated"] is False and b["tool_calls"][0]["arguments_truncated_fields"] == []
    # the length in the manifest is the original one
    tm = json.loads((tmp_path / "out" / "trace_manifest.json").read_text())["trials"]
    assert tm["langchain|m1|ASI01-900|0"]["final_text_len"] == len(long_text)


def test_a_key_is_redacted_before_the_cut_so_no_fragment_of_it_survives(tmp_path):
    key = "sk-ant-api03-" + "Z" * 40
    w = EvidenceWriter(tmp_path / "ev", tmp_path / "out", SALT, max_chars=10)
    w.write({"final_text": "x" * 5 + key, "tool_calls": [{"arguments": {"cmd": "y" * 4 + key, "n": 3, "l": ["z" * 11]}}]})
    rec = read_jsonl(tmp_path / "ev" / "evidence.jsonl")[0]
    assert "ZZZ" not in json.dumps(rec) and rec["final_text"] == "xxxxx[REDA" and rec["final_text_truncated"] is True
    c = rec["tool_calls"][0]
    assert c["arguments"]["cmd"] == "yyyy[REDAC" and c["arguments_truncated"] is True and sorted(c["arguments_truncated_fields"]) == ["cmd", "l[0]"] and c["arguments"]["n"] == 3 and c["arguments"]["l"] == ["z" * 10]


def test_redactor_patterns_and_it_never_reads_environment_variables(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "plainvalue-no-pattern-1234")  # an env value in the text must survive: nothing reads the environment
    red = Redactor(b"long-random-salt-value-xyz")
    s = f"a {FAKE_ANT} b {FAKE_SK} c {FAKE_AIZA} d Bearer eyJhbGciOi.payload-part_9 e plainvalue-no-pattern-1234 f long-random-salt-value-xyz g ghp_{'a' * 24} h AKIA{'B' * 16}"
    out = red.text(s)
    assert out == f"a {REDACTED} b {REDACTED} c {REDACTED} d {REDACTED} e plainvalue-no-pattern-1234 f {REDACTED} g {REDACTED} h {REDACTED}" and red.count == 7
    assert Redactor(b"abc").text("abc stays") == "abc stays"  # a very short salt is not used (it would mangle ordinary words)
    assert Redactor(None).obj({"k": [FAKE_SK, 3, None, {"n": FAKE_ANT}]}) == {"k": [REDACTED, 3, None, {"n": REDACTED}]}


def _mk_repo(p):
    (p / ".git").mkdir(parents=True)
    return p


def test_refusals_inside_a_git_tree_the_output_folder_and_foreign_folders(tmp_path):
    out = tmp_path / "out"
    repo = _mk_repo(tmp_path / "repo")
    for bad in (repo / "ev", repo / "a" / "b" / "ev", repo):
        with pytest.raises(EvidenceRefusal, match="git working tree"):
            check_evidence_dir(bad, out)
        assert not bad.exists() or bad == repo  # nothing was created
    (tmp_path / "link_target_repo").mkdir()
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    with pytest.raises(EvidenceRefusal, match="git working tree"):
        check_evidence_dir(link / "ev", out)  # a symlink into a repository is resolved first
    # a .git FILE (worktree or submodule) counts too
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /elsewhere")
    with pytest.raises(EvidenceRefusal, match="git working tree"):
        check_evidence_dir(wt / "ev", out)
    for bad in (out, out / "inner", tmp_path):  # equal, inside, containing the output folder
        with pytest.raises(EvidenceRefusal, match="output folder"):
            check_evidence_dir(bad, out)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("x")
    with pytest.raises(EvidenceRefusal, match="not empty"):
        check_evidence_dir(foreign, out)
    afile = tmp_path / "afile"
    afile.write_text("x")
    with pytest.raises(EvidenceRefusal, match="not a folder"):
        check_evidence_dir(afile, out)
    assert check_evidence_dir(tmp_path / "fine", out) == (tmp_path / "fine").resolve()
    assert check_evidence_dir(foreign.parent / "e2", out)


def test_an_existing_evidence_folder_of_this_runner_can_be_reused_and_modes_are_reset(tmp_path):
    w = EvidenceWriter(tmp_path / "ev", tmp_path / "out", SALT)
    w.write({"a": 1})
    os.chmod(tmp_path / "ev", 0o755)
    os.chmod(tmp_path / "ev" / "evidence.jsonl", 0o644)
    w2 = EvidenceWriter(tmp_path / "ev", tmp_path / "out", SALT)
    w2.write({"a": 2})
    assert stat.S_IMODE((tmp_path / "ev").stat().st_mode) == 0o700 and stat.S_IMODE((tmp_path / "ev" / "evidence.jsonl").stat().st_mode) == 0o600
    assert [json.loads(x)["a"] for x in (tmp_path / "ev" / "evidence.jsonl").read_text().splitlines()] == [1, 2]


def test_cli_dry_run_with_evidence_dir_and_its_refusals(tmp_path, capsys):
    out, ev = tmp_path / "d", tmp_path / "ev"
    cfg = str(HERE / "configs" / "dryrun.yaml")
    assert main(["--config", cfg, "--dry-run", "--out", str(out), "--evidence-dir", str(ev)]) == 0
    assert len(read_jsonl(ev / "evidence.jsonl")) == 45 and stat.S_IMODE(ev.stat().st_mode) == 0o700 and stat.S_IMODE((ev / "evidence.jsonl").stat().st_mode) == 0o600
    assert "local-only evidence: 45 line(s)" in capsys.readouterr().out
    assert main(["--config", cfg, "--dry-run", "--out", str(out), "--verify"]) == 0
    repo = _mk_repo(tmp_path / "repo")
    assert main(["--config", cfg, "--dry-run", "--out", str(tmp_path / "d2"), "--evidence-dir", str(repo / "ev")]) == 2
    assert "git working tree" in capsys.readouterr().err and not (tmp_path / "d2" / "results.jsonl").exists() and not (repo / "ev").exists()
    assert main(["--config", cfg, "--dry-run", "--out", str(tmp_path / "d3"), "--evidence-dir", str(tmp_path / "d3" / "ev")]) == 2
    assert main(["--config", cfg, "--evidence-dir", str(tmp_path / "e4"), "--estimate"]) == 2
    assert main(["--config", cfg, "--out", str(out), "--evidence-dir", str(tmp_path / "e5"), "--summarize", "--summary-out", str(tmp_path / "s")]) == 2
    assert not (tmp_path / "e4").exists() and not (tmp_path / "e5").exists()
