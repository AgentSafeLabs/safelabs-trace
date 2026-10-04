"""safelabs_trace/openai_agents_handler.py: OpenAI Agents SDK trace handler (third adapter; mirrors ``adk_handler.py``).

``import safelabs_trace.openai_agents_handler`` does not import ``agents``: the handler is plain Python that implements the SDK's run-hook callbacks
by name; ``as_run_hooks``, ``as_agent_hooks``, ``safe_run_config``, ``ensure_openai_export_off``, ``export_status`` and ``openai_agents_tools`` import the SDK
only when called. The module is not imported by ``safelabs_trace/__init__.py``.

Hook surface (openai-agents 0.18.0, VERIFIED in the installed package, paths relative to ``agents/``):

* ``RunHooksBase`` (``lifecycle.py:13``): ``on_llm_start(context, agent, system_prompt, input_items)`` (18), ``on_llm_end(context, agent, response)`` (28),
  ``on_agent_start(context, agent)`` (37), ``on_agent_end(context, agent, output)`` (46), ``on_handoff(context, from_agent, to_agent)`` (61),
  ``on_tool_start(context, agent, tool)`` (70), ``on_tool_end(context, agent, tool, result)`` (85). ``Runner.run(..., hooks=)`` (``run.py:206``) accepts only
  a ``RunHooks`` instance (``run_internal/turn_preparation.py:33-48``), so ``as_run_hooks`` wraps this handler in one.
* ``AgentHooksBase`` (``lifecycle.py:106``): ``on_start``, ``on_end``, ``on_handoff(context, agent, source)``, ``on_tool_start``, ``on_tool_end``, ``on_llm_start``,
  ``on_llm_end`` (113-193), attached with ``Agent(hooks=)`` (``agent.py:341``); ``as_agent_hooks`` wraps the handler for that path. Use one path, not both.
* There is no error hook: a failed run raises out of ``Runner.run``. ``run_traced`` and ``close_open_traces`` close the open trace.
* The SDK invokes run hooks and agent hooks inside ``asyncio.gather`` (``run_internal/run_loop.py:1325-1330``), i.e. in separate tasks, so a context variable
  set in one hook is not visible in the next. The run is therefore keyed by ``id(context.usage)``: the same ``Usage`` object is shared by every context of a run
  (observed). ``ToolContext.tool_call_id`` and ``tool_arguments`` (``tool_context.py:42-47``) carry the call id and the raw JSON arguments.
* Tool exceptions: a tool made with the default failure handling does not raise; the SDK returns an error string as the tool result
  (``tool.py:1609-1618``, timeout text ``tool.py:1629``) and calls ``on_tool_end``. The handler marks the call ``error`` or ``timeout`` when the result starts with
  one of those default messages (INFERRED; a custom failure function is not recognised). A tool whose failure propagates calls no ``on_tool_end``; the call is closed as an error by ``close_open_traces``.

Exporter safety (the contract; see ``export_status``, ``ensure_openai_export_off``, ``safe_run_config``): the SDK's default trace processor uploads every
trace to ``https://api.openai.com/v1/traces/ingest`` through ``BackendSpanExporter`` (``tracing/processors.py:33-34,107,167``) and is registered the first time
anything asks for the trace provider (``tracing/setup.py:39-66``). This handler configures no exporter of its own and by default (``strict=True``) refuses to
start a run while that export could still be active.

Never written to a trace: prompts, instructions, model text, tool arguments, tool results (only the writer's salted digests). The handler never raises into the
run, with one deliberate exception: ``OpenAIExportActiveError`` from the first agent hook when ``strict`` and the export could be active.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from importlib import metadata as _metadata
from typing import Any, Callable

from safelabs_trace import __version__ as PACKAGE_VERSION
from safelabs_trace._common import (
    build_agent_end, build_session_end, build_stop, build_tool_executed, build_tool_requested, remember_description, safe_emit, tags as _tags,
)
from safelabs_trace.schema import AgentRef, AgentStart, ModelCallEnd, ModelCallStart, SessionStart, Usage, build_event
from safelabs_trace.severity import TAGGER_VERSION, load_rules
from safelabs_trace.writer import TraceWriter

COVERAGE = {
    "session.start": "partial", "session.end": "partial", "agent.start": "emitted", "agent.end": "emitted",
    "model.call.start": "emitted", "model.call.end": "emitted", "tool.call.requested": "emitted", "tool.call.executed": "emitted",
    "plan.step": "not_exposed", "policy.decision": "not_exposed", "stop": "partial",
}  # session events come from the first and last agent hooks; stop reads an output-item status, not a finish reason

# Default tool failure texts of openai-agents 0.18.0 (agents/tool.py:1613-1618 and 1629). A test checks them against the installed functions.
_ERROR_PREFIXES = ("An error occurred while running the tool.", "An error occurred while parsing tool arguments.")
_TIMEOUT_RE = re.compile(r"^Tool '.*' timed out after ")
_DISABLE_ENV = "OPENAI_AGENTS_DISABLE_TRACING"  # a flag, not a key; the handler never reads any API key


class OpenAIExportActiveError(RuntimeError):
    """The SDK's default OpenAI trace export could still be active (strict mode refuses to start)."""


