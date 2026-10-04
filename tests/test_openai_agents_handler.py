"""OpenAI Agents SDK trace handler tests. Offline: a fake Model, inert tools, no API key, sockets to the outside blocked, and the SDK's backend
exporter patched to fail loudly if it is ever called. Strings are synthetic and non-harmful. Skipped cleanly when ``agents`` is absent."""

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

from safelabs_trace.inert_tools import InertToolKit
from safelabs_trace.openai_agents_handler import (
    COVERAGE, OpenAIAgentsTraceHandler, OpenAIExportActiveError, _ERROR_PREFIXES, ensure_openai_export_off, export_status, safe_run_config,
)
from safelabs_trace.schema import EVENT_TYPES
from safelabs_trace.writer import TraceWriter, read_trace
from tests.helpers import SALT

CANARY_ARG = "CANARY-OA-ARGUMENT-7311"
CANARY_USER = "CANARY-OA-USER-MESSAGE-5522"
CANARY_MODEL = "CANARY-OA-MODEL-TEXT-8844"
CANARY_RESULT = "CANARY-OA-TOOL-RESULT-9966"
CANARY_SYSTEM = "CANARY-OA-INSTRUCTIONS-1288"
ALL_CANARIES = (CANARY_ARG, CANARY_USER, CANARY_MODEL, CANARY_RESULT, CANARY_SYSTEM)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No internet sockets (AF_UNIX stays for asyncio), no API key in the environment."""
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
    for var in ("OPENAI_API_KEY", "OPENAI_AGENTS_DISABLE_TRACING"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sdk(monkeypatch):
    pytest.importorskip("agents")
    pytest.importorskip("openai")
    import agents
    from agents.models.interface import Model
    from agents.items import ModelResponse
    from agents.tracing import processors, provider as provider_mod, setup
    from agents.usage import Usage
    from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

    uploads = []

    def exploding_export(self, items):
        uploads.append(len(items))
        raise AssertionError("BackendSpanExporter.export was called: a trace would have been uploaded")

    monkeypatch.setattr(processors.BackendSpanExporter, "export", exploding_export)
    monkeypatch.setattr(processors, "_global_exporter", None)
    monkeypatch.setattr(processors, "_global_processor", None)
    monkeypatch.setattr(setup, "GLOBAL_TRACE_PROVIDER", None)  # restored after the test, so no state leaks between tests
    ns = SimpleNamespace(agents=agents, Model=Model, ModelResponse=ModelResponse, Usage=Usage, processors=processors, provider=provider_mod, setup=setup,
                         uploads=uploads, Call=ResponseFunctionToolCall, Msg=ResponseOutputMessage, Text=ResponseOutputText)

    class FakeModel(Model):
        model = "fake-model"

        def __init__(self, script):
            self.it, self.calls = iter(script), 0

        async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, *, previous_response_id, conversation_id, prompt):
            self.calls += 1
            return next(self.it)

        def stream_response(self, *a, **k):
            raise NotImplementedError

    ns.FakeModel = FakeModel
    yield ns
    assert uploads == [], "the OpenAI exporter was asked to upload"


def msg(sdk, text, *, inp=5, out=2, reasoning=0, status="completed"):
    item = sdk.Msg(id="m1", role="assistant", status=status, type="message", content=[sdk.Text(text=text, annotations=[], type="output_text")])
    usage = sdk.Usage(requests=1, input_tokens=inp, output_tokens=out)
    if reasoning:
        from openai.types.responses.response_usage import OutputTokensDetails
        usage.output_tokens_details = OutputTokensDetails(reasoning_tokens=reasoning)
    return sdk.ModelResponse(output=[item], usage=usage, response_id=None)


def calls(sdk, *specs, inp=5, out=2):
    """specs: (name, args dict, call id)."""
    items = [sdk.Call(arguments=json.dumps(a), call_id=cid, name=n, type="function_call", id="fc_" + cid, status="completed") for n, a, cid in specs]
    return sdk.ModelResponse(output=items, usage=sdk.Usage(requests=1, input_tokens=inp, output_tokens=out), response_id=None)


@pytest.fixture
def export_off(sdk):
    ensure_openai_export_off()  # inside the monkeypatched global state
    return sdk


def make(sdk, script, *, tools=None, name="agent", instructions="be helpful", handoffs=None):
    from safelabs_trace.openai_agents_handler import openai_agents_tools
    model = sdk.FakeModel(script)
    agent = sdk.agents.Agent(name=name, instructions=instructions, model=model, tools=tools if tools is not None else [], handoffs=handoffs or [])
    return agent, model


def run(sdk, agent, handler, message="hello", **kw):
    from safelabs_trace.openai_agents_handler import run_traced
    return asyncio.run(run_traced(handler, agent, message, **kw))


def traced(sdk, tmp_path, script, *, tools="kit", kit=None, handler_kw=None, message="hello", **agent_kw):
    from safelabs_trace.openai_agents_handler import openai_agents_tools
    kit = kit or InertToolKit()
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w, **(handler_kw or {}))
    agent, model = make(sdk, script, tools=openai_agents_tools(kit) if tools == "kit" else tools, **agent_kw)
    result = run(sdk, agent, h, message)
    w.close()
    return SimpleNamespace(events=list(read_trace(tmp_path / "run.jsonl")), result=result, kit=kit, handler=h, path=tmp_path / "run.jsonl", model=model, agent=agent)


def types_of(ev):
    return [e.type for e in ev]


def by(ev, t):
    return [e for e in ev if e.type == t]


# ---- event order -------------------------------------------------------------------------------------------------
def test_no_tool_turn_event_order_and_fields(export_off, tmp_path):
    sdk = export_off
    r = traced(sdk, tmp_path, [msg(sdk, "plain answer", inp=11, out=4, reasoning=2)], tools=[], handler_kw={"trial": {"prompt_id": "P-1", "seed": 3}})
    ev = r.events
    assert r.result.final_output == "plain answer"
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    h = ev[0]
    assert h.framework == "openai-agents" and h.framework_version and h.coverage == COVERAGE and set(h.coverage) == set(EVENT_TYPES) and h.adapter == "openai_agents_handler"
    ss = by(ev, "session.start")[0]
    assert ss.trial == {"prompt_id": "P-1", "seed": 3} and ss.prov["session_id"] == "inferred" and ss.session_id == ev[1].trace_id
    start, end = by(ev, "model.call.start")[0], by(ev, "model.call.end")[0]
    assert start.model_requested == "fake-model" and start.prov["model_requested"] == "inferred" and start.tools_offered == [] and start.provider is None
    assert end.usage.input_tokens == 11 and end.usage.output_tokens == 4 and end.usage.reasoning_tokens == 2
    assert end.finish_reason_raw is None and end.model_returned is None and end.prov["finish_reason_raw"] == "unknown"  # not exposed by the SDK
    assert end.tool_calls_requested_count == 0 and end.call_id == start.call_id and end.parent_event_id == start.event_id
    stop = by(ev, "stop")[0]
    assert stop.stop_raw == "completed" and stop.stop_status == "end_of_turn" and stop.prov["stop_raw"] == "inferred" and stop.source_event_id == end.event_id
    assert by(ev, "agent.end")[0].outcome == "completed" and by(ev, "session.end")[0].reason == "completed" and not r.handler.errors


def test_single_tool_call_links_severity_and_ids(export_off, tmp_path):
    sdk = export_off
    r = traced(sdk, tmp_path, [calls(sdk, ("lookup_order", {"order_id": "o1"}, "c1")), msg(sdk, "done")])
    ev = r.events
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "tool.call.requested", "tool.call.executed",
                            "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    mend = by(ev, "model.call.end")[0]
    req, ex = by(ev, "tool.call.requested")[0], by(ev, "tool.call.executed")[0]
    assert mend.tool_calls_requested_count == 1
    assert req.parent_event_id == mend.event_id and req.model_call_id == mend.call_id and req.observed_at == "model_output"
    assert req.tool_call_id == "c1" == ex.tool_call_id and ex.requested_event_id == req.event_id and ex.parent_event_id == req.event_id
    assert (req.severity, req.severity_basis) == ("read_only", "name_rule") == (ex.severity, ex.severity_basis)
    assert ex.status == "success" and ex.result.mode == "digest" and ex.duration_ms is not None and ex.tool_name == "lookup_order"
    assert [c["tool"] for c in r.kit.calls] == ["lookup_order"] and r.result.final_output == "done" and r.model.calls == 2
    assert by(ev, "model.call.start")[0].tools_offered == sorted(r.kit.names())


def test_several_tool_calls_in_one_turn_are_matched_by_call_id(export_off, tmp_path):
    sdk = export_off
    r = traced(sdk, tmp_path, [calls(sdk, ("lookup_order", {"order_id": "a"}, "c1"), ("fs_delete_file", {"path": "/x"}, "c2"), ("lookup_order", {"order_id": "b"}, "c3"),
                                     ("fs_write_file", {"path": "/y", "content": "z"}, "c4")), msg(sdk, "done")])
    ev = r.events
    reqs, exs = by(ev, "tool.call.requested"), by(ev, "tool.call.executed")
    assert len(reqs) == len(exs) == 4 and by(ev, "model.call.end")[0].tool_calls_requested_count == 4
    assert {x.tool_call_id for x in exs} == {"c1", "c2", "c3", "c4"} and {x.requested_event_id for x in exs} == {q.event_id for q in reqs}
    for x in exs:
        q = next(q for q in reqs if q.event_id == x.requested_event_id)
        assert q.tool_call_id == x.tool_call_id and q.tool.name == x.tool_name and ev.index(q) < ev.index(x)
    assert {x.tool_name: x.severity for x in exs} == {"lookup_order": "read_only", "fs_delete_file": "irreversible", "fs_write_file": "state_changing"}
    assert sorted(c["arguments"].get("order_id", "-") for c in r.kit.calls if c["tool"] == "lookup_order") == ["a", "b"]


def test_a_tool_error_returned_by_the_sdk_as_a_result_is_marked_error(export_off, tmp_path):
    sdk = export_off

    @sdk.agents.function_tool
    def broken(order_id: str) -> str:
        """A tool that fails."""
        raise ValueError("synthetic tool failure")

    r = traced(sdk, tmp_path, [calls(sdk, ("broken", {"order_id": "o"}, "c1")), msg(sdk, "recovered")], tools=[broken])
    ex = by(r.events, "tool.call.executed")[0]
    assert r.result.final_output == "recovered"  # the SDK absorbed the failure and the run went on
    assert ex.status == "error" and ex.tool_call_id == "c1" and ex.result.mode == "digest" and ex.error_type is None  # the exception type is not visible to hooks
    assert "synthetic tool failure" not in r.path.read_text()


def test_a_tool_whose_failure_propagates_is_closed_as_an_error(export_off, tmp_path):
    sdk = export_off

    @sdk.agents.function_tool(failure_error_function=None)
    def broken(order_id: str) -> str:
        """A tool that fails and raises."""
        raise ValueError("synthetic tool failure")

    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    agent, _ = make(sdk, [calls(sdk, ("broken", {"order_id": "o"}, "c1")), msg(sdk, "never")], tools=[broken])
    with pytest.raises(Exception) as info:
        run(sdk, agent, h)
    assert "synthetic tool failure" in str(info.value) or "synthetic tool failure" in repr(info.value.__cause__)
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    ex = by(ev, "tool.call.executed")[0]
    assert ex.status == "error" and ex.tool_call_id == "c1" and ex.error_type == type(info.value).__name__ and ex.result is None
    assert types_of(ev)[-3:] == ["stop", "agent.end", "session.end"] and by(ev, "agent.end")[0].outcome == "error" and by(ev, "session.end")[0].reason == "error"
    assert not h.errors


def test_unknown_tool_defaults_to_state_changing_with_basis_recorded(export_off, tmp_path):
    sdk = export_off

    @sdk.agents.function_tool
    def frobnicate(thing: str) -> str:
        """An unknown kind of tool."""
        return "ok"

    r = traced(sdk, tmp_path, [calls(sdk, ("frobnicate", {"thing": "t"}, "c1")), msg(sdk, "done")], tools=[frobnicate])
    req, ex = by(r.events, "tool.call.requested")[0], by(r.events, "tool.call.executed")[0]
    assert (req.severity, req.severity_basis, req.rule_ids[0]) == ("state_changing", "default_unknown", "DEFAULT-UNKNOWN") and ex.severity == "state_changing"
    (tmp_path / "s").mkdir()
    sens = traced(sdk, tmp_path / "s", [calls(sdk, ("frobnicate", {"thing": "t"}, "c1")), msg(sdk, "done")], tools=[frobnicate], handler_kw={"unknown_default": "read_only"})
    assert by(sens.events, "tool.call.requested")[0].severity == "read_only"


def test_an_irreversible_tool_is_tagged_irreversible(export_off, tmp_path):
    sdk = export_off
    r = traced(sdk, tmp_path, [calls(sdk, ("fs_delete_file", {"path": "/data/x"}, "c1")), msg(sdk, "done")])
    req = by(r.events, "tool.call.requested")[0]
    assert (req.severity, req.severity_basis, req.capability_hint) == ("irreversible", "name_rule", "filesystem.delete") and by(r.events, "tool.call.executed")[0].severity == "irreversible"


def test_declared_hints_can_raise(export_off, tmp_path):
    sdk = export_off

    @sdk.agents.function_tool
    def get_report(q: str) -> str:
        """Fetch a report."""
        return "r"

    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    h.declare("get_report", {"destructiveHint": True})
    agent, _ = make(sdk, [calls(sdk, ("get_report", {"q": "x"}, "c1")), msg(sdk, "done")], tools=[get_report])
    run(sdk, agent, h)
    w.close()
    req = by(list(read_trace(tmp_path / "run.jsonl")), "tool.call.requested")[0]
    assert (req.severity, req.severity_basis) == ("irreversible", "declared") and req.tool.declared == {"destructiveHint": True}


# ---- handoffs ----------------------------------------------------------------------------------------------------
def test_a_handoff_ends_the_sender_with_outcome_handoff_and_starts_the_receiver_with_its_parent(export_off, tmp_path):
    sdk = export_off
    b, _ = make(sdk, [msg(sdk, "from b")], name="agent_b")
    a, _ = make(sdk, [calls(sdk, ("transfer_to_agent_b", {}, "h1"))], name="agent_a", handoffs=[b])
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    r = run(sdk, a, h)
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    assert r.final_output == "from b" and not h.errors
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "agent.end", "agent.start", "model.call.start",
                            "model.call.end", "stop", "agent.end", "session.end"]
    starts, ends = by(ev, "agent.start"), by(ev, "agent.end")
    assert [s.agent.name for s in starts] == ["agent_a", "agent_b"] and [e.outcome for e in ends] == ["handoff", "completed"]
    assert starts[1].parent_agent_id == "agent_a" and starts[1].parent_event_id == starts[0].event_id and starts[1].prov["parent_agent_id"] == "verified"
    assert by(ev, "tool.call.requested") == [] and by(ev, "model.call.end")[0].tool_calls_requested_count == 0  # the handoff call is not a tool call
    assert len(by(ev, "stop")) == 1 and by(ev, "stop")[0].parent_event_id == starts[1].event_id


# ---- privacy -----------------------------------------------------------------------------------------------------
def test_digests_present_and_no_raw_text_anywhere_in_the_output_file(export_off, tmp_path):
    sdk = export_off

    @sdk.agents.function_tool
    def leaky(path: str, content: str) -> str:
        """Returns a canary in its result."""
        return CANARY_RESULT

    r = traced(sdk, tmp_path, [calls(sdk, ("leaky", {"path": f"/p/{CANARY_ARG}", "content": CANARY_ARG}, "c1")), msg(sdk, f"answer {CANARY_MODEL}")],
               tools=[leaky], message=f"please {CANARY_USER}", instructions=f"system {CANARY_SYSTEM}")
    blob = r.path.read_text()
    for c in ALL_CANARIES + (SALT.decode(),):
        assert c not in blob, c
    req, ex = by(r.events, "tool.call.requested")[0], by(r.events, "tool.call.executed")[0]
    assert req.args.mode == "digest" and len(req.args.digest) == 16 and req.args.keys == ["content", "path"] and req.args.size > 0
    assert ex.result.mode == "digest" and len(ex.result.digest) == 16 and ex.result.size > 0 and req.args.salt_id == r.events[0].salt_id


def test_full_capture_keeps_text_only_in_the_capture_file(export_off, tmp_path):
    sdk = export_off
    from safelabs_trace.openai_agents_handler import openai_agents_tools
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "traces" / "run.jsonl", capture="full", salt=SALT, capture_dir=tmp_path / "captures")
    h = OpenAIAgentsTraceHandler(w)
    agent, _ = make(sdk, [calls(sdk, ("fs_write_file", {"path": "/p", "content": CANARY_ARG}, "c1")), msg(sdk, "done")], tools=openai_agents_tools(kit))
    run(sdk, agent, h)
    w.close()
    assert CANARY_ARG not in (tmp_path / "traces" / "run.jsonl").read_text() and CANARY_ARG in (tmp_path / "captures" / "run.full.jsonl").read_text()


# ---- robustness --------------------------------------------------------------------------------------------------
def test_a_handler_exception_never_breaks_the_run(export_off, tmp_path):
    sdk = export_off
    from safelabs_trace.openai_agents_handler import openai_agents_tools

    class Broken(TraceWriter):
        def write(self, event):
            raise OSError("disk full")

    kit = InertToolKit()
    w = Broken(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    agent, _ = make(sdk, [calls(sdk, ("lookup_order", {"order_id": "o"}, "c1")), msg(sdk, "all done")], tools=openai_agents_tools(kit))
    r = run(sdk, agent, h)
    assert r.final_output == "all done" and len(kit.calls) == 1 and h.errors and all("OSError" in e for e in h.errors[:3])


def test_the_output_file_validates_against_the_schema_and_is_consistent(export_off, tmp_path):
    sdk = export_off
    r = traced(sdk, tmp_path, [calls(sdk, ("lookup_order", {"order_id": "o"}, "c1"), ("send_email", {"to": "a@example.test", "subject": "s", "body": "b"}, "c2")), msg(sdk, "done")])
    lines = r.path.read_text().splitlines()
    assert len(lines) == len(r.events)
    assert [e.seq for e in r.events] == list(range(len(r.events))) and len({e.trace_id for e in r.events}) == 1
    ids = {e.event_id for e in r.events}
    assert all(e.parent_event_id is None or e.parent_event_id in ids for e in r.events)
    assert all(json.loads(l)["schema"] == "safelabs-trace/0.1" for l in lines) and not r.handler.errors


def test_two_concurrent_runs_with_one_handler_get_separate_traces(export_off, tmp_path):
    sdk = export_off
    from safelabs_trace.openai_agents_handler import openai_agents_tools, run_traced
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    kit = InertToolKit()
    a1, _ = make(sdk, [calls(sdk, ("lookup_order", {"order_id": "1"}, "x1")), msg(sdk, "one")], tools=openai_agents_tools(kit), name="a1")
    a2, _ = make(sdk, [calls(sdk, ("lookup_order", {"order_id": "2"}, "x2")), msg(sdk, "two")], tools=openai_agents_tools(kit), name="a2")

    async def both():
        return await asyncio.gather(run_traced(h, a1, "hi"), run_traced(h, a2, "hi"))

    r1, r2 = asyncio.run(both())
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    by_trace = {}
    for e in ev:
        by_trace.setdefault(e.trace_id, []).append(e)
    assert {r1.final_output, r2.final_output} == {"one", "two"} and len(by_trace) == 2
    for t in by_trace.values():
        assert types_of(t).count("tool.call.executed") == 1 and types_of(t)[-1] == "session.end"
    assert {by(t, "agent.start")[0].agent.name for t in by_trace.values()} == {"a1", "a2"}


def test_close_open_traces_closes_an_in_flight_tool_and_the_run():
    pytest.importorskip("agents")
    import tempfile
    d = Path(tempfile.mkdtemp())
    w = TraceWriter(d / "x.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w, strict=False)
    usage = object()
    ctx = SimpleNamespace(usage=usage)
    tctx = SimpleNamespace(usage=usage, tool_call_id="t1", tool_arguments='{"order_id": "o"}')

    async def go():
        await h.on_agent_start(ctx, SimpleNamespace(name="a"))
        await h.on_llm_start(ctx, SimpleNamespace(name="a", model="m", model_settings=None, tools=[]), None, [])
        await h.on_tool_start(tctx, SimpleNamespace(name="a"), SimpleNamespace(name="lookup_order"))  # started, never finished

    asyncio.run(go())
    h.close_open_traces(ValueError("synthetic"))
    w.close()
    ev = list(read_trace(d / "x.jsonl"))
    ex = by(ev, "tool.call.executed")[0]
    assert ex.status == "error" and ex.error_type == "ValueError" and by(ev, "tool.call.requested")[0].observed_at == "tool_start"
    assert types_of(ev)[-3:] == ["stop", "agent.end", "session.end"] and by(ev, "session.end")[0].reason == "error"


# ---- exporter safety ---------------------------------------------------------------------------------------------
def test_strict_mode_refuses_to_start_while_the_default_export_could_be_active(sdk, tmp_path):
    from safelabs_trace.openai_agents_handler import openai_agents_tools
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)  # strict by default; no provider exists, so the SDK would register the OpenAI exporter on first use
    assert export_status().active is True
    agent, model = make(sdk, [msg(sdk, "never")], tools=openai_agents_tools(kit))
    with pytest.raises(OpenAIExportActiveError, match="ensure_openai_export_off"):
        run(sdk, agent, h)
    w.close()
    assert model.calls == 0 and not tmp_path.joinpath("run.jsonl").exists()  # refused before any event and before any model call
    assert sdk.uploads == []


def test_non_strict_mode_warns_in_the_error_log_and_runs(sdk, tmp_path):
    r = traced(sdk, tmp_path, [msg(sdk, "ok")], tools=[], handler_kw={"strict": False})
    assert r.result.final_output == "ok" and types_of(r.events)[-1] == "session.end"
    assert any(e.startswith("WARNING: OpenAI trace export could be active") for e in r.handler.errors)
    assert not any(hasattr(e, "notes") for e in r.events)  # the header has no notes field, so nothing was added to the schema
    assert sdk.uploads == []


def test_ensure_openai_export_off_from_a_fresh_process(sdk):
    assert sdk.setup.GLOBAL_TRACE_PROVIDER is None and export_status().active
    status = ensure_openai_export_off()
    assert status.active is False and export_status().active is False
    p = sdk.setup.GLOBAL_TRACE_PROVIDER
    assert isinstance(p, sdk.provider.DefaultTraceProvider) and p._multi_processor._processors == () and p._disabled is True
    assert sdk.processors._global_exporter is None and sdk.processors._global_processor is None  # the default exporter object was never even created


def test_ensure_openai_export_off_removes_only_the_openai_exporter(sdk):
    from agents.tracing.processor_interface import TracingProcessor

    class Spy(TracingProcessor):
        def on_trace_start(self, trace): pass
        def on_trace_end(self, trace): pass
        def on_span_start(self, span): pass
        def on_span_end(self, span): pass
        def shutdown(self): pass
        def force_flush(self): pass

    provider = sdk.provider.DefaultTraceProvider()
    mine = Spy()
    provider.register_processor(sdk.processors.BatchTraceProcessor(sdk.processors.BackendSpanExporter()))
    provider.register_processor(mine)
    sdk.setup.GLOBAL_TRACE_PROVIDER = provider
    assert export_status().active is True and "BackendSpanExporter" in export_status().reasons[0]
    ensure_openai_export_off()
    assert export_status().active is False and provider._multi_processor._processors == (mine,) and provider._disabled is True


def test_the_env_flag_counts_as_off_when_no_provider_exists(sdk, monkeypatch):
    monkeypatch.setenv("OPENAI_AGENTS_DISABLE_TRACING", "true")
    st = export_status()
    assert st.active is False and "OPENAI_AGENTS_DISABLE_TRACING" in st.reasons[0]


def test_an_unknown_provider_or_unreadable_state_is_treated_as_active(sdk):
    sdk.setup.GLOBAL_TRACE_PROVIDER = object.__new__(type("Odd", (), {}))  # not a DefaultTraceProvider
    assert export_status().active is True
    p = sdk.provider.DefaultTraceProvider()
    p._multi_processor = None  # unreadable
    sdk.setup.GLOBAL_TRACE_PROVIDER = p
    assert export_status().active is True and "treated as active" in export_status().reasons[0]


def test_safe_run_config_really_disables_tracing_and_nothing_reaches_the_exporter(sdk, tmp_path):
    from agents.tracing.processor_interface import TracingProcessor
    from safelabs_trace.openai_agents_handler import openai_agents_tools

    seen = []

    class Spy(TracingProcessor):
        def on_trace_start(self, trace): seen.append("trace")
        def on_trace_end(self, trace): pass
        def on_span_start(self, span): seen.append("span")
        def on_span_end(self, span): pass
        def shutdown(self): pass
        def force_flush(self): pass

    provider = sdk.provider.DefaultTraceProvider()
    provider.register_processor(sdk.processors.BatchTraceProcessor(sdk.processors.BackendSpanExporter()))  # the real default uploader, still registered
    provider.register_processor(Spy())
    sdk.setup.GLOBAL_TRACE_PROVIDER = provider
    kit = InertToolKit()

    def go(config):
        w = TraceWriter(tmp_path / f"r{len(seen)}.jsonl", salt=SALT)
        h = OpenAIAgentsTraceHandler(w, strict=False)
        agent, _ = make(sdk, [calls(sdk, ("lookup_order", {"order_id": "o"}, "c1")), msg(sdk, "done")], tools=openai_agents_tools(kit))
        from safelabs_trace.openai_agents_handler import as_run_hooks
        asyncio.run(sdk.agents.Runner.run(agent, "hi", hooks=as_run_hooks(h), run_config=config))
        w.close()

    go(safe_run_config())
    assert seen == []  # no trace and no span was created, so no processor (the uploader included) saw anything
    go(sdk.agents.RunConfig(tracing_disabled=False))  # contrast: an ordinary config does create traces and spans
    assert "trace" in seen and "span" in seen
    provider.set_processors([])  # the uploader must not run at interpreter exit with queued items
    assert sdk.uploads == []


def test_safe_run_config_values_and_refusals(sdk):
    cfg = safe_run_config(workflow_name="private-run")
    assert cfg.tracing_disabled is True and cfg.trace_include_sensitive_data is False and cfg.tracing is None and cfg.workflow_name == "private-run"
    for bad in ({"tracing_disabled": False}, {"trace_include_sensitive_data": True}, {"tracing": {"api_key": "x"}}):
        with pytest.raises(ValueError):
            safe_run_config(**bad)
    assert safe_run_config(tracing_disabled=True, trace_include_sensitive_data=False).tracing_disabled is True


def test_the_env_default_for_sensitive_data_is_true_so_the_override_matters(sdk, monkeypatch):
    monkeypatch.setenv("OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA", "true")
    assert sdk.agents.RunConfig().trace_include_sensitive_data is True
    assert safe_run_config().trace_include_sensitive_data is False


# ---- SDK surface -------------------------------------------------------------------------------------------------
def test_the_sdk_accepts_only_a_runhooks_instance(export_off, tmp_path):
    sdk = export_off
    from safelabs_trace.openai_agents_handler import as_run_hooks
    h = OpenAIAgentsTraceHandler(TraceWriter(tmp_path / "x.jsonl", salt=SALT))
    from agents.lifecycle import RunHooksBase
    assert isinstance(as_run_hooks(h), RunHooksBase)  # RunHooks itself is a subscripted generic, which isinstance cannot check
    agent, _ = make(sdk, [msg(sdk, "x")])
    with pytest.raises(TypeError, match="RunHooks"):
        asyncio.run(sdk.agents.Runner.run(agent, "hi", hooks=h, run_config=safe_run_config()))


def test_the_per_agent_hooks_path_gives_the_same_events(export_off, tmp_path):
    sdk = export_off
    from safelabs_trace.openai_agents_handler import as_agent_hooks, openai_agents_tools
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    agent, _ = make(sdk, [calls(sdk, ("fs_delete_file", {"path": f"/x/{CANARY_ARG}"}, "c1")), msg(sdk, "done")], tools=openai_agents_tools(kit))
    agent.hooks = as_agent_hooks(h)
    r = asyncio.run(sdk.agents.Runner.run(agent, "hi", run_config=safe_run_config()))
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    assert r.final_output == "done" and not h.errors
    assert types_of(ev) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "tool.call.requested", "tool.call.executed",
                            "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    assert by(ev, "tool.call.requested")[0].severity == "irreversible" and CANARY_ARG not in (tmp_path / "run.jsonl").read_text()


def test_the_default_error_texts_the_handler_recognises_still_match_the_installed_sdk(sdk):
    from agents.tool import default_tool_error_function
    assert default_tool_error_function(None, ValueError("boom")).startswith(_ERROR_PREFIXES)
    assert _ERROR_PREFIXES[1].startswith("An error occurred while parsing tool arguments")  # the second text comes from the same function (tool.py:1611-1617)


def test_inert_tools_as_sdk_function_tools(sdk):
    from safelabs_trace.openai_agents_handler import openai_agents_tools
    kit = InertToolKit()
    tools = openai_agents_tools(kit)
    assert [t.name for t in tools] == kit.names() and all(isinstance(t, sdk.agents.FunctionTool) for t in tools)
    t = next(t for t in tools if t.name == "fs_write_file")
    assert t.params_json_schema == {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"],
                                    "additionalProperties": False} and t.strict_json_schema is True
    out = asyncio.run(t.on_invoke_tool(SimpleNamespace(), json.dumps({"path": "/a", "content": "b"})))
    assert out.startswith("inert:fs_write_file:ok:") and kit.calls[-1]["arguments"] == {"path": "/a", "content": "b"}


# ---- hygiene -----------------------------------------------------------------------------------------------------
def test_importing_the_handler_module_does_not_import_the_sdk():
    code = "import sys, safelabs_trace.openai_agents_handler as m; assert 'agents' not in sys.modules, 'agents imported'; assert m.OpenAIAgentsTraceHandler"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    code = "import sys, safelabs_trace; assert 'safelabs_trace.openai_agents_handler' not in sys.modules and 'agents' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env).returncode == 0


def test_the_handler_registers_no_exporter_reads_no_key_and_creates_no_default_uploader():
    src = (Path(__file__).resolve().parents[1] / "src" / "safelabs_trace" / "openai_agents_handler.py").read_text()
    body = src.split('"""', 2)[2]
    for banned in ("add_trace_processor", "BatchTraceProcessor(", "default_processor(", "default_exporter(", "set_tracing_export_api_key", "OPENAI_API_KEY", "ConsoleSpanExporter",
                   "trace_include_sensitive_data=True"):
        assert banned not in body, banned
    assert "os.environ.get(_DISABLE_ENV" in body and body.count("os.environ") == 1  # the only environment read is the tracing-disable flag


def test_installed_sdk_hook_signatures_still_match(sdk):
    import inspect
    from agents.lifecycle import AgentHooksBase, RunHooksBase
    run_expect = {"on_llm_start": ["context", "agent", "system_prompt", "input_items"], "on_llm_end": ["context", "agent", "response"], "on_agent_start": ["context", "agent"],
                  "on_agent_end": ["context", "agent", "output"], "on_handoff": ["context", "from_agent", "to_agent"], "on_tool_start": ["context", "agent", "tool"],
                  "on_tool_end": ["context", "agent", "tool", "result"]}
    for name, params in run_expect.items():
        assert list(inspect.signature(getattr(RunHooksBase, name)).parameters)[1:] == params, name
    agent_expect = {"on_start": ["context", "agent"], "on_end": ["context", "agent", "output"], "on_handoff": ["context", "agent", "source"]}
    for name, params in agent_expect.items():
        assert list(inspect.signature(getattr(AgentHooksBase, name)).parameters)[1:] == params, name
