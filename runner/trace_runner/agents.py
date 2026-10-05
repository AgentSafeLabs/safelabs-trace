"""Per-framework agents (inert tools attached) with the matching trace handler, wrapped as a safelabs-eval ``AgentAdapter`` so the harness's
``run_trial`` (retries, missing_infrastructure, scoring, the AgentPort-Bench row) runs unchanged.

Frameworks are imported only when their agent is built. The model object comes from a *model source* (``FakeProvider`` offline, ``RealModels``
for a real run): the agent code below is the same for both.

Call cap: ``max_model_calls`` model calls per trial. The LangChain loop counts calls itself; ADK uses ``RunConfig(max_llm_calls=n)`` and the
OpenAI Agents SDK ``max_turns=n``, whose errors (LlmCallsLimitExceededError / MaxTurnsExceeded) are caught here and recorded as the trial's own
stop status ``cap_hit`` (in the trace manifest and the AgentResponse), not as a failure. In all three the tools of the last allowed call have run.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from safelabs.agents.base import AgentAdapter
from safelabs.agents.schemas import AgentResponse, ToolCall
from safelabs_trace.inert_tools import InertToolKit
from safelabs_trace.writer import TraceWriter

from trace_runner.config import ModelCfg, RunCfg
from trace_runner.safety import check_openai_tools

STOP_COMPLETED, STOP_CAP, STOP_ERROR = "completed", "cap_hit", "error"


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


@dataclass
class TrialCtx:
    trial_id: str
    prompt_id: str
    seed: int
    run_pass: int = 0
    attempt_base: int = 0  # attempts already made for this trial in earlier passes


@dataclass
class Outcome:
    output: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    stop_status: str = STOP_COMPLETED
    model_calls: int | None = None


def _add(a: int | None, b: Any) -> int | None:
    if b is None:
        return a
    return (a or 0) + int(b)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content if isinstance(p, (str, dict)))
    return ""


def build_kit(tool_names: list[str] | None) -> InertToolKit:
    kit = InertToolKit()
    if tool_names is not None:
        unknown = [n for n in tool_names if n not in kit.tools]
        if unknown:
            raise ValueError(f"unknown inert tool(s): {unknown}")
        kit.tools = {n: kit.tools[n] for n in tool_names}
    return kit


# ---- LangChain -----------------------------------------------------------------------------------------------
async def run_langchain(prompt: str, cfg: RunCfg, model: Any, kit: InertToolKit, writer: TraceWriter, trial: dict) -> Outcome:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_core.runnables import RunnableLambda
    from safelabs_trace.langchain_handler import TraceCallbackHandler, langchain_tools

    handler = TraceCallbackHandler(writer, trial=trial)
    tools = {t.name: t for t in langchain_tools(kit)}
    handler.register_tools(list(tools.values()))
    bound = model.bind_tools(list(tools.values()))
    out = Outcome(model_calls=0)

    async def loop(x: str, config: Any) -> str:
        messages: list[Any] = [SystemMessage(content=cfg.system_prompt), HumanMessage(content=x)]
        while True:
            m = await bound.ainvoke(messages, config=config)
            out.model_calls += 1
            um = getattr(m, "usage_metadata", None) or {}
            out.prompt_tokens, out.completion_tokens = _add(out.prompt_tokens, um.get("input_tokens")), _add(out.completion_tokens, um.get("output_tokens"))
            messages.append(m)
            out.output = _text(m.content)
            if not m.tool_calls:
                return out.output
            for tc in m.tool_calls:
                tool = tools.get(tc["name"])
                messages.append(await tool.ainvoke(tc, config=config) if tool is not None
                                else ToolMessage(content="unknown tool", tool_call_id=tc.get("id") or "x", name=tc["name"]))
            if out.model_calls >= cfg.max_model_calls:
                out.stop_status = STOP_CAP
                return out.output

    await RunnableLambda(loop).ainvoke(prompt, config={"callbacks": [handler]})
    return out


class _DropCapNoise(logging.Filter):
    """ADK logs the call-cap error (which this runner treats as the normal stop status ``cap_hit``) at ERROR with a long traceback; drop only those records."""

    def filter(self, record: logging.LogRecord) -> bool:
        e = record.exc_info[1] if record.exc_info else None
        seen = 0
        while e is not None and seen < 8:
            if type(e).__name__ == "LlmCallsLimitExceededError":
                return False
            e, seen = (e.__cause__ or e.__context__), seen + 1
        return True


_adk_logging_ready = False


def _quiet_adk_cap_logging() -> None:
    global _adk_logging_ready
    if not _adk_logging_ready:
        h = logging.StreamHandler(sys.stderr)
        h.setLevel(logging.WARNING)
        h.addFilter(_DropCapNoise())
        logging.getLogger("google_adk").addHandler(h)  # other ADK warnings and errors still reach stderr
        _adk_logging_ready = True


# ---- Google ADK (library use only: InMemoryRunner; never adk web / api_server) ---------------------------------
async def run_adk(prompt: str, cfg: RunCfg, model: Any, kit: InertToolKit, writer: TraceWriter, trial: dict) -> Outcome:
    from google.adk.agents import Agent
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError
    from google.adk.agents.run_config import RunConfig
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner
    from google.genai import types
    from safelabs_trace.adk_handler import ADKTraceHandler, adk_tools, as_plugin

    _quiet_adk_cap_logging()

    class ClosingHandler(ADKTraceHandler):
        """Gap fix (smoke run, 2026-10-05): when ADK stops a run at the call cap it raises before the model is called, after the plugin has written the
        ``model.call.start`` of the call that never happened; the handler's run-error hook and ``close_open_traces`` close agents and the session but not that
        open model call. Close it here (in both places) with a ``model.call.end`` that carries the error type (``LlmCallsLimitExceededError``), through the handler's own model-error path, so every
        start has an end. Uses the handler's private ``_tr``/``_emit``/``_model_end`` (safelabs-trace/src is not changed; a src-side fix is the cleaner one)."""

        def _close_open_model(self, st: Any, error: BaseException | None) -> None:
            if st is not None and st.get("open_model") is not None:
                self._emit(self._model_end, st, None, error)

        async def on_run_error_callback(self, *, invocation_context: Any, error: Exception) -> None:
            # the plugin path: ADK reports the run error here, and the parent closes the agents and the session (dropping the open model call)
            self._close_open_model(self._tr.get(getattr(invocation_context, "invocation_id", None)), error)
            await super().on_run_error_callback(invocation_context=invocation_context, error=error)

        def close_open_traces(self, error: BaseException | None = None) -> None:
            for st in list(self._tr.values()):
                self._close_open_model(st, error)
            super().close_open_traces(error)

    handler = ClosingHandler(writer, trial=trial)
    agent = Agent(name="bench_agent", model=model, instruction=cfg.system_prompt, tools=adk_tools(kit))
    runner = InMemoryRunner(app=App(name="trace_runner", root_agent=agent, plugins=[as_plugin(handler)]))
    session = await runner.session_service.create_session(app_name="trace_runner", user_id="u")
    out = Outcome(model_calls=0)
    try:
        async for ev in runner.run_async(user_id="u", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
                                         run_config=RunConfig(max_llm_calls=cfg.max_model_calls)):
            um = getattr(ev, "usage_metadata", None)
            if um is not None and not getattr(ev, "partial", False):
                out.model_calls += 1
                out.prompt_tokens = _add(out.prompt_tokens, um.prompt_token_count)
                out.completion_tokens = _add(out.completion_tokens, um.candidates_token_count)
                out.reasoning_tokens = _add(out.reasoning_tokens, getattr(um, "thoughts_token_count", None))
            if ev.is_final_response() and ev.content and ev.content.parts:
                out.output = "".join(p.text or "" for p in ev.content.parts)
    except LlmCallsLimitExceededError as exc:
        handler.close_open_traces(exc)
        out.stop_status = STOP_CAP
    except BaseException as exc:
        handler.close_open_traces(exc)
        raise
    return out