@dataclass(frozen=True)
class ExportStatus:
    active: bool  # True when the default OpenAI export could upload traces (fail-closed: True when it cannot be shown to be off)
    reasons: tuple[str, ...]


def _is_openai_exporter(processor: Any) -> bool:
    from agents.tracing.processors import BackendSpanExporter, BatchTraceProcessor
    if isinstance(processor, BackendSpanExporter):
        return True
    return isinstance(processor, BatchTraceProcessor) and isinstance(getattr(processor, "_exporter", None), BackendSpanExporter)


def export_status() -> ExportStatus:
    """Could the SDK's default OpenAI trace export upload traces right now? Looks at the global trace provider and nothing else
    (a per-run ``RunConfig`` cannot be seen from a hook). Never creates the default provider or exporter, and never reads an API key."""
    try:
        from agents.tracing import setup
        from agents.tracing.provider import DefaultTraceProvider
    except Exception as exc:  # noqa: BLE001
        return ExportStatus(True, (f"cannot inspect the SDK trace provider ({type(exc).__name__}); treated as active",))
    provider = setup.GLOBAL_TRACE_PROVIDER
    env_off = os.environ.get(_DISABLE_ENV, "false").lower() in ("true", "1")
    if provider is None:
        if env_off:
            return ExportStatus(False, (f"{_DISABLE_ENV} is set, so the provider will start disabled",))
        return ExportStatus(True, ("no trace provider exists yet: the SDK registers the default OpenAI exporter on first use (agents/tracing/setup.py:55-59)",))
    if not isinstance(provider, DefaultTraceProvider):
        return ExportStatus(True, (f"custom trace provider {type(provider).__name__}: cannot show that it does not export to OpenAI",))
    try:
        provider._refresh_disabled_flag()  # reads the env flag once, honours a manual set_tracing_disabled (tracing/provider.py:291-308)
        if provider._disabled:
            return ExportStatus(False, ("tracing is disabled globally, so no trace or span is created",))
        procs = provider._multi_processor._processors
    except Exception as exc:  # noqa: BLE001
        return ExportStatus(True, (f"cannot read the provider's state ({type(exc).__name__}); treated as active",))
    if any(_is_openai_exporter(p) for p in procs):
        return ExportStatus(True, ("tracing is enabled and a processor exports to the OpenAI backend (BackendSpanExporter)",))
    return ExportStatus(False, ("tracing is enabled but no OpenAI exporter is registered",))


