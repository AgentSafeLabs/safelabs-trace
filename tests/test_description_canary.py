"""The tool description feeds the tagger at runtime but is never written to a trace (one canary test per framework).
Frameworks that are not installed skip cleanly."""

from __future__ import annotations

import json

import pytest

from safelabs_trace.writer import TraceWriter, read_trace
from tests.helpers import SALT

CANARY_DESC = "CANARY-DESCRIPTION-TEXT-5150"
DESC = f"Deletes the entry and returns a summary. {CANARY_DESC}"


def _assert_tagged_from_description_and_clean(events, *paths):
    req = [e for e in events if e.type == "tool.call.requested"]
    assert len(req) == 1
    assert (req[0].severity, req[0].severity_basis) == ("irreversible", "name_rule") and req[0].rule_ids[0].startswith("D-DESC-")
    ex = [e for e in events if e.type == "tool.call.executed"]
    assert ex and ex[0].severity == "irreversible"
    for e in events:
        assert CANARY_DESC not in json.dumps(e.model_dump(mode="json") if hasattr(e, "model_dump") else repr(e), default=str)
    for p in paths:
        assert CANARY_DESC not in p.read_text()


# ---- LangChain ---------------------------------------------------------------------------------------------------
def test_langchain_description_is_used_but_never_written(tmp_path):
    pytest.importorskip("langchain_core")
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.runnables import RunnableLambda
    from langchain_core.tools import StructuredTool

    from safelabs_trace.langchain_handler import TraceCallbackHandler

    def frobnicate(thing: str) -> str:
        return "ok"

    tool = StructuredTool.from_function(func=frobnicate, name="frobnicate", description=DESC)
    for mode in ("registered", "tool_start"):
        path = tmp_path / f"{mode}.jsonl"
        w = TraceWriter(path, salt=SALT)
        h = TraceCallbackHandler(w)
        if mode == "registered":  # the request is built from the model output, before the tool starts
            h.register_tools([tool])
            model = GenericFakeChatModel(messages=iter([AIMessage(content="", tool_calls=[{"name": "frobnicate", "args": {"thing": "x"}, "id": "c1", "type": "tool_call"}]),
                                                        AIMessage(content="done")]))

            def loop(x, config):
                m = model.invoke([HumanMessage(content=x)], config=config)
                for call in m.tool_calls:
                    tool.invoke(call, config=config)
                return model.invoke([HumanMessage(content="go")], config=config)

            RunnableLambda(loop).invoke("start", config={"callbacks": [h]})
        else:  # a bare tool call: the description arrives in the serialized tool
            tool.invoke({"thing": "x"}, config={"callbacks": [h]})
        w.close()
        _assert_tagged_from_description_and_clean(list(read_trace(path)), path)
        assert h.descriptions["frobnicate"] == DESC and h.errors == []


# ---- Google ADK --------------------------------------------------------------------------------------------------
from tests.test_adk_handler import adk, calls as adk_calls, make_agent, no_network, run_agent as adk_run, text as adk_text  # noqa: E402,F401


def test_adk_description_is_used_but_never_written(adk, tmp_path):
    from safelabs_trace.adk_handler import ADKTraceHandler

    def frobnicate(thing: str) -> str:
        return "ok"

    frobnicate.__doc__ = DESC
    w = TraceWriter(tmp_path / "run.jsonl", salt=SALT)
    h = ADKTraceHandler(w)
    agent = make_agent(adk, [adk_calls(adk, ("frobnicate", {"thing": "x"}, "c1")), adk_text(adk, "done")], tools=[adk.tools.FunctionTool(frobnicate)])
    adk_run(adk, agent, plugin_handler=h)  # no register_tools call: the description is read from the model request's tools
    w.close()
    _assert_tagged_from_description_and_clean(list(read_trace(tmp_path / "run.jsonl")), tmp_path / "run.jsonl")
    assert CANARY_DESC in h.descriptions["frobnicate"] and h.errors == []


# ---- OpenAI Agents SDK -------------------------------------------------------------------------------------------
from tests.test_openai_agents_handler import calls as oa_calls, export_off, msg as oa_msg, offline, sdk, traced as oa_traced  # noqa: E402,F401


def test_openai_agents_description_is_used_but_never_written(export_off, tmp_path):
    sdk = export_off

    async def invoke(ctx, args_json):
        return "ok"

    schema = {"type": "object", "properties": {"thing": {"type": "string"}}, "required": ["thing"], "additionalProperties": False}
    tool = sdk.agents.FunctionTool(name="frobnicate", description=DESC, params_json_schema=schema, on_invoke_tool=invoke, strict_json_schema=True)
    r = oa_traced(sdk, tmp_path, [oa_calls(sdk, ("frobnicate", {"thing": "x"}, "c1")), oa_msg(sdk, "done")], tools=[tool])
    _assert_tagged_from_description_and_clean(r.events, r.path)
    assert r.handler.descriptions["frobnicate"] == DESC and r.handler.errors == []
