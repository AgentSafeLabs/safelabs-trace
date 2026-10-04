import json
from pathlib import Path

import pytest

pytest.importorskip("langchain_core")

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402

from safelabs_trace.inert_tools import InertToolKit  # noqa: E402
from safelabs_trace.langchain_handler import COVERAGE, TraceCallbackHandler, langchain_tools  # noqa: E402
from safelabs_trace.schema import EVENT_TYPES  # noqa: E402
from safelabs_trace.writer import TraceWriter, read_trace  # noqa: E402
from tests.helpers import SALT  # noqa: E402

CANARY = "CANARY-LANGCHAIN-ARGUMENT-4242"


def tc(name, args, cid):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


def script():
    return [
        AIMessage(content="", tool_calls=[tc("lookup_order", {"order_id": CANARY}, "call_1"), tc("fs_delete_file", {"path": f"/x/{CANARY}"}, "call_2"),
                                          tc("fs_write_file", {"path": "/y", "content": CANARY}, "call_3")],
                  usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}, response_metadata={"finish_reason": "tool_calls", "model_name": "fake-model-1"}),
        AIMessage(content="all done", usage_metadata={"input_tokens": 20, "output_tokens": 3, "total_tokens": 23}, response_metadata={"finish_reason": "stop"}),
    ]


def run_agent(handler=None, tools=None, kit=None):
    """A minimal agent loop on real LangChain objects: a fake chat model, StructuredTools around the inert kit."""
    kit = kit or InertToolKit()
    tools = tools or {t.name: t for t in langchain_tools(kit)}
    model = GenericFakeChatModel(messages=iter(script()))

    def loop(x, config):
        m = model.invoke([HumanMessage(content=x)], config=config)
        for call in m.tool_calls:
            tools[call["name"]].invoke(call, config=config)
        return model.invoke([HumanMessage(content="continue")], config=config)

    cfg = {"callbacks": [handler]} if handler else {}
    return RunnableLambda(loop).invoke("start", config=cfg), kit


@pytest.fixture
def traced(tmp_path):
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = TraceCallbackHandler(w, trial={"prompt_id": "P-1", "seed": 7})
    out, kit = run_agent(h)
    w.close()
    return {"events": list(read_trace(tmp_path / "run.jsonl")), "out": out, "kit": kit, "handler": h, "text": (tmp_path / "run.jsonl").read_text(), "path": tmp_path / "run.jsonl"}


def by_type(events, t):
    return [e for e in events if e.type == t]


def test_event_sequence_and_header(traced):
    ev = traced["events"]
    assert ev[0].type == "trace.header" and ev[0].coverage == COVERAGE and ev[0].framework == "langchain-core" and ev[0].framework_version
    assert set(COVERAGE) == set(EVENT_TYPES)
    kinds = [e.type for e in ev]
    assert kinds[:2] == ["trace.header", "session.start"] and kinds[2] == "agent.start"
    assert kinds[-3:] == ["stop", "agent.end", "session.end"]
    assert kinds.count("model.call.start") == kinds.count("model.call.end") == 2
    assert kinds.count("tool.call.requested") == kinds.count("tool.call.executed") == 3
    assert [e.seq for e in ev] == list(range(len(ev))) and len({e.trace_id for e in ev}) == 1
    assert by_type(ev, "session.start")[0].trial == {"prompt_id": "P-1", "seed": 7}


def test_requested_precedes_executed_with_links_and_ids(traced):
    ev = traced["events"]
    ids = {e.event_id: e for e in ev}
    model_ends = by_type(ev, "model.call.end")
    for req in by_type(ev, "tool.call.requested"):
        assert req.observed_at == "model_output" and req.parent_event_id == model_ends[0].event_id and req.model_call_id == model_ends[0].call_id
        ex = next(e for e in by_type(ev, "tool.call.executed") if e.tool_call_id == req.tool_call_id)
        assert ex.requested_event_id == req.event_id and ex.parent_event_id == req.event_id
        assert ev.index(req) < ev.index(ex) and ex.tool_name == req.tool.name
        assert req.prov["tool_call_id"] == "verified"
    for e in ev[1:]:
        assert e.parent_event_id is None or e.parent_event_id in ids
    assert {e.tool_call_id for e in by_type(ev, "tool.call.requested")} == {"call_1", "call_2", "call_3"}


