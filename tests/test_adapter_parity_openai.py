"""The same logical scenario through the LangChain, ADK and OpenAI Agents handlers, with fakes and the same inert tool:
one model call -> one call to ``lookup_order`` -> a final answer. Offline; synthetic strings. Skipped unless all three frameworks are installed.

Unavoidable differences (asserted as differences below, not hidden): ``tools_offered`` (ADK and the OpenAI SDK expose the agent's tool names, a bare
LangChain fake model does not); ``model_requested`` (the SDK and ADK expose it, the LangChain fake does not); reasoning tokens (null for LangChain and ADK, a zero-filled 0 from the OpenAI SDK's Usage); finish reasons (ADK reads ``STOP``, LangChain
``stop``; the OpenAI SDK exposes none, so ``stop_raw`` is the last output item's status ``completed``; the unified status is equal); ``finish_reason_raw`` on
the model call end is null for the OpenAI SDK; session events are ``partial`` in the OpenAI and LangChain headers and ``emitted`` in ADK's."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("google.adk")
pytest.importorskip("google.genai")
pytest.importorskip("agents")

from safelabs_trace.divergence import action_verdict, analyze, text_verdict  # noqa: E402
from safelabs_trace.inert_tools import InertToolKit  # noqa: E402
from safelabs_trace.openai_agents_handler import OpenAIAgentsTraceHandler, ensure_openai_export_off, openai_agents_tools, run_traced  # noqa: E402
from safelabs_trace.writer import TraceWriter, read_trace  # noqa: E402
from tests.helpers import SALT  # noqa: E402
from tests.test_adapter_parity import run_adk, run_langchain  # noqa: E402
from tests.test_adk_handler import adk, no_network  # noqa: E402,F401  (fixtures)
from tests.test_openai_agents_handler import calls as oa_calls, make as oa_make, msg as oa_msg, offline, sdk  # noqa: E402,F401  (fixtures and helpers)

ARGS = {"order_id": "o-1"}


def run_openai(sdk, tmp_path):
    ensure_openai_export_off()
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "oa.jsonl", salt=SALT)
    h = OpenAIAgentsTraceHandler(w)
    agent, _ = oa_make(sdk, [oa_calls(sdk, ("lookup_order", ARGS, "call_1"), inp=5, out=2), oa_msg(sdk, "done", inp=8, out=1)], tools=openai_agents_tools(kit))
    result = asyncio.run(run_traced(h, agent, "start"))
    w.close()
    assert result.final_output == "done" and not h.errors and [c["tool"] for c in kit.calls] == ["lookup_order"]
    return list(read_trace(tmp_path / "oa.jsonl"))


@pytest.fixture
def three(adk, sdk, tmp_path):
    lc, _ = run_langchain(tmp_path)
    ad, _ = run_adk(adk, tmp_path)
    return {"langchain": lc, "adk": ad, "openai": run_openai(sdk, tmp_path)}


def kinds(ev):
    return [e.type for e in ev]


def by(ev, t):
    return [e for e in ev if e.type == t]


def parent_kinds(ev):
    ids = {e.event_id: e.type for e in ev}
    return [(e.type, ids.get(e.parent_event_id)) for e in ev]


def test_same_sequence_of_event_types_in_all_three(three):
    expected = ["trace.header", "session.start", "agent.start", "model.call.start", "model.call.end", "tool.call.requested", "tool.call.executed",
                "model.call.start", "model.call.end", "stop", "agent.end", "session.end"]
    for name, ev in three.items():
        assert kinds(ev) == expected, name


def test_same_parent_structure_in_all_three(three):
    base = parent_kinds(three["langchain"])
    assert parent_kinds(three["adk"]) == base and parent_kinds(three["openai"]) == base


def test_same_severity_rule_digest_and_ids_on_the_tool_events(three):
    digests = set()
    for name, ev in three.items():
        req, ex = by(ev, "tool.call.requested")[0], by(ev, "tool.call.executed")[0]
        assert (req.severity, req.severity_basis, tuple(req.rule_ids), req.capability_hint) == ("read_only", "name_rule", ("N-READ",), None), name
        assert (ex.severity, ex.severity_basis, ex.status, ex.tool_name, ex.tool_call_id) == ("read_only", "name_rule", "success", "lookup_order", "call_1"), name
        assert req.tool_call_id == "call_1" and req.args.keys == ["order_id"] and req.args.mode == ex.result.mode == "digest" and req.observed_at == "model_output", name
        digests.add((req.args.digest, req.args.size))
    assert len(digests) == 1  # same salt and same arguments give the same digest in every framework


def test_same_values_where_all_three_expose_them(three):
    for name, ev in three.items():
        ends = by(ev, "model.call.end")
        assert [(e.usage.input_tokens, e.usage.output_tokens) for e in ends] == [(5, 2), (8, 1)], name
        assert [e.tool_calls_requested_count for e in ends] == [1, 0], name
        assert by(ev, "stop")[0].stop_status == "end_of_turn" and by(ev, "session.end")[0].reason == "completed" and by(ev, "agent.end")[0].outcome == "completed", name
    # reasoning tokens: LangChain and ADK report none (null); the OpenAI SDK's Usage always carries a count and zero-fills it (a documented difference)
    assert [e.usage.reasoning_tokens for e in by(three["langchain"], "model.call.end")] == [None, None] == [e.usage.reasoning_tokens for e in by(three["adk"], "model.call.end")]
    assert [e.usage.reasoning_tokens for e in by(three["openai"], "model.call.end")] == [0, 0]


def test_documented_differences_are_real(three):
    lc, ad, oa = three["langchain"], three["adk"], three["openai"]
    assert by(lc, "model.call.start")[0].tools_offered is None and by(ad, "model.call.start")[0].tools_offered and by(oa, "model.call.start")[0].tools_offered
    assert by(lc, "model.call.start")[0].model_requested is None and by(oa, "model.call.start")[0].model_requested == "fake-model"
    assert (by(lc, "stop")[0].stop_raw, by(ad, "stop")[0].stop_raw, by(oa, "stop")[0].stop_raw) == ("stop", "STOP", "completed")
    assert by(oa, "model.call.end")[0].finish_reason_raw is None and by(ad, "model.call.end")[0].finish_reason_raw == "STOP"
    assert lc[0].framework == "langchain-core" and ad[0].framework == "google-adk" and oa[0].framework == "openai-agents"
    assert (lc[0].coverage["session.start"], ad[0].coverage["session.start"], oa[0].coverage["session.start"]) == ("partial", "emitted", "partial")
    for t in ("tool.call.requested", "tool.call.executed", "model.call.start", "model.call.end"):
        assert lc[0].coverage[t] == ad[0].coverage[t] == oa[0].coverage[t] == "emitted"


@pytest.mark.parametrize("verdict,text_v", [("pass", "safe"), ("fail", "unsafe"), ("vulnerable", "unsafe"), ("uncertain", "abstain")])
def test_divergence_gives_the_same_result_from_all_three_traces(three, verdict, text_v):
    tables = []
    for name, ev in three.items():
        av = action_verdict(ev)
        assert (av.level, av.source, av.n_calls, av.blocked, av.partial) == ("read", "executed", 1, 0, False), name
        tid = ev[0].trace_id
        tables.append(analyze({tid: ev}, {tid: verdict}, min_class=1))
        assert text_verdict(verdict) == text_v
    assert tables[0] == tables[1] == tables[2]
    assert tables[0]["matrix"][text_v]["read"] == 1 and tables[0]["n_excluded_unknown_action"] == 0
