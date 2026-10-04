"""Google ADK trace handler tests. Offline: a scripted fake model, inert tools, no network (sockets to the outside are blocked by a fixture).
Strings are synthetic and non-harmful. Tests that need ADK skip cleanly when it is not installed."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from safelabs_trace.adk_handler import COVERAGE, COVERAGE_AGENT_CALLBACKS, ADKTraceHandler
from safelabs_trace.inert_tools import InertToolKit
from safelabs_trace.schema import EVENT_TYPES
from safelabs_trace.writer import TraceWriter, read_trace
from tests.helpers import SALT

CANARY_ARG = "CANARY-ADK-ARGUMENT-7311"
CANARY_USER = "CANARY-ADK-USER-MESSAGE-5522"
CANARY_MODEL = "CANARY-ADK-MODEL-TEXT-8844"
CANARY_RESULT = "CANARY-ADK-TOOL-RESULT-9966"
CANARY_SYSTEM = "CANARY-ADK-INSTRUCTION-1288"
ALL_CANARIES = (CANARY_ARG, CANARY_USER, CANARY_MODEL, CANARY_RESULT, CANARY_SYSTEM)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Block every outside connection. ``socket.socket`` itself is replaced by a subclass that refuses internet sockets but allows the
    AF_UNIX socketpair asyncio needs for its event loop."""
    real = socket.socket

    class GuardSocket(real):
        def __init__(self, family=-1, *a, **k):
            if family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("network access attempted in an offline test")
            super().__init__(family, *a, **k)

    def refuse(*a, **k):
        raise AssertionError("network access attempted in an offline test")

    monkeypatch.setattr(socket, "socket", GuardSocket)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def adk():
    pytest.importorskip("google.adk")
    pytest.importorskip("google.genai")
    import google.adk.agents as agents
    import google.adk.models.base_llm as base_llm
    import google.adk.models.llm_response as llm_response
    import google.adk.runners as runners
    import google.adk.tools as tools
    from google.genai import types
    return SimpleNamespace(agents=agents, BaseLlm=base_llm.BaseLlm, LlmResponse=llm_response.LlmResponse, runners=runners, tools=tools, types=types)


def text(adk, t, *, usage=None, finish="STOP", **kw):
    return adk.LlmResponse(content=adk.types.Content(role="model", parts=[adk.types.Part(text=t)]), usage_metadata=usage,
                           finish_reason=getattr(adk.types.FinishReason, finish) if finish else None, **kw)


def calls(adk, *specs, usage=None):
    """One model response asking for several tool calls. spec = (name, args) or (name, args, id)."""
    parts = []
    for s in specs:
        fc = adk.types.FunctionCall(name=s[0], args=s[1], **({"id": s[2]} if len(s) > 2 else {}))
        parts.append(adk.types.Part(function_call=fc))
    return adk.LlmResponse(content=adk.types.Content(role="model", parts=parts), usage_metadata=usage, finish_reason=adk.types.FinishReason.STOP)


def usage(adk, p, c, t=None):
    return adk.types.GenerateContentResponseUsageMetadata(prompt_token_count=p, candidates_token_count=c, thoughts_token_count=t)


def make_agent(adk, responses, *, tools=None, name="agent", instruction="be helpful", **kw):
    it = iter(responses)

    class _Llm(adk.BaseLlm):
        model: str = "fake-model"

        async def generate_content_async(self, llm_request, stream=False):
            yield next(it)

    return adk.agents.Agent(name=name, model=_Llm(), instruction=instruction, tools=tools or [], **kw)


def run_agent(adk, agent, *, plugin_handler=None, message="hello", tmp=None):
    """Run once on an in-memory runner; returns (final text, events). Exceptions from the run propagate."""
    from safelabs_trace.adk_handler import as_plugin

    async def go():
        plugins = [as_plugin(plugin_handler)] if plugin_handler is not None else []
        from google.adk.apps import App  # the Runner(plugins=...) argument is deprecated in 2.9.0 (runners.py:351); App carries the plugins
        runner = adk.runners.InMemoryRunner(app=App(name="app", root_agent=agent, plugins=plugins))
        session = await runner.session_service.create_session(app_name="app", user_id="u")
        out, evs = "", []
        async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=adk.types.Content(role="user", parts=[adk.types.Part(text=message)])):
            evs.append(ev)
            if ev.is_final_response() and ev.content and ev.content.parts:
                out = "".join(p.text or "" for p in ev.content.parts)
        return out, evs

    return asyncio.run(go())