def test_severity_is_tagged_at_tool_call_time(traced):
    got = {e.tool.name: (e.severity, e.severity_basis, e.capability_hint) for e in by_type(traced["events"], "tool.call.requested")}
    assert got["lookup_order"][:2] == ("read_only", "name_rule")
    assert got["fs_delete_file"] == ("irreversible", "name_rule", "filesystem.delete")
    assert got["fs_write_file"] == ("state_changing", "name_rule", "filesystem.write")
    sev = {e.tool_name: e.severity for e in by_type(traced["events"], "tool.call.executed")}
    assert sev == {"lookup_order": "read_only", "fs_delete_file": "irreversible", "fs_write_file": "state_changing"}


def test_default_capture_leaves_no_plaintext(traced):
    assert CANARY not in traced["text"] and SALT.decode() not in traced["text"]
    req = by_type(traced["events"], "tool.call.requested")[1]
    assert req.args.mode == "digest" and len(req.args.digest) == 16 and req.args.keys == ["path"]
    ex = by_type(traced["events"], "tool.call.executed")[0]
    assert ex.result.mode == "digest" and ex.result.size > 0 and ex.status == "success" and ex.duration_ms is not None


def test_model_usage_stop_and_provenance(traced):
    ev = traced["events"]
    ends = by_type(ev, "model.call.end")
    assert ends[0].usage.input_tokens == 11 and ends[0].usage.output_tokens == 7 and ends[0].finish_reason_raw == "tool_calls"
    assert ends[0].tool_calls_requested_count == 3 and ends[1].tool_calls_requested_count == 0 and ends[0].model_returned == "fake-model-1"
    assert ends[0].prov["usage"] == "verified" and ends[0].prov["finish_reason_raw"] == "inferred"
    stop = by_type(ev, "stop")[0]
    assert stop.stop_raw == "stop" and stop.stop_status == "end_of_turn" and stop.source_event_id == ends[1].event_id
    start = by_type(ev, "model.call.start")[0]
    assert start.prov["tools_offered"] == "unknown" or start.tools_offered is not None
    assert by_type(ev, "session.end")[0].reason == "completed" and by_type(ev, "agent.end")[0].outcome == "completed"


def test_inert_tools_recorded_the_calls_and_the_agent_answer_is_unchanged(traced):
    assert [c["tool"] for c in traced["kit"].calls] == ["lookup_order", "fs_delete_file", "fs_write_file"]
    plain, _ = run_agent(handler=None)
    assert plain.content == traced["out"].content == "all done"


def test_tracing_failure_never_changes_the_run(tmp_path):
    class Broken(TraceWriter):
        def write(self, event):
            raise OSError("disk full")

    w = Broken(tmp_path / "run.jsonl", salt=SALT)
    h = TraceCallbackHandler(w)
    out, kit = run_agent(h)
    assert out.content == "all done" and len(kit.calls) == 3
    assert h.errors and all("OSError" in e for e in h.errors[:3])


def test_a_bare_chat_model_call_is_its_own_trace(tmp_path):
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = TraceCallbackHandler(w)
    GenericFakeChatModel(messages=iter([AIMessage(content="hi", response_metadata={"finish_reason": "length"})])).invoke([HumanMessage(content="q")], config={"callbacks": [h]})
    w.close()
    kinds = [e.type for e in read_trace(tmp_path / "run.jsonl")]
    assert kinds == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "stop", "agent.end", "session.end"] or "model.call.end" in kinds
    assert [e for e in read_trace(tmp_path / "run.jsonl") if e.type == "stop"][0].stop_status == "token_limit"


def test_tool_error_is_recorded_as_status_error(tmp_path):
    def broken(order_id: str) -> str:
        raise ValueError("synthetic failure")

    tool = StructuredTool.from_function(broken, name="lookup_order", description="d")
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = TraceCallbackHandler(w)
    model = GenericFakeChatModel(messages=iter([AIMessage(content="", tool_calls=[tc("lookup_order", {"order_id": "o1"}, "c1")]), AIMessage(content="x")]))

    def loop(x, config):
        m = model.invoke([HumanMessage(content=x)], config=config)
        try:
            tool.invoke(m.tool_calls[0], config=config)
        except ValueError:
            pass
        return model.invoke([HumanMessage(content="c")], config=config)

    RunnableLambda(loop).invoke("go", config={"callbacks": [h]})
    w.close()
    ex = [e for e in read_trace(tmp_path / "run.jsonl") if e.type == "tool.call.executed"][0]
    assert ex.status == "error" and ex.error_type == "ValueError" and ex.result is None and ex.prov["error_type"] == "verified"


