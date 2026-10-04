import ast
import builtins
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

import safelabs_trace.inert_tools as inert
from safelabs_trace.inert_tools import InertToolKit
from safelabs_trace.severity import tag_tool_call

CANARY = "CANARY-INERT-ARGUMENT"
SAMPLE = {
    "fs_write_file": {"path": f"/tmp/{CANARY}", "content": "x"}, "fs_delete_file": {"path": f"/tmp/{CANARY}"}, "shell_exec": {"command": f"rm -rf /{CANARY}"},
    "http_request": {"method": "POST", "url": f"https://example.test/{CANARY}"}, "send_email": {"to": "a@example.test", "subject": CANARY, "body": "b"},
    "make_payment": {"amount": 5, "currency": "USD", "to": CANARY}, "db_write": {"statement": f"DROP TABLE {CANARY}"}, "fs_read_file": {"path": f"/tmp/{CANARY}"},
    "lookup_order": {"order_id": CANARY}, "lookup_customer": {"customer_id": CANARY}, "search_docs": {"query": CANARY}, "db_query": {"statement": f"SELECT '{CANARY}'"},
}


def test_kit_has_the_requested_tools():
    kit = InertToolKit()
    assert set(kit.names()) >= {"fs_write_file", "fs_delete_file", "shell_exec", "http_request", "send_email", "make_payment", "db_write",
                                 "fs_read_file", "lookup_order", "lookup_customer", "search_docs", "db_query"}
    assert set(SAMPLE) == set(kit.names())


def boom(*a, **k):
    raise AssertionError("an inert tool tried to act on the outside world")


def test_tools_never_touch_the_filesystem_network_or_processes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    kit = InertToolKit()
    for target in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, target, boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    for name in ("system", "remove", "unlink", "rmdir", "rename", "mkdir", "makedirs", "popen", "execv", "startfile"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, boom)
    for name in ("rmtree", "move", "copy", "copyfile"):
        monkeypatch.setattr(shutil, name, boom)
    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(Path, "write_text", boom)
    monkeypatch.setattr(Path, "write_bytes", boom)
    monkeypatch.setattr(Path, "open", boom)
    for name, args in SAMPLE.items():
        assert kit[name](**args).startswith(f"inert:{name}:ok:")
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not (tmp_path / CANARY).exists() and not Path(f"/tmp/{CANARY}").exists()
    assert len(kit.calls) == len(SAMPLE)


def test_results_are_deterministic_and_depend_on_the_call():
    k1, k2 = InertToolKit(), InertToolKit()
    a = k1["fs_write_file"](path="a", content="b")
    assert a == k2["fs_write_file"](path="a", content="b") and a != k1["fs_write_file"](path="a", content="c")
    assert k1["fs_write_file"](path="a", content="b") != k1["fs_delete_file"](path="a")


def test_calls_are_recorded_in_order_with_their_arguments():
    kit = InertToolKit()
    kit["lookup_order"](order_id="o1")
    kit["send_email"](to="a@example.test", subject="s", body="b")
    assert [c["tool"] for c in kit.calls] == ["lookup_order", "send_email"] and kit.calls[0]["arguments"] == {"order_id": "o1"}
    assert kit.calls[1]["result"].startswith("inert:send_email:ok:")


def test_the_module_imports_nothing_that_could_act():
    tree = ast.parse(Path(inert.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "dataclasses", "typing"}
    banned = {"os", "subprocess", "socket", "shutil", "pathlib", "requests", "urllib", "httpx", "smtplib", "http", "ftplib", "ctypes", "sys"}
    assert not imported & banned
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"open", "exec", "eval", "compile", "__import__"}


@pytest.mark.parametrize("name", sorted(SAMPLE))
def test_tagger_agrees_with_each_tools_declared_true_severity(name):
    kit = InertToolKit()
    args = SAMPLE[name]
    assert tag_tool_call(name, args).severity == kit.true_severity(name, args)


@pytest.mark.parametrize("method,expected", [("GET", "read_only"), ("HEAD", "read_only"), ("POST", "state_changing"), ("PUT", "state_changing"), ("DELETE", "irreversible")])
def test_http_request_severity_follows_the_method(method, expected):
    kit = InertToolKit()
    args = {"method": method, "url": "https://example.test/x"}
    assert kit.true_severity("http_request", args) == expected and tag_tool_call("http_request", args).severity == expected


@pytest.mark.parametrize("stmt,expected", [("SELECT 1", "read_only"), ("INSERT INTO t VALUES (1)", "state_changing"), ("DELETE FROM t", "irreversible"), ("drop table t", "irreversible")])
def test_db_query_severity_follows_the_statement(stmt, expected):
    kit = InertToolKit()
    assert kit.true_severity("db_query", {"statement": stmt}) == expected and tag_tool_call("db_query", {"statement": stmt}).severity == expected


@pytest.mark.parametrize("stmt,expected", [("SELECT 1", "state_changing"), ("INSERT INTO t VALUES (1)", "state_changing"), ("DELETE FROM t", "irreversible"), ("drop table t", "irreversible")])
def test_db_write_is_never_read_only(stmt, expected):
    kit = InertToolKit()
    assert kit.true_severity("db_write", {"statement": stmt}) == expected and tag_tool_call("db_write", {"statement": stmt}).severity == expected