def traced(adk, tmp_path, responses, *, tools=None, kit=None, handler_kw=None, message="hello", **agent_kw):
    from safelabs_trace.adk_handler import adk_tools
    kit = kit or InertToolKit()
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w, **(handler_kw or {}))
    agent = make_agent(adk, responses, tools=tools if tools is not None else adk_tools(kit), **agent_kw)
    out, evs = run_agent(adk, agent, plugin_handler=h, message=message)
    w.close()
    return SimpleNamespace(events=list(read_trace(tmp_path / "run.jsonl")), out=out, kit=kit, handler=h, path=tmp_path / "run.jsonl", writer=w)


def types_of(events):
    return [e.type for e in events]


def by(events, t):
    return [e for e in events if e.type == t]


# ---- event order -------------------------------------------------------------------------------------------------
def test_no_tool_turn_event_order_and_fields(adk, tmp_path):
    r = traced(adk, tmp_path, [text(adk, "plain answer", usage=usage(adk, 11, 4, 2))], tools=[], handler_kw={"trial": {"prompt_id": "P-1", "seed": 3}})
    ev = r.events
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    assert r.out == "plain answer"
    h = ev[0]
    assert h.framework == "google-adk" and h.framework_version and h.coverage == COVERAGE and set(h.coverage) == set(EVENT_TYPES) and h.adapter == "adk_handler"
    assert by(ev, "session.start")[0].trial == {"prompt_id": "P-1", "seed": 3} and by(ev, "session.start")[0].prov["session_id"] == "verified"
    start, end = by(ev, "model.call.start")[0], by(ev, "model.call.end")[0]
    assert start.model_requested == "fake-model" and start.tools_offered == [] and start.prov["tools_offered"] == "verified" and start.provider is None
    assert end.usage.input_tokens == 11 and end.usage.output_tokens == 4 and end.usage.reasoning_tokens == 2
    assert end.finish_reason_raw == "STOP" and end.tool_calls_requested_count == 0 and end.call_id == start.call_id and end.parent_event_id == start.event_id
    stop = by(ev, "stop")[0]
    assert stop.stop_raw == "STOP" and stop.stop_status == "end_of_turn" and stop.source_event_id == end.event_id
    assert by(ev, "agent.start")[0].agent.name == "agent" and by(ev, "agent.end")[0].outcome == "completed" and by(ev, "session.end")[0].reason == "completed"


def test_missing_usage_and_finish_reason_are_null_not_guessed(adk, tmp_path):
    r = traced(adk, tmp_path, [text(adk, "x", usage=None, finish=None)])
    end = by(r.events, "model.call.end")[0]
    assert end.usage is None and end.finish_reason_raw is None and end.prov["usage"] == "unknown" and end.prov["finish_reason_raw"] == "unknown"
    stop = by(r.events, "stop")[0]
    assert stop.stop_raw is None and stop.stop_status == "unknown"


def test_single_tool_call_links_severity_and_ids(adk, tmp_path):
    r = traced(adk, tmp_path, [calls(adk, ("lookup_order", {"order_id": "o1"}, "fc-1")), text(adk, "done")])
    ev = r.events
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "tool.call.requested", "tool.call.executed",
                            "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    mend = by(ev, "model.call.end")[0]
    req, ex = by(ev, "tool.call.requested")[0], by(ev, "tool.call.executed")[0]
    assert mend.tool_calls_requested_count == 1 and mend.finish_reason_raw == "STOP"
    assert req.parent_event_id == mend.event_id and req.model_call_id == mend.call_id and req.observed_at == "model_output"
    assert req.tool_call_id == "fc-1" and ex.tool_call_id == "fc-1" and ex.requested_event_id == req.event_id and ex.parent_event_id == req.event_id
    assert (req.severity, req.severity_basis) == ("read_only", "name_rule") == (ex.severity, ex.severity_basis)
    assert ex.status == "success" and ex.result.mode == "digest" and ex.duration_ms is not None and ex.tool_name == "lookup_order"
    assert [c["tool"] for c in r.kit.calls] == ["lookup_order"] and r.out == "done"
    assert by(ev, "model.call.start")[0].tools_offered == sorted(r.kit.names())  # ADK exposes the offered tool names


