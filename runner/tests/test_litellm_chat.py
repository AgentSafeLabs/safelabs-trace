"""The LangChain chat model over LiteLLM, tested with litellm's completion functions replaced by fakes (nothing leaves the process)."""

import json
from types import SimpleNamespace

import pytest

litellm = pytest.importorskip("litellm")

from rt_helpers import SALT, make_cfg, model, run  # noqa: E402
from safelabs_trace.inert_tools import InertToolKit  # noqa: E402
from safelabs_trace.writer import TraceWriter, read_trace  # noqa: E402
from trace_runner.agents import run_langchain  # noqa: E402
from trace_runner.litellm_chat import LiteLLMChat  # noqa: E402


def resp(content="", calls=(), finish="stop", pt=11, ct=7):
    tcs = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tcs or None), finish_reason=finish)],
                           usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct), model="fake")


def test_the_langchain_agent_runs_over_litellm_with_tools_and_traces(tmp_path, monkeypatch):
    seen = []
    script = iter([resp(calls=[("fs_delete_file", {"path": "/x"})], finish="tool_calls"), resp("done")])

    async def fake_acompletion(**kw):
        seen.append(kw)
        return next(script)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    cfg = make_cfg(tmp_path)
    kit = InertToolKit()
    w = TraceWriter(tmp_path / "t.jsonl", salt=SALT)
    out = run(run_langchain("hello", cfg, LiteLLMChat(model="anthropic/x"), kit, w, {"trial_id": "t", "attempt": 1}))
    w.close()
    assert out.output == "done" and out.model_calls == 2 and (out.prompt_tokens, out.completion_tokens) == (22, 14) and out.stop_status == "completed"
    assert [c["tool"] for c in kit.calls] == ["fs_delete_file"]
    assert len(seen[0]["tools"]) == 12 and seen[0]["model"] == "anthropic/x" and seen[0]["messages"][0]["role"] == "system"
    assert [m["role"] for m in seen[1]["messages"]] == ["system", "user", "assistant", "tool"]
    assert seen[1]["messages"][2]["tool_calls"][0]["function"]["name"] == "fs_delete_file"
    ev = list(read_trace(tmp_path / "t.jsonl"))
    assert [e.severity for e in ev if e.type == "tool.call.requested"] == ["irreversible"]


def test_the_call_cap_stops_the_langchain_loop(tmp_path, monkeypatch):
    async def always_tools(**kw):
        return resp(calls=[("lookup_order", {"order_id": "o"})], finish="tool_calls")

    monkeypatch.setattr(litellm, "acompletion", always_tools)
    cfg = make_cfg(tmp_path, max_model_calls=3)
    out = run(run_langchain("hello", cfg, LiteLLMChat(model="m"), InertToolKit(), TraceWriter(tmp_path / "c.jsonl", salt=SALT), {"trial_id": "t", "attempt": 1}))
    assert out.stop_status == "cap_hit" and out.model_calls == 3


def test_a_provider_error_propagates_for_the_harness_to_classify(tmp_path, monkeypatch):
    from trace_runner.fakes import RateLimitError

    async def boom(**kw):
        raise RateLimitError("429")

    monkeypatch.setattr(litellm, "acompletion", boom)
    with pytest.raises(RateLimitError):
        run(run_langchain("hello", make_cfg(tmp_path), LiteLLMChat(model="m"), InertToolKit(), TraceWriter(tmp_path / "e.jsonl", salt=SALT), {"trial_id": "t", "attempt": 1}))