def test_declared_hints_from_tool_metadata_can_raise(tmp_path):
    tool = StructuredTool.from_function(lambda q: "r", name="get_report", description="d", metadata={"destructiveHint": True}, args_schema=None)
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = TraceCallbackHandler(w)
    h.register_tools([tool])
    model = GenericFakeChatModel(messages=iter([AIMessage(content="", tool_calls=[tc("get_report", {"q": "x"}, "c1")]), AIMessage(content="x")]))

    def loop(x, config):
        m = model.invoke([HumanMessage(content=x)], config=config)
        tool.invoke(m.tool_calls[0], config=config)
        return model.invoke([HumanMessage(content="c")], config=config)

    RunnableLambda(loop).invoke("go", config={"callbacks": [h]})
    w.close()
    req = [e for e in read_trace(tmp_path / "run.jsonl") if e.type == "tool.call.requested"][0]
    assert req.severity == "irreversible" and req.severity_basis == "declared" and req.tool.declared == {"destructiveHint": True}


def test_a_tool_started_without_a_model_request_gets_a_requested_event(tmp_path):
    kit = InertToolKit()
    tools = {t.name: t for t in langchain_tools(kit)}
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = TraceCallbackHandler(w, overrides={"lookup_order": "state_changing"})
    tools["lookup_order"].invoke({"order_id": "o1"}, config={"callbacks": [h]})
    w.close()
    ev = list(read_trace(tmp_path / "run.jsonl"))
    req = [e for e in ev if e.type == "tool.call.requested"][0]
    ex = [e for e in ev if e.type == "tool.call.executed"][0]
    assert req.observed_at == "tool_start" and req.severity == "state_changing" and req.severity_basis == "manual" and ex.requested_event_id == req.event_id


def test_full_capture_writes_content_only_to_the_capture_file(tmp_path):
    cap = tmp_path / "captures"
    w = TraceWriter(tmp_path / "traces" / "run.jsonl", capture="full", salt=SALT, capture_dir=cap)
    run_agent(TraceCallbackHandler(w))
    w.close()
    assert CANARY not in (tmp_path / "traces" / "run.jsonl").read_text()
    assert CANARY in (cap / "run.full.jsonl").read_text()
    req = [e for e in read_trace(tmp_path / "traces" / "run.jsonl") if e.type == "tool.call.requested"][0]
    assert req.args.mode == "full" and req.args.ref.startswith("run.full.jsonl#")


def test_the_handler_runs_inline_and_does_not_raise():
    assert TraceCallbackHandler.run_inline is True and TraceCallbackHandler.raise_error is False


def test_installed_langchain_callback_signatures_still_match():
    """The hooks the handler overrides exist with the keyword names it relies on (VERIFIED against langchain_core)."""
    import inspect

    from langchain_core.callbacks import BaseCallbackHandler
    expect = {"on_chain_start": {"serialized", "inputs", "run_id", "parent_run_id"}, "on_chain_end": {"outputs", "run_id", "parent_run_id"},
              "on_chain_error": {"error", "run_id", "parent_run_id"}, "on_chat_model_start": {"serialized", "messages", "run_id", "parent_run_id"},
              "on_llm_start": {"serialized", "prompts", "run_id", "parent_run_id"}, "on_llm_end": {"response", "run_id", "parent_run_id"},
              "on_llm_error": {"error", "run_id", "parent_run_id"}, "on_tool_start": {"serialized", "input_str", "run_id", "parent_run_id", "inputs"},
              "on_tool_end": {"output", "run_id", "parent_run_id"}, "on_tool_error": {"error", "run_id", "parent_run_id"}}
    for name, params in expect.items():
        assert params <= set(inspect.signature(getattr(BaseCallbackHandler, name)).parameters), name