def test_a_call_id_that_adk_assigns_later_still_links_request_and_execution(adk, tmp_path):
    r = traced(adk, tmp_path, [calls(adk, ("lookup_order", {"order_id": "o1"})), text(adk, "done")])  # the model gave no call id
    req, ex = by(r.events, "tool.call.requested")[0], by(r.events, "tool.call.executed")[0]
    assert req.tool_call_id is None and req.prov["tool_call_id"] == "unknown"
    assert ex.tool_call_id and ex.tool_call_id != req.tool_call_id and ex.requested_event_id == req.event_id  # id read from the tool context at execution


def test_several_tool_calls_in_one_turn(adk, tmp_path):
    r = traced(adk, tmp_path, [calls(adk, ("lookup_order", {"order_id": "a"}, "c1"), ("fs_delete_file", {"path": "/x"}), ("lookup_order", {"order_id": "b"}),
                                     ("fs_write_file", {"path": "/y", "content": "z"}, "c4")), text(adk, "done")])
    ev = r.events
    reqs, exs = by(ev, "tool.call.requested"), by(ev, "tool.call.executed")
    assert len(reqs) == len(exs) == 4 and by(ev, "model.call.end")[0].tool_calls_requested_count == 4
    assert {x.requested_event_id for x in exs} == {q.event_id for q in reqs}  # one execution per request, none shared
    assert all(next(q for q in reqs if q.event_id == x.requested_event_id).tool.name == x.tool_name for x in exs)
    sev = {}
    for x in exs:
        sev.setdefault(x.tool_name, set()).add(x.severity)
    assert sev == {"lookup_order": {"read_only"}, "fs_delete_file": {"irreversible"}, "fs_write_file": {"state_changing"}}
    assert all(ev.index(q) < ev.index(x) for q in reqs for x in exs if x.requested_event_id == q.event_id)
    assert sorted(c["arguments"].get("order_id", "-") for c in r.kit.calls if c["tool"] == "lookup_order") == ["a", "b"]


def test_a_tool_that_raises_is_recorded_and_the_error_propagates(adk, tmp_path):
    def broken(order_id: str) -> str:
        """A tool that fails."""
        raise ValueError("synthetic tool failure")

    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    agent = make_agent(adk, [calls(adk, ("broken", {"order_id": "o"}, "c1")), text(adk, "never")], tools=[adk.tools.FunctionTool(broken)])
    with pytest.raises(ValueError, match="synthetic tool failure"):
        run_agent(adk, agent, plugin_handler=h)
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    ex = by(ev, "tool.call.executed")[0]
    assert ex.status == "error" and ex.error_type == "ValueError" and ex.result is None and ex.prov["error_type"] == "verified" and ex.tool_call_id == "c1"
    assert by(ev, "agent.end")[0].outcome == "error" and by(ev, "agent.end")[0].error_type == "ValueError"
    assert by(ev, "session.end")[0].reason == "error" and by(ev, "session.end")[0].error_type == "ValueError"
    assert types_of(ev)[-3:] == ["stop", "agent.end", "session.end"] and not h.errors


def test_unknown_tool_defaults_to_state_changing_with_basis_recorded(adk, tmp_path):
    def frobnicate(thing: str) -> str:
        """An unknown kind of tool."""
        return "ok"

    r = traced(adk, tmp_path, [calls(adk, ("frobnicate", {"thing": "t"}, "c1")), text(adk, "done")], tools=[adk.tools.FunctionTool(frobnicate)])
    req, ex = by(r.events, "tool.call.requested")[0], by(r.events, "tool.call.executed")[0]
    assert (req.severity, req.severity_basis, req.rule_ids[0]) == ("state_changing", "default_unknown", "DEFAULT-UNKNOWN") and ex.severity == "state_changing"
    sens = traced(adk, tmp_path / "s", [calls(adk, ("frobnicate", {"thing": "t"}, "c1")), text(adk, "done")], tools=[adk.tools.FunctionTool(frobnicate)],
                  handler_kw={"unknown_default": "read_only"}) if (tmp_path / "s").mkdir() is None else None
    assert by(sens.events, "tool.call.requested")[0].severity == "read_only" and by(sens.events, "tool.call.requested")[0].severity_basis == "default_unknown"