def ensure_openai_export_off() -> ExportStatus:
    """Turn the default OpenAI trace export off for this process, using the SDK's public functions, and verify it.

    * No provider yet: install a fresh ``DefaultTraceProvider`` with no processor (``agents.tracing.set_trace_provider``, ``tracing/setup.py:27``), so the
      default exporter object is never created, then disable tracing.
    * A provider exists: disable tracing (``set_tracing_disabled``, ``tracing/__init__.py:108``; a manual flag outranks the env flag,
      ``tracing/provider.py:305-308``) and drop any processor that exports to OpenAI (``set_trace_processors``, ``tracing/__init__.py:101``).
    Other processors a program registered itself are kept. Raises ``OpenAIExportActiveError`` if the export still could be active."""
    from agents.tracing import set_trace_processors, set_tracing_disabled, set_trace_provider, setup
    from agents.tracing.provider import DefaultTraceProvider

    if setup.GLOBAL_TRACE_PROVIDER is None:
        set_trace_provider(DefaultTraceProvider())
    provider = setup.GLOBAL_TRACE_PROVIDER
    set_tracing_disabled(True)
    if isinstance(provider, DefaultTraceProvider):
        keep = [p for p in provider._multi_processor._processors if not _is_openai_exporter(p)]
        set_trace_processors(keep)
    status = export_status()
    if status.active:
        raise OpenAIExportActiveError("could not turn the OpenAI trace export off: " + "; ".join(status.reasons))
    return status


def safe_run_config(**overrides: Any) -> Any:
    """A ``RunConfig`` with tracing disabled, no per-run tracing key and sensitive-data capture off
    (``run_config.py:257,259-265``). Overrides may set other fields; weakening any of the three is refused."""
    from agents import RunConfig

    for field, bad in (("tracing_disabled", False), ("trace_include_sensitive_data", True)):
        if field in overrides and overrides[field] == bad:
            raise ValueError(f"safe_run_config refuses {field}={bad!r}")
    if overrides.get("tracing"):
        raise ValueError("safe_run_config refuses a per-run tracing config (it carries an export API key)")
    overrides.pop("tracing", None)
    return RunConfig(**{**overrides, "tracing_disabled": True, "trace_include_sensitive_data": False})