def _oa_usage(out: Outcome, u: Any) -> None:
    if u is None:
        return
    out.prompt_tokens, out.completion_tokens, out.model_calls = int(u.input_tokens), int(u.output_tokens), int(getattr(u, "requests", 0) or 0) or None
    det = getattr(u, "output_tokens_details", None)
    out.reasoning_tokens = getattr(det, "reasoning_tokens", None) if det is not None else None


# ---- OpenAI Agents SDK ---------------------------------------------------------------------------------------
async def run_openai_agents(prompt: str, cfg: RunCfg, model: Any, kit: InertToolKit, writer: TraceWriter, trial: dict) -> Outcome:
    from agents import Agent
    from agents.exceptions import MaxTurnsExceeded
    from safelabs_trace.openai_agents_handler import OpenAIAgentsTraceHandler, openai_agents_tools, run_traced, safe_run_config

    handler = OpenAIAgentsTraceHandler(writer, trial=trial, strict=True)  # strict is not configurable
    tools = openai_agents_tools(kit)
    check_openai_tools(tools)
    agent = Agent(name="bench_agent", instructions=cfg.system_prompt, model=model, tools=tools)
    out = Outcome()
    try:
        result = await run_traced(handler, agent, prompt, run_config=safe_run_config(), max_turns=cfg.max_model_calls)
    except MaxTurnsExceeded as exc:
        out.stop_status = STOP_CAP
        _oa_usage(out, getattr(getattr(getattr(exc, "run_data", None), "context_wrapper", None), "usage", None))  # the exception carries the run's usage
        return out
    out.output = _text(result.final_output) if not isinstance(result.final_output, str) else result.final_output
    _oa_usage(out, getattr(getattr(result, "context_wrapper", None), "usage", None))
    return out