def test_an_irreversible_tool_is_tagged_irreversible(adk, tmp_path):
    r = traced(adk, tmp_path, [calls(adk, ("fs_delete_file", {"path": "/data/x"}, "c1")), text(adk, "done")])
    req = by(r.events, "tool.call.requested")[0]
    assert (req.severity, req.severity_basis, req.capability_hint) == ("irreversible", "name_rule", "filesystem.delete")
    assert by(r.events, "tool.call.executed")[0].severity == "irreversible"


def test_declared_hints_from_custom_metadata_can_raise(adk, tmp_path):
    def get_report(q: str) -> str:
        """Fetch a report."""
        return "r"

    tool = adk.tools.FunctionTool(get_report)
    tool.custom_metadata = {"destructiveHint": True}
    from safelabs_trace.writer import TraceWriter as W
    w = W(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    h.register_tools([tool])
    run_agent(adk, make_agent(adk, [calls(adk, ("get_report", {"q": "x"}, "c1")), text(adk, "done")], tools=[tool]), plugin_handler=h)
    w.close()
    req = by(list(read_trace(tmp_path / "run.jsonl")), "tool.call.requested")[0]
    assert (req.severity, req.severity_basis) == ("irreversible", "declared") and req.tool.declared == {"destructiveHint": True}


# ---- privacy -----------------------------------------------------------------------------------------------------
def test_digests_present_and_no_raw_text_anywhere_in_the_output_file(adk, tmp_path):
    def leaky(path: str, content: str) -> str:
        """Returns a canary in its result."""
        return CANARY_RESULT

    r = traced(adk, tmp_path, [calls(adk, ("leaky", {"path": f"/p/{CANARY_ARG}", "content": CANARY_ARG}, "c1")), text(adk, f"answer {CANARY_MODEL}")],
               tools=[adk.tools.FunctionTool(leaky)], message=f"please {CANARY_USER}", instruction=f"system {CANARY_SYSTEM}")
    blob = r.path.read_text()
    for c in ALL_CANARIES + (SALT.decode(),):
        assert c not in blob, c
    req, ex = by(r.events, "tool.call.requested")[0], by(r.events, "tool.call.executed")[0]
    assert req.args.mode == "digest" and len(req.args.digest) == 16 and req.args.keys == ["content", "path"] and req.args.size > 0
    assert ex.result.mode == "digest" and len(ex.result.digest) == 16 and ex.result.type in ("str", "dict") and ex.result.size > 0
    assert req.args.salt_id and req.args.salt_id == r.events[0].salt_id


def test_full_capture_keeps_text_only_in_the_capture_file(adk, tmp_path):
    from safelabs_trace.adk_handler import adk_tools
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "traces" / "run.jsonl", capture="full", salt=SALT, capture_dir=tmp_path / "captures")
    h = ADKTraceHandler(w)
    run_agent(adk, make_agent(adk, [calls(adk, ("fs_write_file", {"path": "/p", "content": CANARY_ARG}, "c1")), text(adk, "done")], tools=adk_tools(kit)), plugin_handler=h)
    w.close()
    assert CANARY_ARG not in (tmp_path / "traces" / "run.jsonl").read_text() and CANARY_ARG in (tmp_path / "captures" / "run.full.jsonl").read_text()