class OpenAIAgentsTraceHandler:
    """Writes trace events for OpenAI Agents SDK runs. Use ``Runner.run(agent, input, hooks=as_run_hooks(handler), run_config=safe_run_config())``
    or ``run_traced``; call ``ensure_openai_export_off()`` once at process start."""

    def __init__(self, writer: TraceWriter, *, trial: dict[str, str | int] | None = None, declared: dict[str, dict[str, Any]] | None = None,
                 overrides: dict[str, str] | None = None, unknown_default: str = "state_changing", rules: dict[str, Any] | None = None,
                 adapter: str = "openai_agents_handler", strict: bool = True) -> None:
        self.writer, self.trial, self.strict = writer, trial, strict
        self.declared, self.overrides, self.unknown_default = dict(declared or {}), dict(overrides or {}), unknown_default
        self.rules = rules if rules is not None else load_rules()
        self.adapter = adapter
        self.descriptions: dict[str, str] = {}  # tool name -> description, in memory only, for the tagger; never written to a trace
        self.errors: list[str] = []  # emission errors and, with strict=False, export warnings (prefixed WARNING)
        self.version = _agents_version()
        self._tr: dict[int, dict[str, Any]] = {}  # id(context.usage) -> trace state

    # ---- helpers -------------------------------------------------------------------------------------------
    def declare(self, name: str, hints: dict[str, Any]) -> None:
        """Declared hints for a tool (for example MCP-style annotations). The SDK's function tools carry none of their own."""
        self.declared[name] = dict(hints)

    def register_tools(self, tools: list[Any] | None) -> None:
        """Remember tool descriptions (in memory) so the tagger can use them; an agent's tools are also read when it starts."""
        for t in tools or []:
            remember_description(self.descriptions, getattr(t, "name", None), getattr(t, "description", None))

    def check_export_safe(self) -> ExportStatus:
        """Refuse (strict) or warn (not strict) when the default OpenAI export could be active."""
        status = export_status()
        if status.active:
            msg = "OpenAI trace export could be active: " + "; ".join(status.reasons) + ". Call ensure_openai_export_off() first."
            if self.strict:
                raise OpenAIExportActiveError(msg)
            self.errors.append("WARNING: " + msg)
        return status

    def _emit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return safe_emit(self.errors, fn, *args, **kwargs)

    def _write(self, st: dict[str, Any], event: Any) -> Any:
        self.writer.write(event)
        st["count"] += 1
        return event

    @staticmethod
    def _key(context: Any) -> int:
        return id(getattr(context, "usage", None) or context)

    def _begin(self, key: int, context: Any) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        st: dict[str, Any] = {"trace_id": trace_id, "session_id": trace_id, "t0": time.monotonic(), "count": 0, "session_start_id": None, "frame": None,
                              "handoff_from": None, "open_model": None, "last_model_end": None, "last_status": None, "pending": {}, "tools": {},
                              "_hold": getattr(context, "usage", None)}  # keep the key object alive so its id cannot be reused
        self._tr[key] = st
        self.writer.start_trace(trace_id, adapter=self.adapter, framework="openai-agents", framework_version=self.version, coverage=COVERAGE,
                                tagger_version=TAGGER_VERSION, rules_version=str(self.rules.get("rules_version", "")), package_version=PACKAGE_VERSION)
        s = self._write(st, build_event(SessionStart, {"session_id": "inferred"}, trace_id=trace_id, session_id=trace_id, trial=self.trial))  # the SDK has no session id
        st["session_start_id"] = s.event_id
        return st

    def _end_run(self, key: int, st: dict[str, Any], *, ok: bool, error: BaseException | None) -> None:
        self._write(st, build_session_end(trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=st["session_start_id"], ok=ok, error=error,
                                          t0=st["t0"], event_count=st["count"] + 1))
        self.writer.close_trace(st["trace_id"])
        self._tr.pop(key, None)

    def close_open_traces(self, error: BaseException | None = None) -> None:
        """Close every open trace as an error: in-flight tools get an error ``tool.call.executed``, then ``stop``, ``agent.end``, ``session.end``.
        Needed after a failed run (the SDK has no error hook); harmless when nothing is open."""
        for key, st in list(self._tr.items()):
            for call_id, t in list(st["tools"].items()):
                self._emit(self._tool_finished, st, call_id, "error", None, error)
            self._emit(self._finish_agent, st, ok=False, error=error, final=True)
            self._emit(self._end_run, key, st, ok=False, error=error)

    # ---- agents --------------------------------------------------------------------------------------------
    async def on_agent_start(self, context: Any, agent: Any) -> None:
        key = self._key(context)
        st = self._tr.get(key)
        if st is None:
            self.check_export_safe()  # strict: raises before any event is written and before the first model call
            st = self._emit(self._begin, key, context)
            if st is None:
                return
        self._emit(self._agent_start, st, agent)

    def _agent_start(self, st: dict[str, Any], agent: Any) -> None:
        src = st["handoff_from"]
        st["handoff_from"] = None
        name = getattr(agent, "name", None)
        self.register_tools(getattr(agent, "tools", None))
        vals = {"parent_agent_id": src["name"] if src else None}
        ev = self._write(st, build_event(AgentStart, _tags(vals), trace_id=st["trace_id"], session_id=st["session_id"],
                                         parent_event_id=src["event_id"] if src else st["session_start_id"], agent=AgentRef(name=name), **vals))
        st["frame"] = {"event_id": ev.event_id, "name": name}

    def _finish_agent(self, st: dict[str, Any], *, ok: bool, error: BaseException | None, final: bool, outcome: str | None = None) -> None:
        frame = st["frame"] or {"event_id": st["session_start_id"], "name": None}
        tid, sid = st["trace_id"], st["session_id"]
        if final:
            self._write(st, build_stop(trace_id=tid, session_id=sid, parent_event_id=frame["event_id"], raw=st["last_status"], raw_tag="inferred",
                                       source_event_id=st["last_model_end"]))
        self._write(st, build_agent_end(trace_id=tid, session_id=sid, parent_event_id=frame["event_id"], outcome=outcome or ("completed" if ok else "error"),
                                        error=error, agent_name=frame["name"]))

    async def on_agent_end(self, context: Any, agent: Any, output: Any) -> None:
        key = self._key(context)
        st = self._tr.get(key)
        if st is not None:
            self._emit(self._finish_agent, st, ok=True, error=None, final=True)
            self._emit(self._end_run, key, st, ok=True, error=None)

    async def on_handoff(self, context: Any, from_agent: Any, to_agent: Any) -> None:
        """A handoff ends the sending agent with outcome ``handoff`` and the receiving agent starts with ``parent_agent_id`` set to the sender:
        both fit existing fields. Handoff tool calls are not reported as tool calls."""
        st = self._tr.get(self._key(context))
        if st is not None:
            frame = st["frame"]
            self._emit(self._finish_agent, st, ok=True, error=None, final=False, outcome="handoff")
            st["handoff_from"] = frame

    # ---- model calls ---------------------------------------------------------------------------------------
    async def on_llm_start(self, context: Any, agent: Any, system_prompt: Any, input_items: Any) -> None:
        st = self._tr.get(self._key(context))
        if st is not None:
            self._emit(self._model_start, st, agent)

    def _model_start(self, st: dict[str, Any], agent: Any) -> None:
        m = getattr(agent, "model", None)
        model = m if isinstance(m, str) else getattr(m, "model", None)
        ms = getattr(agent, "model_settings", None)
        params = {k: v for k, v in (("temperature", getattr(ms, "temperature", None)), ("max_tokens", getattr(ms, "max_tokens", None))) if v is not None}
        tools = getattr(agent, "tools", None)
        offered = sorted(t.name for t in tools if isinstance(getattr(t, "name", None), str)) if isinstance(tools, list) else None
        vals = {"model_requested": model if isinstance(model, str) else None, "params": params or None, "tools_offered": offered}
        call_id = str(uuid.uuid4())  # the SDK has no model-call id
        frame = st["frame"]
        ev = self._write(st, build_event(ModelCallStart, _tags(vals, inferred=("model_requested", "params", "tools_offered")), trace_id=st["trace_id"],
                                         session_id=st["session_id"], parent_event_id=frame["event_id"] if frame else st["session_start_id"],
                                         call_id=call_id, **vals))
        st["open_model"] = {"event_id": ev.event_id, "call_id": call_id}

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        st = self._tr.get(self._key(context))
        if st is not None:
            self._emit(self._model_end, st, agent, response)

    @staticmethod
    def _handoff_names(agent: Any) -> set[str]:
        from agents.handoffs import Handoff
        names: set[str] = set()
        for h in getattr(agent, "handoffs", None) or []:
            names.add(h.tool_name if isinstance(h, Handoff) else Handoff.default_tool_name(h))
        return names

    def _model_end(self, st: dict[str, Any], agent: Any, response: Any) -> None:
        om = st["open_model"] or {"event_id": None, "call_id": str(uuid.uuid4())}
        st["open_model"] = None
        u = getattr(response, "usage", None)
        usage = None
        if u is not None:
            usage = Usage(input_tokens=getattr(u, "input_tokens", None), output_tokens=getattr(u, "output_tokens", None),
                          reasoning_tokens=getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None))
        items = list(getattr(response, "output", None) or [])
        handoff_names = self._handoff_names(agent)
        calls = [i for i in items if getattr(i, "type", None) == "function_call" and getattr(i, "name", None) not in handoff_names]
        if items:  # the SDK exposes no finish reason; the last output item's status is the closest signal (INFERRED)
            status = getattr(items[-1], "status", None)
            st["last_status"] = status if isinstance(status, str) else None
        vals = {"usage": usage, "tool_calls_requested_count": len(calls)}  # finish reason and returned model name are not exposed (null)
        end = self._write(st, build_event(ModelCallEnd, _tags(vals), trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=om["event_id"],
                                          call_id=om["call_id"], **vals))
        st["last_model_end"] = end.event_id
        for c in calls:
            self._request(st, c.name, self._parse_args(getattr(c, "arguments", None)), getattr(c, "call_id", None), end.event_id, om["call_id"],
                          observed_at="model_output")

    @staticmethod
    def _parse_args(raw: Any) -> Any:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except ValueError:
                return raw
            return parsed if isinstance(parsed, dict) else raw
        return None

    # ---- tools ---------------------------------------------------------------------------------------------
    def _request(self, st: dict[str, Any], name: str, args: Any, call_id: str | None, model_event: str | None, model_call: str | None, *, observed_at: str) -> Any:
        frame = st["frame"]
        ev, tagged = build_tool_requested(self.writer, trace_id=st["trace_id"], session_id=st["session_id"],
                                          parent_event_id=model_event or (frame["event_id"] if frame else st["session_start_id"]), name=name, args=args,
                                          call_id=call_id, model_call_id=model_call, observed_at=observed_at, declared=self.declared.get(name),
                                          overrides=self.overrides, rules=self.rules, unknown_default=self.unknown_default,
                                          description=self.descriptions.get(name))
        self._write(st, ev)
        st["pending"][call_id or ev.event_id] = (ev.event_id, tagged)
        return ev

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        st = self._tr.get(self._key(context))
        if st is not None:
            self._emit(self._tool_start, st, context, tool)

    def _tool_start(self, st: dict[str, Any], context: Any, tool: Any) -> None:
        name = getattr(tool, "name", None) or "unknown"
        self.register_tools([tool])
        call_id = getattr(context, "tool_call_id", None)
        req = st["pending"].pop(call_id, None) if call_id is not None else None
        if req is None:  # a tool ran with no request seen in a model response
            ev = self._request(st, name, self._parse_args(getattr(context, "tool_arguments", None)), call_id, None, None, observed_at="tool_start")
            req = st["pending"].pop(call_id or ev.event_id)
        st["tools"][call_id or req[0]] = {"name": name, "t0": time.monotonic(), "req": req, "call_id": call_id}

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any) -> None:
        st = self._tr.get(self._key(context))
        if st is None:
            return
        status = "success"
        if isinstance(result, str):  # the SDK returns default failure messages as results (see the module docstring)
            if result.startswith(_ERROR_PREFIXES):
                status = "error"
            elif _TIMEOUT_RE.match(result):
                status = "timeout"
        call_id = getattr(context, "tool_call_id", None)
        key = call_id if call_id in st["tools"] else next((k for k, v in st["tools"].items() if v["name"] == getattr(tool, "name", None)), None)
        if key is not None:
            self._emit(self._tool_finished, st, key, status, result, None)

    def _tool_finished(self, st: dict[str, Any], key: str, status: str, result: Any, error: BaseException | None) -> None:
        t = st["tools"].pop(key, None)
        if t is None:
            return
        req_id, tagged = t["req"]
        ev = build_tool_executed(self.writer, trace_id=st["trace_id"], session_id=st["session_id"], parent_event_id=req_id, requested_event_id=req_id,
                                 tool_name=t["name"], status=status, severity=tagged.severity, severity_basis=tagged.basis, tool_call_id=t["call_id"],
                                 result=result, capture_result=result is not None, error=error, t0=t["t0"])
        self._write(st, ev)