RUNNERS = {"langchain": run_langchain, "adk": run_adk, "openai_agents": run_openai_agents}


class TracedAdapter(AgentAdapter):
    """One (framework, model) cell. ``set_context`` before each trial; ``execute`` is called by run_trial once per attempt."""

    def __init__(self, cfg: RunCfg, framework: str, model_cfg: ModelCfg, model_source: Any, salt: bytes, traces_dir: Path) -> None:
        super().__init__(timeout=cfg.call_timeout_s)
        self.cfg, self.framework, self.model_cfg, self.source = cfg, framework, model_cfg, model_source
        self.salt, self.traces_dir = salt, Path(traces_dir)
        self.ctx: TrialCtx | None = None
        self._n = 0
        self.last: dict[str, Any] = {}

    @property
    def adapter_type(self) -> str:
        return f"traced_{self.framework}"

    def set_context(self, ctx: TrialCtx) -> None:
        self.ctx, self._n, self.last = ctx, 0, {}

    def trace_path(self, trial_id: str) -> Path:
        return self.traces_dir / f"{safe_name(trial_id)}.jsonl"

    async def _execute(self, prompt: str) -> AgentResponse:
        ctx = self.ctx
        assert ctx is not None, "set_context() first"
        self._n += 1
        attempt = ctx.attempt_base + self._n
        self.last = {"stop_status": STOP_ERROR, "attempt": attempt, "tools_called": [], "model_calls": None}
        trial = {"trial_id": ctx.trial_id, "prompt_id": ctx.prompt_id, "model": self.model_cfg.id, "framework": self.framework, "seed": ctx.seed, "attempt": attempt}
        kit = build_kit(self.cfg.tools)
        model = self.source.build(self.framework, self.model_cfg, ctx, self._n)
        writer = TraceWriter(self.trace_path(ctx.trial_id), capture="digest", salt=self.salt)
        t0 = time.perf_counter()
        try:
            out = await RUNNERS[self.framework](prompt, self.cfg, model, kit, writer, trial)
        finally:
            writer.close()
            self.last["tools_called"] = [c["tool"] for c in kit.calls]
        self.last.update(stop_status=out.stop_status, model_calls=out.model_calls)
        usage = None if out.prompt_tokens is None and out.completion_tokens is None else {
            "prompt_tokens": out.prompt_tokens, "completion_tokens": out.completion_tokens, "reasoning_tokens": out.reasoning_tokens}
        prov = {"tool_calls": "verified", "stop_reason": "inferred"}  # tool calls were made through the inert kit; the stop status is this runner's own label
        if usage is not None:
            prov["usage"] = "verified"
        return AgentResponse(output=out.output, provenance=prov, latency_ms=(time.perf_counter() - t0) * 1000, usage=usage, stop_reason=out.stop_status,
                             tool_calls=[ToolCall(name=c["tool"], arguments=None) for c in kit.calls],  # names only: arguments never leave the process
                             metadata={"stop_status": out.stop_status, "model_calls": out.model_calls, "attempt": attempt}, framework=self.adapter_type)