# ---- robustness --------------------------------------------------------------------------------------------------
def test_a_handler_exception_never_breaks_the_run(adk, tmp_path):
    class Broken(TraceWriter):
        def write(self, event):
            raise OSError("disk full")

    from safelabs_trace.adk_handler import adk_tools
    kit = InertToolKit()
    w = Broken(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    out, _ = run_agent(adk, make_agent(adk, [calls(adk, ("lookup_order", {"order_id": "o"}, "c1")), text(adk, "all done")], tools=adk_tools(kit)), plugin_handler=h)
    assert out == "all done" and len(kit.calls) == 1
    assert h.errors and all("OSError" in e for e in h.errors[:3])


def test_handler_methods_tolerate_odd_inputs_without_raising():
    class Boom(TraceWriter):
        pass

    h = ADKTraceHandler(Boom.__new__(Boom))  # a writer that was never initialised: every write fails
    ctx = SimpleNamespace(invocation_id="i1", session=SimpleNamespace(id="s1"))

    async def go():
        await h.before_run_callback(invocation_context=ctx)
        await h.before_agent_callback(agent=SimpleNamespace(name="a"), callback_context=ctx)
        await h.before_model_callback(callback_context=ctx, llm_request=object())
        await h.after_model_callback(callback_context=ctx, llm_response=object())
        await h.before_tool_callback(tool=object(), tool_args=None, tool_context=ctx)
        await h.after_tool_callback(tool=object(), tool_args=None, tool_context=ctx, result=None)
        await h.after_agent_callback(agent=SimpleNamespace(name="a"), callback_context=ctx)
        await h.after_run_callback(invocation_context=ctx)
        await h.on_run_error_callback(invocation_context=ctx, error=RuntimeError("x"))

    asyncio.run(go())
    assert h.errors  # recorded, never raised


def test_callbacks_return_none_so_nothing_is_short_circuited(adk, tmp_path):
    clean = make_agent(adk, [calls(adk, ("lookup_order", {"order_id": "o"}, "c1")), text(adk, "same answer")], tools=__import__("safelabs_trace.adk_handler", fromlist=["x"]).adk_tools(InertToolKit()))
    plain, _ = run_agent(adk, clean)
    r = traced(adk, tmp_path, [calls(adk, ("lookup_order", {"order_id": "o"}, "c1")), text(adk, "same answer")])
    assert plain == r.out == "same answer"
    h = ADKTraceHandler(TraceWriter(tmp_path / "x.jsonl", salt=SALT))
    ctx = SimpleNamespace(invocation_id="i", session=SimpleNamespace(id="s"))

    async def go():
        return [await h.before_run_callback(invocation_context=ctx), await h.before_agent_callback(agent=SimpleNamespace(name="a"), callback_context=ctx),
                await h.before_model_callback(callback_context=ctx, llm_request=SimpleNamespace(model="m", config=None, tools_dict={})),
                await h.after_model_callback(callback_context=ctx, llm_response=SimpleNamespace(partial=None)),
                await h.before_tool_callback(tool=SimpleNamespace(name="t"), tool_args={}, tool_context=ctx),
                await h.after_tool_callback(tool=SimpleNamespace(name="t"), tool_args={}, tool_context=ctx, result={}),
                await h.after_agent_callback(agent=SimpleNamespace(name="a"), callback_context=ctx), await h.after_run_callback(invocation_context=ctx)]

    assert asyncio.run(go()) == [None] * 8


def test_the_output_file_validates_against_the_schema_and_is_consistent(adk, tmp_path):
    r = traced(adk, tmp_path, [calls(adk, ("lookup_order", {"order_id": "o"}, "c1"), ("send_email", {"to": "a@example.test", "subject": "s", "body": "b"}, "c2")),
                               text(adk, "done", usage=usage(adk, 3, 1))])
    lines = r.path.read_text().splitlines()
    assert len(lines) == len(r.events)
    assert [e.seq for e in r.events] == list(range(len(r.events))) and len({e.trace_id for e in r.events}) == 1
    ids = {e.event_id: e for e in r.events}
    assert all(e.parent_event_id is None or e.parent_event_id in ids for e in r.events)
    assert all(json.loads(l)["schema"] == "safelabs-trace/0.1" for l in lines)
    assert all(e.prov for e in r.events if e.type in ("model.call.start", "model.call.end", "tool.call.requested", "tool.call.executed"))
    assert not r.handler.errors


def test_partial_streamed_responses_are_not_model_call_ends(adk, tmp_path):
    h = ADKTraceHandler(TraceWriter(tmp_path / "x.jsonl", salt=SALT))
    ctx = SimpleNamespace(invocation_id="i", session=SimpleNamespace(id="s"))

    async def go():
        await h.before_run_callback(invocation_context=ctx)
        await h.before_agent_callback(agent=SimpleNamespace(name="a"), callback_context=ctx)
        await h.before_model_callback(callback_context=ctx, llm_request=SimpleNamespace(model="m", config=None, tools_dict={}))
        await h.after_model_callback(callback_context=ctx, llm_response=SimpleNamespace(partial=True, content=None, usage_metadata=None, finish_reason=None))
        await h.after_model_callback(callback_context=ctx, llm_response=SimpleNamespace(partial=False, content=None, usage_metadata=None, finish_reason=None, model_version="mv", error_code=None))

    asyncio.run(go())
    h.writer.close()
    ev = list(read_trace(tmp_path / "x.jsonl"))
    assert types_of(ev).count("model.call.end") == 1 and by(ev, "model.call.end")[0].model_returned == "mv"


def test_an_error_response_from_the_model_is_recorded_as_error_type(adk, tmp_path):
    r = traced(adk, tmp_path, [adk.LlmResponse(error_code="SAFETY", error_message="blocked")])
    end = by(r.events, "model.call.end")[0]
    assert end.error_type == "SAFETY" and end.prov["error_type"] == "verified" and by(r.events, "session.end")[0].reason == "completed"
    assert "blocked" not in r.path.read_text()  # the message text is not stored


def test_model_error_hook_closes_the_call_with_the_exception_type(tmp_path):
    h = ADKTraceHandler(TraceWriter(tmp_path / "x.jsonl", salt=SALT))
    ctx = SimpleNamespace(invocation_id="i", session=SimpleNamespace(id="s"))

    async def go():
        await h.before_run_callback(invocation_context=ctx)
        await h.before_agent_callback(agent=SimpleNamespace(name="a"), callback_context=ctx)
        await h.before_model_callback(callback_context=ctx, llm_request=SimpleNamespace(model="m", config=None, tools_dict={}))
        await h.on_model_error_callback(callback_context=ctx, llm_request=None, error=TimeoutError("t"))

    asyncio.run(go())
    ev = list(read_trace(tmp_path / "x.jsonl"))
    assert by(ev, "model.call.end")[0].error_type == "TimeoutError" and not h.errors


def test_nested_agents_get_their_own_start_and_end_but_one_stop(adk, tmp_path):
    from safelabs_trace.adk_handler import as_plugin
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    a = make_agent(adk, [text(adk, "first")], name="child_a")
    b = make_agent(adk, [text(adk, "second")], name="child_b")
    root = adk.agents.SequentialAgent(name="root", sub_agents=[a, b])
    run_agent(adk, root, plugin_handler=h)
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    starts = by(ev, "agent.start")
    assert [s.agent.name for s in starts] == ["root", "child_a", "child_b"]
    assert starts[0].parent_event_id == by(ev, "session.start")[0].event_id and starts[1].parent_event_id == starts[0].event_id
    assert [s.parent_agent_id for s in starts] == [None, "root", "root"] and starts[1].prov["parent_agent_id"] == "verified"
    assert [e.agent.name for e in by(ev, "agent.end")] == ["child_a", "child_b", "root"] and len(by(ev, "stop")) == 1
    assert by(ev, "stop")[0].parent_event_id == starts[0].event_id and not h.errors


# ---- fallback: per-agent callbacks (surface b) ----------------------------------------------------------------------
def test_fallback_per_agent_callbacks_give_the_same_event_order(adk, tmp_path):
    from safelabs_trace.adk_handler import adk_tools, attach_to_agent
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    agent = make_agent(adk, [calls(adk, ("fs_delete_file", {"path": f"/x/{CANARY_ARG}"}, "c1")), text(adk, "done", usage=usage(adk, 5, 2))], tools=adk_tools(kit))
    attach_to_agent(agent, h)
    out, _ = run_agent(adk, agent)  # no plugin
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    assert out == "done" and not h.errors
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "tool.call.requested", "tool.call.executed",
                            "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    assert ev[0].coverage == COVERAGE_AGENT_CALLBACKS and ev[0].coverage["session.start"] == "partial" and by(ev, "session.start")[0].prov["session_id"] == "verified"
    assert by(ev, "tool.call.requested")[0].severity == "irreversible" and by(ev, "model.call.end")[1].usage.input_tokens == 5
    assert CANARY_ARG not in (tmp_path / "run.jsonl").read_text()


def test_fallback_keeps_existing_callbacks_and_can_be_detached(adk, tmp_path):
    from safelabs_trace.adk_handler import attach_to_agent
    seen = []

    def mine(callback_context, llm_request):
        seen.append("mine")
        return None

    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    agent = make_agent(adk, [text(adk, "x"), text(adk, "y")], before_model_callback=mine)
    detach = attach_to_agent(agent, h)
    assert isinstance(agent.before_model_callback, list) and agent.before_model_callback[-1] is mine
    run_agent(adk, agent)
    assert seen == ["mine"] and "model.call.start" in {e.type for e in read_trace(tmp_path / "run.jsonl")}
    detach()
    assert agent.before_model_callback is mine and agent.before_agent_callback is None


def test_fallback_after_a_failed_run_needs_close_open_traces(adk, tmp_path):
    from safelabs_trace.adk_handler import attach_to_agent

    def broken(order_id: str) -> str:
        """Fails."""
        raise ValueError("synthetic")

    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    agent = make_agent(adk, [calls(adk, ("broken", {"order_id": "o"}, "c1")), text(adk, "never")], tools=[adk.tools.FunctionTool(broken)])
    attach_to_agent(agent, h)
    with pytest.raises(ValueError):
        run_agent(adk, agent)
    before = list(read_trace(tmp_path / "run.jsonl"))
    assert by(before, "tool.call.executed")[0].status == "error"  # the per-agent tool error callback is installed
    assert "session.end" not in types_of(before) and "agent.end" not in types_of(before)  # no run-level or agent-error hook on this path
    h.close_open_traces(ValueError("synthetic"))
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    assert types_of(ev)[-2:] == ["agent.end", "session.end"] and by(ev, "session.end")[0].reason == "error" and by(ev, "agent.end")[0].outcome == "error"


# ---- hygiene -----------------------------------------------------------------------------------------------------
def test_importing_the_handler_module_does_not_import_adk():
    code = ("import sys, safelabs_trace, safelabs_trace.adk_handler; bad=[m for m in ('google.adk','google.genai') if m in sys.modules]; assert not bad, bad;"
            "import safelabs_trace.langchain_handler" if False else "import sys, safelabs_trace.adk_handler as m; assert 'google.adk' not in sys.modules, 'adk imported'; assert m.ADKTraceHandler")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr


def test_the_core_package_does_not_import_the_adk_handler():
    code = "import sys, safelabs_trace; assert 'safelabs_trace.adk_handler' not in sys.modules; assert 'google.adk' not in sys.modules"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env).returncode == 0


