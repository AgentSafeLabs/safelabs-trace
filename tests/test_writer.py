import json
import os
import threading
from pathlib import Path

import pytest

from safelabs_trace.schema import AgentStart, ModelCallStart, ToolCallRequested, ToolInfo, build_event
from safelabs_trace.writer import (
    CaptureDirError, SaltError, TraceError, TraceWriter, digest_value, iter_trace_files, read_trace, resolve_salt, salt_id,
)
from tests.helpers import SALT, full_coverage

CANARY = "CANARY-ARGUMENT-TEXT-98765"


def start(w, tid="t1"):
    return w.start_trace(tid, adapter="a", framework="f", framework_version="1.0", coverage=full_coverage(), tagger_version="1", rules_version="1")


def lines(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def requested(w, args, tid="t1"):
    cap = w.capture_value(args, trace_id=tid, event_id="e1", kind="args")
    return build_event(ToolCallRequested, {"args": "verified"}, trace_id=tid, event_id="e1", tool=ToolInfo(name="x"), args=cap, severity="state_changing", severity_basis="name_rule")


def test_digest_only_default_leaks_no_plaintext_and_no_salt(writer, tmp_path):
    start(writer)
    writer.write(requested(writer, {"path": CANARY, "content": CANARY * 3}))
    writer.close()
    text = (tmp_path / "run.jsonl").read_text()
    assert CANARY not in text and SALT.decode() not in text
    row = lines(tmp_path / "run.jsonl")[1]["args"]
    assert row["mode"] == "digest" and len(row["digest"]) == 16 and row["keys"] == ["content", "path"] and row["type"] == "dict" and row["size"] > 0
    assert row["ref"] is None and row["salt_id"] == salt_id(SALT) and row["salt_id"] != SALT.decode()
    assert lines(tmp_path / "run.jsonl")[0]["salt_id"] == salt_id(SALT)


def test_digest_is_salted_deterministic_and_canonical():
    a, _ = digest_value({"b": 1, "a": 2}, b"salt-one")
    assert a == digest_value({"a": 2, "b": 1}, b"salt-one")[0]
    assert a != digest_value({"a": 2, "b": 1}, b"salt-two")[0]
    assert digest_value("text", b"s")[1] == 4 and digest_value("héllo", b"s")[1] == 6


def test_no_salt_means_no_start_and_no_silent_unsalted_hashing(tmp_path, monkeypatch):
    monkeypatch.delenv("SAFELABS_TRACE_SALT", raising=False)
    with pytest.raises(SaltError):
        TraceWriter(tmp_path / "a.jsonl")
    assert TraceWriter(tmp_path / "b.jsonl", capture="none").salt_id is None


def test_salt_from_env_and_from_a_file_outside_any_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("SAFELABS_TRACE_SALT", "env-salt-canary")
    w = TraceWriter(tmp_path / "a.jsonl")
    assert w.salt_id == salt_id(b"env-salt-canary")
    monkeypatch.delenv("SAFELABS_TRACE_SALT")
    f = tmp_path / "x.salt"
    f.write_text("file-salt-canary\n")
    assert resolve_salt(salt_file=f) == b"file-salt-canary"
    assert TraceWriter(tmp_path / "b.jsonl", salt_file=f).salt_id == salt_id(b"file-salt-canary")
    assert resolve_salt(salt=b"explicit", env="SAFELABS_TRACE_SALT") == b"explicit"


def test_salt_file_inside_a_git_working_tree_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    f = repo / "x.salt"
    f.write_text("s")
    with pytest.raises(SaltError):
        resolve_salt(salt_file=f)
    empty = tmp_path / "empty.salt"
    empty.write_text("\n")
    with pytest.raises(SaltError):
        resolve_salt(salt_file=empty)


def test_capture_none_keeps_only_the_type(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", capture="none")
    cap = w.capture_value({"k": CANARY}, trace_id="t", event_id="e", kind="args")
    assert cap.mode == "none" and cap.digest is None and cap.size is None and cap.type == "dict"
    assert w.digest_text("some plan text")[0] is None


def make_repo(tmp_path, ignore=None):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    if ignore is not None:
        (repo / ".gitignore").write_text(ignore)
    return repo


def test_full_capture_goes_to_a_separate_git_ignored_file(tmp_path):
    repo = make_repo(tmp_path, "captures/\n")
    w = TraceWriter(repo / "traces" / "run.jsonl", capture="full", salt=SALT, capture_dir=repo / "captures")
    start(w)
    w.write(requested(w, {"path": CANARY}))
    trace_text = (repo / "traces" / "run.jsonl").read_text()
    assert CANARY not in trace_text
    cap = lines(repo / "traces" / "run.jsonl")[1]["args"]
    assert cap["mode"] == "full" and cap["ref"] == "run.full.jsonl#e1:args" and cap["digest"]
    full = lines(repo / "captures" / "run.full.jsonl")
    assert full == [{"trace_id": "t1", "event_id": "e1", "kind": "args", "value": {"path": CANARY}}]
    assert (repo / "captures" / "run.full.jsonl").read_text().count(CANARY) == 1


def test_full_capture_dir_must_be_ignored_when_in_a_git_tree(tmp_path):
    plain = make_repo(tmp_path / "a")
    with pytest.raises(CaptureDirError):
        TraceWriter(plain / "t.jsonl", capture="full", salt=SALT, capture_dir=plain / "captures")
    repo = make_repo(tmp_path / "b", "dist/\n")
    with pytest.raises(CaptureDirError):
        TraceWriter(tmp_path / "t.jsonl", capture="full", salt=SALT, capture_dir=repo / "captures")
    with pytest.raises(CaptureDirError):
        TraceWriter(tmp_path / "t2.jsonl", capture="full", salt=SALT)
    outside = TraceWriter(tmp_path / "t3.jsonl", capture="full", salt=SALT, capture_dir=tmp_path / "anywhere")  # not in a git tree
    assert outside.capture_dir.exists()


def test_event_before_header_and_after_close_are_refused(writer):
    ev = build_event(AgentStart, {}, trace_id="t1")
    with pytest.raises(TraceError):
        writer.write(ev)
    start(writer)
    with pytest.raises(TraceError):
        start(writer)
    writer.close()
    with pytest.raises(TraceError):
        writer.write(ev)


def test_seq_is_assigned_per_trace_in_order(writer, tmp_path):
    start(writer, "a")
    start(writer, "b")
    for tid in ("a", "b", "a"):
        writer.write(build_event(AgentStart, {}, trace_id=tid))
    rows = lines(tmp_path / "run.jsonl")
    assert [(r["trace_id"], r["seq"]) for r in rows] == [("a", 0), ("b", 0), ("a", 1), ("b", 1), ("a", 2)]


def test_long_event_is_truncated_and_flagged(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", salt=SALT, max_event_bytes=600)
    start(w)
    big = build_event(ModelCallStart, {"provider": "verified", "params": "verified", "tools_offered": "verified"}, trace_id="t1", call_id="c", provider="p" * 5000,
                      params={"x": "y" * 3000}, tools_offered=["t" * 100] * 40)
    assert w.write(big) is True
    row = lines(tmp_path / "a.jsonl")[1]
    assert row["truncated"] is True and len(json.dumps(row)) <= 700 and len(row["provider"]) <= 200
    ok = build_event(AgentStart, {}, trace_id="t1")
    w.write(ok)
    assert lines(tmp_path / "a.jsonl")[2]["truncated"] is False


def test_trace_limit_drops_events_and_writes_truncation_markers(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", salt=SALT, max_trace_events=4)
    start(w)
    results = [w.write(build_event(AgentStart, {}, trace_id="t1")) for _ in range(7)]
    assert results == [True, True, True, False, False, False, False]
    w.close_trace("t1")
    rows = lines(tmp_path / "a.jsonl")
    kinds = [r["type"] for r in rows]
    assert kinds.count("trace.truncated") == 2 and rows[-1]["final"] is True and rows[-1]["dropped_events"] == 4 and kinds.count("agent.start") == 3


def test_trace_byte_limit(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", salt=SALT)
    start(w)
    w.max_trace_bytes = (tmp_path / "a.jsonl").stat().st_size + 700  # room for the header (already written) and a few events
    n = sum(w.write(build_event(AgentStart, {}, trace_id="t1")) for _ in range(20))
    assert 0 < n < 20


def test_file_rotation_keeps_every_event_in_order(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", salt=SALT, max_file_bytes=700, max_trace_events=1000)
    start(w)
    for _ in range(12):
        w.write(build_event(AgentStart, {}, trace_id="t1"))
    w.close()
    files = iter_trace_files(tmp_path / "a.jsonl")
    assert len(files) > 1 and files[0].name == "a.jsonl" and files[1].name == "a.1.jsonl"
    events = list(read_trace(tmp_path / "a.jsonl"))
    assert len(events) == 13 and [e.seq for e in events] == list(range(13))


def test_appends_are_atomic_under_threads(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", salt=SALT, max_trace_events=10_000)
    start(w)

    def work():
        for _ in range(50):
            w.write(build_event(AgentStart, {}, trace_id="t1"))

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rows = lines(tmp_path / "a.jsonl")  # every line must parse
    assert len(rows) == 401 and sorted(r["seq"] for r in rows) == list(range(401))


def test_files_are_created_private(tmp_path):
    w = TraceWriter(tmp_path / "a.jsonl", salt=SALT)
    start(w)
    assert oct(os.stat(tmp_path / "a.jsonl").st_mode & 0o777) == "0o600"


def test_read_trace_round_trips_typed_events(writer, tmp_path):
    start(writer)
    writer.write(requested(writer, {"a": 1}))
    writer.close()
    evs = list(read_trace(tmp_path / "run.jsonl"))
    assert [e.type for e in evs] == ["trace.header", "tool.call.requested"] and evs[1].args.mode == "digest"
