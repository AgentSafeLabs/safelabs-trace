"""safelabs_trace/adk_handler.py: Google ADK trace handler (the second adapter; mirrors ``langchain_handler.py``).

``import safelabs_trace.adk_handler`` does not import ``google.adk``: the handler is plain Python that implements the ADK plugin
callbacks by name, and ``as_plugin`` / ``adk_tools`` import ADK only when called. The module is not imported by
``safelabs_trace/__init__.py``.

Hook surface (google-adk 2.9.0, VERIFIED in the installed package, paths relative to ``google/adk/``):

* **Plugin API (preferred)**: ``BasePlugin`` (``plugins/base_plugin.py:41``) with ``before_run_callback`` (136), ``after_run_callback`` (174),
  ``before_agent_callback`` (198), ``after_agent_callback`` (217), ``before_model_callback`` (233), ``after_model_callback`` (253),
  ``on_model_error_callback`` (272), ``before_tool_callback`` (297), ``after_tool_callback`` (321), ``on_tool_error_callback`` (348),
  ``on_agent_error_callback`` (374), ``on_run_error_callback`` (394). Registered with ``Runner(plugins=[...])`` (``runners.py:229``). A callback
  that returns a value short-circuits the run, so every handler method here returns None. ``after_run_callback`` fires on success only; a failed run
  calls ``on_run_error_callback`` instead (``runners.py:1455-1480``).
* **Fallback, per-agent callbacks**: ``BaseAgent.before_agent_callback`` / ``after_agent_callback`` (``agents/base_agent.py:168,186``) and the
  ``LlmAgent`` model and tool callbacks (``agents/llm_agent.py:484-564``). ``attach_to_agent`` installs the same handler on an agent tree. There is no
  run-level or agent-error hook on this path, so the session events are synthesized from the root agent and ``close_open_traces`` must be called
  after a failed run.
* Objects read: ``CallbackContext`` / ``ToolContext`` (``agents/context.py:113``; ``invocation_id``, ``session``, ``function_call_id`` at 237),
  ``LlmRequest.model`` and ``tools_dict`` (``models/llm_request.py:68,84``), ``LlmResponse.usage_metadata`` / ``finish_reason`` /
  ``model_version`` / ``error_code`` / ``partial`` and ``content.parts[*].function_call`` (``models/llm_response.py:59,117,120,139``),
  ``BaseTool.name`` / ``custom_metadata`` (``tools/base_tool.py:60,90``).

Telemetry: this handler configures and enables no exporter and sets no tracer provider. See the report for what ADK itself emits.

Never written to a trace: prompts, model text, tool arguments, tool results (only the writer's salted digests). The handler never raises into the
run: any error while emitting is recorded in ``handler.errors``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from importlib import metadata as _metadata
from typing import Any, Callable

from safelabs_trace import __version__ as PACKAGE_VERSION
from safelabs_trace._common import (
    build_agent_end, build_session_end, build_stop, build_tool_executed, build_tool_requested, remember_description, safe_emit, tags as _tags,
)
from safelabs_trace.schema import AgentRef, AgentStart, ModelCallEnd, ModelCallStart, SessionStart, Usage, build_event
from safelabs_trace.severity import TAGGER_VERSION, load_rules
from safelabs_trace.writer import TraceWriter

COVERAGE = {  # plugin path
    "session.start": "emitted", "session.end": "emitted", "agent.start": "emitted", "agent.end": "emitted",
    "model.call.start": "emitted", "model.call.end": "emitted", "tool.call.requested": "emitted", "tool.call.executed": "emitted",
    "plan.step": "not_exposed", "policy.decision": "not_exposed", "stop": "emitted",
}
COVERAGE_AGENT_CALLBACKS = {**COVERAGE, "session.start": "partial", "session.end": "partial"}  # synthesized from the root agent

_ERR_TIMEOUT = (TimeoutError,)


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _function_calls(llm_response: Any) -> list[Any]:
    parts = getattr(getattr(llm_response, "content", None), "parts", None) or []
    return [p.function_call for p in parts if getattr(p, "function_call", None) is not None]


class ADKTraceHandler:
    """Writes trace events for ADK runs. Use ``as_plugin(handler)`` with ``Runner(plugins=[...])`` or ``attach_to_agent(agent, handler)``."""

    def __init__(self, writer: TraceWriter, *, trial: dict[str, str | int] | None = None, declared: dict[str, dict[str, Any]] | None = None,
                 overrides: dict[str, str] | None = None, unknown_default: str = "state_changing", rules: dict[str, Any] | None = None,
                 adapter: str = "adk_handler") -> None:
        self.writer, self.trial = writer, trial
        self.declared, self.overrides, self.unknown_default = dict(declared or {}), dict(overrides or {}), unknown_default
        self.rules = rules if rules is not None else load_rules()
        self.adapter = adapter
        self.descriptions: dict[str, str] = {}  # tool name -> description, in memory only, for the tagger; never written to a trace
        self.errors: list[str] = []
        self.version = _adk_version()
        self._tr: dict[str, dict[str, Any]] = {}  # invocation id -> trace state

    # ---- helpers -------------------------------------------------------------------------------------------
    def register_tools(self, tools: list[Any]) -> None:
        """Read declared hints from ``BaseTool.custom_metadata`` (``tools/base_tool.py:90``)."""
        for t in tools:
            remember_description(self.descriptions, getattr(t, "name", None), getattr(t, "description", None))
            md = getattr(t, "custom_metadata", None)
            if isinstance(md, dict) and md:
                self.declared[getattr(t, "name", "")] = md

    def _emit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return safe_emit(self.errors, fn, *args, **kwargs)

    def _write(self, st: dict[str, Any], event: Any) -> Any:
        self.writer.write(event)
        st["count"] += 1
        return event

    @staticmethod
    def _session_id(ctx: Any) -> str | None:
        try:
            return ctx.session.id
        except Exception:  # noqa: BLE001 - duck-typed contexts in tests may lack it
            return None

    def _begin(self, inv: str, session_id: str | None, mode: str) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        st: dict[str, Any] = {"trace_id": trace_id, "session_id": session_id or trace_id, "session_known": session_id is not None, "mode": mode,
                              "t0": time.monotonic(), "count": 0, "stack": [], "session_start_id": None, "root_start_id": None,
                              "open_model": None, "last_model_end": None, "last_finish": None, "pending": defaultdict(list), "tools": {}}
        self._tr[inv] = st
        self.writer.start_trace(trace_id, adapter=self.adapter, framework="google-adk", framework_version=self.version,
                                coverage=COVERAGE if mode == "plugin" else COVERAGE_AGENT_CALLBACKS, tagger_version=TAGGER_VERSION,
                                rules_version=str(self.rules.get("rules_version", "")), package_version=PACKAGE_VERSION)
        tag = "verified" if session_id is not None else "inferred"
        s = self._write(st, build_event(SessionStart, {"session_id": tag}, trace_id=trace_id, session_id=st["session_id"], trial=self.trial))
        st["session_start_id"] = s.event_id
        return st

    def _end_session(self, st: dict[str, Any], inv: str, *, ok: bool, error: BaseException | None) -> None:
        self._write(st, build_session_end(trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=st["session_start_id"], ok=ok, error=error,
                                          t0=st["t0"], event_count=st["count"] + 1))
        self.writer.close_trace(st["trace_id"])
        self._tr.pop(inv, None)

    def close_open_traces(self, error: BaseException | None = None) -> None:
        """Close every trace still open (agent and session ended with an error). Needed on the fallback path after a failed run, where ADK
        gives no run-level hook; harmless on the plugin path."""
        for inv, st in list(self._tr.items()):
            while st["stack"]:
                frame = st["stack"].pop()
                self._emit(self._agent_end, st, frame, ok=False, error=error)
            self._emit(self._end_session, st, inv, ok=False, error=error)

    # ---- run (plugin path) ---------------------------------------------------------------------------------
    async def before_run_callback(self, *, invocation_context: Any) -> None:
        inv = getattr(invocation_context, "invocation_id", None)
        if inv is not None and inv not in self._tr:
            self._emit(self._begin, inv, self._session_id(invocation_context), "plugin")

    async def after_run_callback(self, *, invocation_context: Any) -> None:
        st = self._tr.get(getattr(invocation_context, "invocation_id", None))
        if st is not None and st["mode"] == "plugin":
            self._emit(self._end_session, st, invocation_context.invocation_id, ok=True, error=None)

    async def on_run_error_callback(self, *, invocation_context: Any, error: Exception) -> None:
        inv = getattr(invocation_context, "invocation_id", None)
        st = self._tr.get(inv)
        if st is not None:
            while st["stack"]:  # an agent error hook may not have fired for every open agent
                self._emit(self._agent_end, st, st["stack"].pop(), ok=False, error=error)
            self._emit(self._end_session, st, inv, ok=False, error=error)

    # ---- agents --------------------------------------------------------------------------------------------
    async def before_agent_callback(self, *, agent: Any, callback_context: Any) -> None:
        inv = getattr(callback_context, "invocation_id", None)
        st = self._tr.get(inv)
        if st is None:
            st = self._emit(self._begin, inv, self._session_id(callback_context), "agent_callbacks")
            if st is None:
                return
        self._emit(self._agent_start, st, agent)

    def _agent_start(self, st: dict[str, Any], agent: Any) -> None:
        parent = st["stack"][-1] if st["stack"] else None
        name = getattr(agent, "name", None)
        vals = {"parent_agent_id": parent["name"] if parent else None}
        ev = self._write(st, build_event(AgentStart, _tags(vals), trace_id=st["trace_id"], session_id=st["session_id"],
                                         parent_event_id=parent["event_id"] if parent else st["session_start_id"], agent=AgentRef(name=name), **vals))
        st["stack"].append({"event_id": ev.event_id, "name": name, "root": parent is None})
        if parent is None:
            st["root_start_id"] = ev.event_id

    def _agent_end(self, st: dict[str, Any], frame: dict[str, Any], *, ok: bool, error: BaseException | None) -> None:
        tid, sid = st["trace_id"], st["session_id"]
        if frame["root"]:
            self._write(st, build_stop(trace_id=tid, session_id=sid, parent_event_id=frame["event_id"], raw=st["last_finish"], raw_tag="verified",
                                       source_event_id=st["last_model_end"]))
        self._write(st, build_agent_end(trace_id=tid, session_id=sid, parent_event_id=frame["event_id"], outcome="completed" if ok else "error", error=error,
                                        agent_name=frame["name"]))

    async def after_agent_callback(self, *, agent: Any, callback_context: Any) -> None:
        inv = getattr(callback_context, "invocation_id", None)
        st = self._tr.get(inv)
        if st is None or not st["stack"]:
            return
        frame = st["stack"].pop()
        self._emit(self._agent_end, st, frame, ok=True, error=None)
        if frame["root"] and st["mode"] == "agent_callbacks":
            self._emit(self._end_session, st, inv, ok=True, error=None)

    async def on_agent_error_callback(self, *, agent: Any, callback_context: Any, error: Exception) -> None:
        st = self._tr.get(getattr(callback_context, "invocation_id", None))
        if st is not None and st["stack"]:
            self._emit(self._agent_end, st, st["stack"].pop(), ok=False, error=error)

    # ---- model calls ---------------------------------------------------------------------------------------
    async def before_model_callback(self, *, callback_context: Any, llm_request: Any) -> None:
        st = self._tr.get(getattr(callback_context, "invocation_id", None))
        if st is not None:
            self._emit(self._model_start, st, llm_request)

    def _model_start(self, st: dict[str, Any], llm_request: Any) -> None:
        cfg = getattr(llm_request, "config", None)
        params = {k: v for k, v in (("temperature", getattr(cfg, "temperature", None)), ("max_tokens", getattr(cfg, "max_output_tokens", None))) if v is not None}
        tools = getattr(llm_request, "tools_dict", None)
        offered = sorted(tools) if isinstance(tools, dict) else None
        for tname, tool in (tools.items() if isinstance(tools, dict) else ()):
            remember_description(self.descriptions, tname, getattr(tool, "description", None))
        vals = {"model_requested": getattr(llm_request, "model", None), "params": params or None, "tools_offered": offered}
        parent = st["stack"][-1]["event_id"] if st["stack"] else st["root_start_id"]
        call_id = str(uuid.uuid4())  # ADK has no model-call id
        ev = self._write(st, build_event(ModelCallStart, _tags(vals), trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=parent,
                                         call_id=call_id, **vals))
        st["open_model"] = {"event_id": ev.event_id, "call_id": call_id}

    async def after_model_callback(self, *, callback_context: Any, llm_response: Any) -> None:
        st = self._tr.get(getattr(callback_context, "invocation_id", None))
        if st is not None and not getattr(llm_response, "partial", None):  # streamed fragments are not model-call ends
            self._emit(self._model_end, st, llm_response, None)

    async def on_model_error_callback(self, *, callback_context: Any, llm_request: Any, error: Exception) -> None:
        st = self._tr.get(getattr(callback_context, "invocation_id", None))
        if st is not None:
            self._emit(self._model_end, st, None, error)

    def _model_end(self, st: dict[str, Any], resp: Any, error: BaseException | None) -> None:
        om = st["open_model"] or {"event_id": None, "call_id": str(uuid.uuid4())}
        st["open_model"] = None
        um = getattr(resp, "usage_metadata", None)
        usage = None
        if um is not None:
            usage = Usage(input_tokens=getattr(um, "prompt_token_count", None), output_tokens=getattr(um, "candidates_token_count", None),
                          reasoning_tokens=getattr(um, "thoughts_token_count", None))
        calls = _function_calls(resp) if resp is not None else None
        raw = _enum_name(getattr(resp, "finish_reason", None))
        code = getattr(resp, "error_code", None)
        et = type(error).__name__ if error is not None else (str(code) if code else None)
        vals = {"model_returned": getattr(resp, "model_version", None), "usage": usage, "finish_reason_raw": raw,
                "tool_calls_requested_count": len(calls) if calls is not None else None, "error_type": et}
        end = self._write(st, build_event(ModelCallEnd, _tags(vals), trace_id=st["trace_id"], session_id=st["session_id"],
                                          parent_event_id=om["event_id"], call_id=om["call_id"], **vals))
        st["last_model_end"] = end.event_id
        if raw:
            st["last_finish"] = raw
        for fc in calls or []:
            self._request(st, getattr(fc, "name", "") or "", dict(getattr(fc, "args", None) or {}), getattr(fc, "id", None), end.event_id, om["call_id"], observed_at="model_output")

    # ---- tools ---------------------------------------------------------------------------------------------
    def _request(self, st: dict[str, Any], name: str, args: Any, call_id: str | None, model_event: str | None, model_call: str | None, *, observed_at: str) -> Any:
        parent = model_event or (st["stack"][-1]["event_id"] if st["stack"] else st["root_start_id"])
        ev, tagged = build_tool_requested(self.writer, trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=parent, name=name, args=args,
                                          call_id=call_id, model_call_id=model_call, observed_at=observed_at, declared=self.declared.get(name),
                                          overrides=self.overrides, rules=self.rules, unknown_default=self.unknown_default,
                                          description=self.descriptions.get(name))
        self._write(st, ev)
        st["pending"][name].append({"event_id": ev.event_id, "tool_call_id": call_id, "tagged": tagged, "args": _canon(args) if isinstance(args, dict) else None})
        return ev

    def _match(self, st: dict[str, Any], name: str, call_id: str | None, args: Any) -> dict[str, Any] | None:
        """The pending request for this execution: same id, else same arguments, else the oldest with this tool name."""
        queue = st["pending"].get(name) or []
        pick = None
        if call_id is not None:
            pick = next((p for p in queue if p["tool_call_id"] == call_id), None)
        if pick is None:
            canon = _canon(args) if isinstance(args, dict) else None
            pick = next((p for p in queue if canon is not None and p["args"] == canon), None) or (queue[0] if queue else None)
        if pick is not None:
            queue.remove(pick)
        return pick

    async def before_tool_callback(self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any) -> None:
        st = self._tr.get(getattr(tool_context, "invocation_id", None))
        if st is not None:
            self._emit(self._tool_start, st, tool, tool_args, tool_context)

    def _tool_start(self, st: dict[str, Any], tool: Any, args: Any, ctx: Any) -> None:
        name = getattr(tool, "name", None) or "unknown"
        remember_description(self.descriptions, name, getattr(tool, "description", None))
        call_id = getattr(ctx, "function_call_id", None)
        req = self._match(st, name, call_id, args)
        if req is None:  # a tool ran with no request seen in a model response
            self._request(st, name, args, call_id, None, None, observed_at="tool_start")
            req = self._match(st, name, call_id, args)
        key = call_id or req["event_id"]
        st["tools"][key] = {"name": name, "t0": time.monotonic(), "req": req, "call_id": call_id or req["tool_call_id"]}

    async def after_tool_callback(self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any, result: Any) -> None:
        self._tool_done(tool, tool_context, "success", result, None)

    async def on_tool_error_callback(self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any, error: Exception) -> None:
        self._tool_done(tool, tool_context, "error", None, error)

    def _tool_done(self, tool: Any, ctx: Any, status: str, result: Any, error: BaseException | None) -> None:
        st = self._tr.get(getattr(ctx, "invocation_id", None))
        if st is not None:
            self._emit(self._executed, st, tool, ctx, status, result, error)

    def _executed(self, st: dict[str, Any], tool: Any, ctx: Any, status: str, result: Any, error: BaseException | None) -> None:
        call_id = getattr(ctx, "function_call_id", None)
        name = getattr(tool, "name", None) or "unknown"
        t = st["tools"].pop(call_id, None) if call_id in st["tools"] else next((st["tools"].pop(k) for k, v in list(st["tools"].items()) if v["name"] == name), None)
        if t is None:
            return
        req = t["req"]
        tagged = req["tagged"]
        ev = build_tool_executed(self.writer, trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=req["event_id"], requested_event_id=req["event_id"],
                                 tool_name=t["name"], status=status, severity=tagged.severity, severity_basis=tagged.basis, tool_call_id=t["call_id"], result=result,
                                 capture_result=result is not None, error=error, t0=t["t0"])
        self._write(st, ev)


def _adk_version() -> str | None:
    try:
        return _metadata.version("google-adk")
    except _metadata.PackageNotFoundError:
        return None


def as_plugin(handler: ADKTraceHandler, name: str = "safelabs_trace") -> Any:
    """A ``BasePlugin`` that forwards every callback to the handler (imports ADK now, not at module import)."""
    from google.adk.plugins.base_plugin import BasePlugin

    class _TracePlugin(BasePlugin):
        def __init__(self) -> None:
            super().__init__(name=name)
            self.handler = handler

        async def before_run_callback(self, *, invocation_context):
            await handler.before_run_callback(invocation_context=invocation_context)

        async def after_run_callback(self, *, invocation_context):
            await handler.after_run_callback(invocation_context=invocation_context)

        async def on_run_error_callback(self, *, invocation_context, error):
            await handler.on_run_error_callback(invocation_context=invocation_context, error=error)

        async def before_agent_callback(self, *, agent, callback_context):
            await handler.before_agent_callback(agent=agent, callback_context=callback_context)

        async def after_agent_callback(self, *, agent, callback_context):
            await handler.after_agent_callback(agent=agent, callback_context=callback_context)

        async def on_agent_error_callback(self, *, agent, callback_context, error):
            await handler.on_agent_error_callback(agent=agent, callback_context=callback_context, error=error)

        async def before_model_callback(self, *, callback_context, llm_request):
            await handler.before_model_callback(callback_context=callback_context, llm_request=llm_request)

        async def after_model_callback(self, *, callback_context, llm_response):
            await handler.after_model_callback(callback_context=callback_context, llm_response=llm_response)

        async def on_model_error_callback(self, *, callback_context, llm_request, error):
            await handler.on_model_error_callback(callback_context=callback_context, llm_request=llm_request, error=error)

        async def before_tool_callback(self, *, tool, tool_args, tool_context):
            await handler.before_tool_callback(tool=tool, tool_args=tool_args, tool_context=tool_context)

        async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
            await handler.after_tool_callback(tool=tool, tool_args=tool_args, tool_context=tool_context, result=result)

        async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):
            await handler.on_tool_error_callback(tool=tool, tool_args=tool_args, tool_context=tool_context, error=error)

    return _TracePlugin()


_AGENT_FIELDS = ("before_agent_callback", "after_agent_callback", "before_model_callback", "after_model_callback", "on_model_error_callback",
                 "before_tool_callback", "after_tool_callback", "on_tool_error_callback")


def attach_to_agent(agent: Any, handler: ADKTraceHandler, *, include_sub_agents: bool = True) -> Callable[[], None]:
    """Fallback (b): install the handler through the per-agent callback fields on ``agent`` and, by default, its sub-agents.
    Existing callbacks are kept (the handler's run first). Returns a function that restores the original values."""
    saved: list[tuple[Any, str, Any]] = []

    def listify(v: Any) -> list[Any]:
        return [] if v is None else list(v) if isinstance(v, (list, tuple)) else [v]

    def install(a: Any) -> None:
        h = handler

        async def before_agent(callback_context):
            await h.before_agent_callback(agent=a, callback_context=callback_context)

        async def after_agent(callback_context):
            await h.after_agent_callback(agent=a, callback_context=callback_context)

        async def before_model(callback_context, llm_request):
            await h.before_model_callback(callback_context=callback_context, llm_request=llm_request)

        async def after_model(callback_context, llm_response):
            await h.after_model_callback(callback_context=callback_context, llm_response=llm_response)

        async def model_error(callback_context, llm_request, error):
            await h.on_model_error_callback(callback_context=callback_context, llm_request=llm_request, error=error)

        async def before_tool(tool, args, tool_context):
            await h.before_tool_callback(tool=tool, tool_args=args, tool_context=tool_context)

        async def after_tool(tool, args, tool_context, tool_response):
            await h.after_tool_callback(tool=tool, tool_args=args, tool_context=tool_context, result=tool_response)

        async def tool_error(tool, args, tool_context, error):
            await h.on_tool_error_callback(tool=tool, tool_args=args, tool_context=tool_context, error=error)

        ours = {"before_agent_callback": before_agent, "after_agent_callback": after_agent, "before_model_callback": before_model,
                "after_model_callback": after_model, "on_model_error_callback": model_error, "before_tool_callback": before_tool,
                "after_tool_callback": after_tool, "on_tool_error_callback": tool_error}
        for field, fn in ours.items():
            if not hasattr(a, field):  # a BaseAgent has only the two agent callbacks; an LlmAgent has all eight
                continue
            old = getattr(a, field)
            saved.append((a, field, old))
            setattr(a, field, [fn, *listify(old)])
        if include_sub_agents:
            for sub in getattr(a, "sub_agents", None) or []:
                install(sub)

    install(agent)

    def detach() -> None:
        for a, field, old in reversed(saved):
            setattr(a, field, old)

    return detach


def adk_tools(kit: Any) -> list[Any]:
    """The inert tools as ADK ``FunctionTool`` objects (``google/adk/tools/function_tool.py``), so a benchmark agent can be given tools that
    do nothing. Each function has the kit tool's name, docstring and typed parameters, which ADK reads to build the model-facing schema."""
    import inspect

    from google.adk.tools import FunctionTool

    kinds = {"str": str, "int": int, "float": float, "bool": bool}
    out = []
    for tool in kit.tools.values():
        params = [inspect.Parameter(p, inspect.Parameter.KEYWORD_ONLY, annotation=kinds[ty]) for p, ty in tool.params.items()]

        def run(*, _tool=tool, **kwargs: Any) -> str:
            return _tool(**kwargs)

        run.__name__ = tool.name
        run.__qualname__ = tool.name
        run.__doc__ = tool.description
        run.__signature__ = inspect.Signature(params, return_annotation=str)  # type: ignore[attr-defined]
        run.__annotations__ = {p.name: p.annotation for p in params} | {"return": str}
        out.append(FunctionTool(run))
    return out