def test_the_handler_configures_no_exporter_or_tracer_provider():
    src = (Path(__file__).resolve().parents[1] / "src" / "safelabs_trace" / "adk_handler.py").read_text()
    for banned in ("set_tracer_provider", "set_meter_provider", "BatchSpanProcessor", "SimpleSpanProcessor", "OTLP", "maybe_set_otel_providers", "get_gcp_exporters",
                   "TracerProvider("):
        assert banned not in src.split('"""', 2)[2], banned


def test_installed_adk_plugin_signatures_still_match(adk):
    import inspect
    from google.adk.plugins.base_plugin import BasePlugin
    expect = {"before_run_callback": {"invocation_context"}, "after_run_callback": {"invocation_context"}, "on_run_error_callback": {"invocation_context", "error"},
              "before_agent_callback": {"agent", "callback_context"}, "after_agent_callback": {"agent", "callback_context"},
              "on_agent_error_callback": {"agent", "callback_context", "error"}, "before_model_callback": {"callback_context", "llm_request"},
              "after_model_callback": {"callback_context", "llm_response"}, "on_model_error_callback": {"callback_context", "llm_request", "error"},
              "before_tool_callback": {"tool", "tool_args", "tool_context"}, "after_tool_callback": {"tool", "tool_args", "tool_context", "result"},
              "on_tool_error_callback": {"tool", "tool_args", "tool_context", "error"}}
    for name, params in expect.items():
        assert params <= set(inspect.signature(getattr(BasePlugin, name)).parameters), name