def _agents_version() -> str | None:
    try:
        return _metadata.version("openai-agents")
    except _metadata.PackageNotFoundError:
        return None


def as_run_hooks(handler: OpenAIAgentsTraceHandler) -> Any:
    """A ``RunHooks`` instance that forwards every callback to the handler (``Runner.run`` accepts only a ``RunHooks``; imports the SDK now)."""
    from agents import RunHooks

    class _TraceRunHooks(RunHooks):
        async def on_llm_start(self, context, agent, system_prompt, input_items):
            await handler.on_llm_start(context, agent, system_prompt, input_items)

        async def on_llm_end(self, context, agent, response):
            await handler.on_llm_end(context, agent, response)

        async def on_agent_start(self, context, agent):
            await handler.on_agent_start(context, agent)

        async def on_agent_end(self, context, agent, output):
            await handler.on_agent_end(context, agent, output)

        async def on_handoff(self, context, from_agent, to_agent):
            await handler.on_handoff(context, from_agent, to_agent)

        async def on_tool_start(self, context, agent, tool):
            await handler.on_tool_start(context, agent, tool)

        async def on_tool_end(self, context, agent, tool, result):
            await handler.on_tool_end(context, agent, tool, result)

    return _TraceRunHooks()


def as_agent_hooks(handler: OpenAIAgentsTraceHandler) -> Any:
    """An ``AgentHooks`` instance for ``Agent(hooks=...)`` (the per-agent path). It sees only that agent's events, so a handoff target needs its own."""
    from agents import AgentHooks

    class _TraceAgentHooks(AgentHooks):
        async def on_start(self, context, agent):
            await handler.on_agent_start(context, agent)

        async def on_end(self, context, agent, output):
            await handler.on_agent_end(context, agent, output)

        async def on_handoff(self, context, agent, source):
            await handler.on_handoff(context, source, agent)

        async def on_tool_start(self, context, agent, tool):
            await handler.on_tool_start(context, agent, tool)

        async def on_tool_end(self, context, agent, tool, result):
            await handler.on_tool_end(context, agent, tool, result)

        async def on_llm_start(self, context, agent, system_prompt, input_items):
            await handler.on_llm_start(context, agent, system_prompt, input_items)

        async def on_llm_end(self, context, agent, response):
            await handler.on_llm_end(context, agent, response)

    return _TraceAgentHooks()


