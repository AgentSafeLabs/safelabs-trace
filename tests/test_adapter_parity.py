"""The same logical scenario through the LangChain handler and the ADK handler, with fakes and the same inert tool:
one model call -> one call to ``lookup_order`` -> a final answer. Offline; synthetic strings. Skipped unless both frameworks are installed.

Unavoidable differences (asserted as differences below, not hidden): call ids (LangChain passes the model's id through; ADK may assign its own
later), ``tools_offered`` (ADK exposes the offered tool names, a bare LangChain fake model does not), ``provider`` and ``model_requested``,
the raw stop string (``stop`` against ``STOP``; the unified status is equal) and the header coverage for the session events
(LangChain marks them partial, ADK emits them)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("google.adk")
pytest.importorskip("google.genai")

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

from safelabs_trace.adk_handler import ADKTraceHandler, adk_tools  # noqa: E402
from safelabs_trace.divergence import action_verdict, analyze, divergence_table, load_traces, text_verdict  # noqa: E402
from safelabs_trace.inert_tools import InertToolKit  # noqa: E402
from safelabs_trace.langchain_handler import TraceCallbackHandler, langchain_tools  # noqa: E402
from safelabs_trace.writer import TraceWriter, read_trace  # noqa: E402
from tests.helpers import SALT  # noqa: E402
from tests.test_adk_handler import adk, calls, make_agent, no_network, run_agent, text, usage  # noqa: E402,F401  (fixtures and helpers)

ARGS = {"order_id": "o-1"}


def run_langchain(tmp_path):
    kit = InertToolKit()
    tools = {t.name: t for t in langchain_tools(kit)}
    w = TraceWriter(tmp_path / "lc.jsonl", salt=SALT)
    h = TraceCallbackHandler(w)
    model = GenericFakeChatModel(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "lookup_order", "args": ARGS, "id": "call_1", "type": "tool_call"}],
                  usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}, response_metadata={"finish_reason": "stop"}),
        AIMessage(content="done", usage_metadata={"input_tokens": 8, "output_tokens": 1, "total_tokens": 9}, response_metadata={"finish_reason": "stop"}),
    ]))

    def loop(x, config):
        m = model.invoke([HumanMessage(content=x)], config=config)
        for call in m.tool_calls:
            tools[call["name"]].invoke(call, config=config)
        return model.invoke([HumanMessage(content="continue")], config=config)

    out = RunnableLambda(loop).invoke("start", config={"callbacks": [h]})
    w.close()
    assert out.content == "done" and not h.errors and [c["tool"] for c in kit.calls] == ["lookup_order"]
    return list(read_trace(tmp_path / "lc.jsonl")), "done"


def run_adk(adk, tmp_path):
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "adk.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    agent = make_agent(adk, [calls(adk, ("lookup_order", ARGS, "call_1"), usage=usage(adk, 5, 2)), text(adk, "done", usage=usage(adk, 8, 1))], tools=adk_tools(kit))
    out, _ = run_agent(adk, agent, plugin_handler=h)
    w.close()
    assert out == "done" and not h.errors and [c["tool"] for c in kit.calls] == ["lookup_order"]
    return list(read_trace(tmp_path / "adk.jsonl")), out


@pytest.fixture
def both(adk, tmp_path):
    return run_langchain(tmp_path)[0], run_adk(adk, tmp_path)[0]


def kinds(ev):
    return [e.type for e in ev]


def by(ev, t):
    return [e for e in ev if e.type == t]


def parent_kinds(ev):
    ids = {e.event_id: e.type for e in ev}
    return [(e.type, ids.get(e.parent_event_id)) for e in ev]


def test_same_sequence_of_event_types(both):
    lc, ad = both
    assert kinds(lc) == kinds(ad) == ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "tool.call.requested",
                                      "tool.call.executed", "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]


def test_same_parent_structure(both):
    lc, ad = both
    assert parent_kinds(lc) == parent_kinds(ad)


def test_same_severity_and_rule_on_the_tool_events(both):
    for ev in both:
        req, ex = by(ev, "tool.call.requested")[0], by(ev, "tool.call.executed")[0]
        assert (req.severity, req.severity_basis, tuple(req.rule_ids), req.capability_hint) == ("read_only", "name_rule", ("N-READ",), None)
        assert (ex.severity, ex.severity_basis, ex.status, ex.tool_name) == ("read_only", "name_rule", "success", "lookup_order")
        assert req.args.keys == ["order_id"] and req.args.mode == ex.result.mode == "digest" and req.observed_at == "model_output"
    lc_req, ad_req = by(both[0], "tool.call.requested")[0], by(both[1], "tool.call.requested")[0]
    assert lc_req.args.digest == ad_req.args.digest and lc_req.args.size == ad_req.args.size  # same salt, same arguments, same digest


def test_same_values_where_both_frameworks_expose_them(both):
    lc, ad = both
    assert [e.usage.model_dump() for e in by(lc, "model.call.end")] == [e.usage.model_dump() for e in by(ad, "model.call.end")]
    assert [e.tool_calls_requested_count for e in by(lc, "model.call.end")] == [e.tool_calls_requested_count for e in by(ad, "model.call.end")] == [1, 0]
    assert by(lc, "stop")[0].stop_status == by(ad, "stop")[0].stop_status == "end_of_turn"
    assert by(lc, "session.end")[0].reason == by(ad, "session.end")[0].reason == "completed" and by(lc, "agent.end")[0].outcome == by(ad, "agent.end")[0].outcome
    assert by(lc, "tool.call.requested")[0].tool_call_id == by(ad, "tool.call.requested")[0].tool_call_id == "call_1"


def test_documented_differences_are_real(both):
    lc, ad = both
    assert by(lc, "model.call.start")[0].tools_offered is None and by(ad, "model.call.start")[0].tools_offered  # names exposed by ADK only
    assert by(lc, "stop")[0].stop_raw == "stop" and by(ad, "stop")[0].stop_raw == "STOP"
    assert by(ad, "model.call.start")[0].model_requested == "fake-model"
    assert lc[0].framework == "langchain-core" and ad[0].framework == "google-adk"
    assert lc[0].coverage["session.start"] == "partial" and ad[0].coverage["session.start"] == "emitted"
    for t in ("tool.call.requested", "tool.call.executed", "model.call.start", "model.call.end", "stop"):
        assert lc[0].coverage[t] == ad[0].coverage[t] or t == "stop"


@pytest.mark.parametrize("verdict,text_v", [("pass", "safe"), ("fail", "unsafe"), ("vulnerable", "unsafe"), ("uncertain", "abstain")])
def test_divergence_gives_the_same_result_from_both_traces(both, tmp_path, verdict, text_v):
    results = []
    for name, ev in zip(("lc", "adk"), both):
        av = action_verdict(ev)
        assert (av.level, av.source, av.n_calls, av.blocked, av.partial) == ("read", "executed", 1, 0, False)
        tid = ev[0].trace_id
        table = analyze({tid: ev}, {tid: verdict}, min_class=1)
        assert text_verdict(verdict) == text_v
        results.append(table)
    lc_t, ad_t = results
    assert lc_t == ad_t
    assert lc_t["matrix"][text_v]["read"] == 1 and lc_t["n_excluded_unknown_action"] == 0


def test_the_traces_survive_a_round_trip_through_the_loader(both, tmp_path):
    assert set(len(v) for v in (load_traces(tmp_path / "lc.jsonl").values())) == {12}
    assert set(len(v) for v in (load_traces(tmp_path / "adk.jsonl").values())) == {12}
