"""The exporter is never called; canary strings never reach a trace, a result file, a manifest or a summary."""

import json

import pytest

from rt_helpers import FRAMEWORKS, make_cfg, make_runner, run
from trace_runner.safety import enforce_startup_safety

C_PROMPT, C_SYSTEM, C_ARGS = "CANARY-PROMPT-6401", "CANARY-SYSTEM-7512", "CANARY-TOOLARG-8623"


def test_openai_exporter_is_never_called_and_nothing_uses_the_network(tmp_path, openai_sdk):
    cfg = make_cfg(tmp_path, frameworks=["openai_agents"], n_items=4)
    enforce_startup_safety(cfg, {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})
    out = run(make_runner(tmp_path, cfg).run())
    assert out["ran"] == 4
    assert openai_sdk == []  # also asserted again by the fixture at teardown; the socket guard would have failed any connection attempt


def test_canary_strings_are_absent_from_every_output(tmp_path, openai_sdk):
    plan = {"by_prompt": {"ASI01-900": {"kind": "comply_tool", "tool": "fs_write_file", "args": {"path": "/x", "content": C_ARGS}},
                          "ASI01-901": {"kind": "refuse_irreversible_tool", "tool": "fs_delete_file", "args": {"path": f"/{C_ARGS}"}}}}
    cfg = make_cfg(tmp_path, n_items=3, plan=plan, canary=C_PROMPT, system_prompt=f"You are an assistant. {C_SYSTEM}")
    enforce_startup_safety(cfg, {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})
    r = make_runner(tmp_path, cfg)
    # the canaries really are in play: they are in the prompts, the system prompt and the tool arguments the fake models send
    assert all(C_PROMPT in i.prompt for i in r.items) and C_SYSTEM in cfg.system_prompt
    assert r.source.behaviour("t", "ASI01-900", "m1", "adk", 0).args["content"] == C_ARGS
    run(r.run())
    out = tmp_path / "out"
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len([p for p in files if p.parent.name == "traces"]) == 9
    for p in files:
        text = p.read_text(errors="replace")
        for c in (C_PROMPT, C_SYSTEM, C_ARGS):
            assert c not in text, f"{c} found in {p.name}"
    # and the traces do carry digests of the tool arguments (a positive control for the check above)
    some = next(p for p in files if p.parent.name == "traces" and "ASI01-900" in p.name)
    events = [json.loads(x) for x in some.read_text().splitlines()]
    req = [e for e in events if e["type"] == "tool.call.requested"]
    assert req and req[0]["args"]["digest"] and req[0]["args"]["mode"] == "digest"


def test_traces_are_digest_only_and_gitignored(tmp_path):
    cfg = make_cfg(tmp_path, frameworks=["langchain"], n_items=2)
    run(make_runner(tmp_path, cfg).run())
    assert (tmp_path / "out" / ".gitignore").read_text().strip() == "traces/"
    for p in (tmp_path / "out" / "traces").glob("*.jsonl"):
        for line in p.read_text().splitlines():
            e = json.loads(line)
            if e["type"] == "trace.header":
                assert e["capture"] == "digest"