async def run_traced(handler: OpenAIAgentsTraceHandler, agent: Any, input: Any, **kwargs: Any) -> Any:
    """``Runner.run`` with the handler as run hooks and ``safe_run_config()`` unless a ``run_config`` is given; on any exception the open trace is closed
    as an error and the exception is re-raised. Does not call ``ensure_openai_export_off``: call it once at process start."""
    from agents import Runner

    kwargs.setdefault("run_config", safe_run_config())
    kwargs["hooks"] = as_run_hooks(handler)
    try:
        return await Runner.run(agent, input, **kwargs)
    except BaseException as exc:
        handler.close_open_traces(exc)
        raise


def openai_agents_tools(kit: Any) -> list[Any]:
    """The inert tools as SDK ``FunctionTool`` objects (``agents.tool.FunctionTool``, ``tool.py:381``), so a benchmark agent can be given tools that do
    nothing. Each has the kit tool's name, description and a strict JSON schema built from its declared parameters."""
    from agents import FunctionTool

    kinds = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
    out = []
    for tool in kit.tools.values():
        schema = {"type": "object", "properties": {p: {"type": kinds[ty]} for p, ty in tool.params.items()}, "required": list(tool.params),
                  "additionalProperties": False}

        async def invoke(ctx: Any, args_json: str, _tool: Any = tool) -> str:
            return _tool(**json.loads(args_json or "{}"))

        out.append(FunctionTool(name=tool.name, description=tool.description, params_json_schema=schema, on_invoke_tool=invoke, strict_json_schema=True))
    return out
