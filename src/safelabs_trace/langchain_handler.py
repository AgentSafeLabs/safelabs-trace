"""safelabs_trace/langchain_handler.py: a LangChain callback handler that writes trace events.

Needs ``langchain-core`` (the ``langchain`` extra). Checked against langchain-core 1.4.0 (VERIFIED in the
installed package, paths relative to ``langchain_core/``):

* ``BaseCallbackHandler`` (``callbacks/base.py:496``), attributes ``raise_error`` (``:506``) and ``run_inline`` (``:509``);
* ``on_chain_start(serialized, inputs, *, run_id, parent_run_id, tags, metadata, **kwargs)`` (``:386``; ``serialized`` is
  None for a RunnableLambda, observed), ``on_chain_end`` (``:172``), ``on_chain_error`` (``:189``);
* ``on_chat_model_start(serialized, messages, *, run_id, parent_run_id, ...)`` (``:311``, ``invocation_params`` arrives in
  kwargs, ``language_models/chat_models.py:758,889``), ``on_llm_start`` (``:282``), ``on_llm_end(response, *, run_id,
  parent_run_id)`` (``:90``), ``on_llm_error`` (``:109``);
* ``on_tool_start(serialized, input_str, *, run_id, parent_run_id, inputs, **kwargs)`` (``:409``; ``tool_call_id`` arrives in
  kwargs, ``tools/base.py:942-950``), ``on_tool_end(output, *, run_id, parent_run_id)`` (``:244``), ``on_tool_error`` (``:261``);
* ``AIMessage.tool_calls`` (``messages/ai.py:170``) and ``usage_metadata`` (``:176``).

The handler never raises into the run: any error while emitting is recorded in ``handler.errors``. It sets
``run_inline = True`` so events are written in call order. One trace per root run; a bare chat model or a chain can
be the root. Tool arguments and results are captured through the writer (digest-only by default), and the severity
tagger runs on the in-memory arguments at tool-call time.
"""

from __future__ import annotations

import time
import uuid
from importlib import metadata as _metadata
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from safelabs_trace import __version__ as PACKAGE_VERSION
from safelabs_trace.schema import (
    AgentEnd, AgentStart, ModelCallEnd, ModelCallStart, SessionEnd, SessionStart, Stop, ToolCallExecuted, ToolCallRequested,
    ToolInfo, Usage, build_event, map_stop_reason,
)
from safelabs_trace.severity import TAGGER_VERSION, load_rules, tag_tool_call
from safelabs_trace.writer import TraceWriter

COVERAGE = {
    "session.start": "partial", "session.end": "partial", "agent.start": "partial", "agent.end": "partial",
    "model.call.start": "emitted", "model.call.end": "emitted", "tool.call.requested": "emitted", "tool.call.executed": "emitted",
    "plan.step": "not_exposed", "policy.decision": "not_exposed", "stop": "partial",
}  # session and agent events mark only the root run; stop reads a finish reason whose key varies by provider


def _tags(values: dict[str, Any], inferred: tuple[str, ...] = ()) -> dict[str, str]:
    """Provenance tags for the fields that have a value: ``verified`` unless the field is listed as inferred."""
    return {k: ("inferred" if k in inferred else "verified") for k, v in values.items() if v is not None}


def _name(serialized: Any, kwargs: dict[str, Any], default: str = "unknown") -> str:
    if kwargs.get("name"):
        return str(kwargs["name"])
    if isinstance(serialized, dict):
        if serialized.get("name"):
            return str(serialized["name"])
        ident = serialized.get("id")
        if isinstance(ident, list) and ident:
            return str(ident[-1])
    return default


class TraceCallbackHandler(BaseCallbackHandler):
    run_inline = True  # write events in call order, on the caller's thread
    raise_error = False

    def __init__(self, writer: TraceWriter, *, trial: dict[str, str | int] | None = None, declared: dict[str, dict[str, Any]] | None = None,
                 overrides: dict[str, str] | None = None, unknown_default: str = "state_changing", rules: dict[str, Any] | None = None,
                 adapter: str = "langchain_handler") -> None:
        self.writer, self.trial = writer, trial
        self.declared, self.overrides, self.unknown_default = dict(declared or {}), dict(overrides or {}), unknown_default
        self.rules = rules if rules is not None else load_rules()
        self.adapter = adapter
        self.errors: list[str] = []
        self.version = _lc_version()
        self._root: dict[UUID, UUID] = {}  # run_id -> root run id
        self._tr: dict[UUID, dict[str, Any]] = {}  # root run id -> trace state
        self._tool: dict[UUID, dict[str, Any]] = {}  # tool run id -> state

    # ---- helpers -------------------------------------------------------------------------------------------
    def register_tools(self, tools: list[Any]) -> None:
        """Read declared hints from ``BaseTool.metadata`` (langchain_core/tools/base.py:490)."""
        for t in tools:
            md = getattr(t, "metadata", None)
            if isinstance(md, dict) and md:
                self.declared[getattr(t, "name", "")] = md

    def _emit(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - tracing must never change the run
            self.errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
            return None

    def _state(self, run_id: UUID, parent_run_id: UUID | None) -> tuple[UUID, dict[str, Any] | None]:
        root = self._root.get(parent_run_id) if parent_run_id is not None else None
        root = root or run_id
        self._root[run_id] = root
        return root, self._tr.get(root)

    def _write(self, st: dict[str, Any], event: Any) -> Any:
        self.writer.write(event)
        st["count"] += 1
        return event

    def _begin(self, root: UUID, serialized: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        st = {"trace_id": trace_id, "session_id": trace_id, "t0": time.monotonic(), "count": 0, "last_model_call": None,
              "last_finish": None, "requested": {}, "agent_start_id": None, "session_start_id": None}
        self._tr[root] = st
        self.writer.start_trace(trace_id, adapter=self.adapter, framework="langchain-core", framework_version=self.version, coverage=COVERAGE,
                                tagger_version=TAGGER_VERSION, rules_version=str(self.rules.get("rules_version", "")), package_version=PACKAGE_VERSION)
        s = self._write(st, build_event(SessionStart, {"session_id": "inferred"}, trace_id=trace_id, session_id=trace_id, trial=self.trial))
        a = self._write(st, build_event(AgentStart, {}, trace_id=trace_id, session_id=trace_id, parent_event_id=s.event_id,
                                        agent={"name": _name(serialized, kwargs)}))
        st["session_start_id"], st["agent_start_id"] = s.event_id, a.event_id
        return st

    def _root_event_parent(self, st: dict[str, Any]) -> str | None:
        return st["agent_start_id"]

    def _finish_root(self, st: dict[str, Any], *, ok: bool, error: BaseException | None) -> None:
        tid, sid = st["trace_id"], st["session_id"]
        raw = st["last_finish"]
        self._write(st, build_event(Stop, {"stop_raw": "inferred"} if raw else {}, trace_id=tid, session_id=sid, parent_event_id=st["agent_start_id"],
                                    stop_raw=raw, stop_status=map_stop_reason(raw), source_event_id=st["last_model_call"]))
        et = type(error).__name__ if error is not None else None
        self._write(st, build_event(AgentEnd, {"error_type": "verified"} if et else {}, trace_id=tid, session_id=sid, parent_event_id=st["agent_start_id"],
                                    outcome="completed" if ok else "error", error_type=et))
        dur = int((time.monotonic() - st["t0"]) * 1000)
        self._write(st, build_event(SessionEnd, {"error_type": "verified", "duration_ms": "inferred", "event_count": "inferred"} if et else
                                    {"duration_ms": "inferred", "event_count": "inferred"}, trace_id=tid, session_id=sid,
                                    parent_event_id=st["session_start_id"], reason="completed" if ok else "error", error_type=et, duration_ms=dur,
                                    event_count=st["count"] + 1))
        self.writer.close_trace(tid)

    # ---- chains (root run only) ----------------------------------------------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):  # noqa: ANN001
        root, st = self._state(run_id, parent_run_id)
        if st is None and parent_run_id is None:
            self._emit(self._begin, root, serialized, kwargs)

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):  # noqa: ANN001
        if parent_run_id is None and run_id in self._tr:
            self._emit(self._finish_root, self._tr.pop(run_id), ok=True, error=None)

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):  # noqa: ANN001
        if parent_run_id is None and run_id in self._tr:
            self._emit(self._finish_root, self._tr.pop(run_id), ok=False, error=error)

    # ---- model calls ---------------------------------------------------------------------------------------
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):  # noqa: ANN001
        self._model_start(serialized, run_id, parent_run_id, {**kwargs, "metadata": metadata})

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):  # noqa: ANN001
        self._model_start(serialized, run_id, parent_run_id, {**kwargs, "metadata": metadata})

    def _model_start(self, serialized: Any, run_id: UUID, parent_run_id: UUID | None, kwargs: dict[str, Any]) -> None:
        root, st = self._state(run_id, parent_run_id)
        if st is None:
            st = self._emit(self._begin, root, serialized, kwargs)
            if st is None:
                return
            st["bare"] = True
        params = kwargs.get("invocation_params") or {}
        md = kwargs.get("metadata") or {}
        model = md.get("ls_model_name") or params.get("model") or params.get("model_name")
        provider = md.get("ls_provider") if isinstance(md.get("ls_provider"), str) else None
        tools = params.get("tools")
        offered = None
        if isinstance(tools, list):
            offered = [str((x.get("function") or x).get("name")) for x in tools if isinstance(x, dict) and (x.get("function") or x).get("name")]
        vals = {"provider": provider, "model_requested": model, "tools_offered": offered}
        ev = build_event(ModelCallStart, _tags(vals, inferred=("provider", "model_requested", "tools_offered")), trace_id=st["trace_id"],
                         session_id=st["session_id"], parent_event_id=st["agent_start_id"], call_id=str(run_id), **vals)
        self._emit(self._write, st, ev)
        st.setdefault("calls", {})[run_id] = ev.event_id

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):  # noqa: ANN001
        root = self._root.get(run_id)
        st = self._tr.get(root) if root else None
        if st is not None:
            self._emit(self._model_end, st, response, run_id, root == run_id)
            self._finish_if_root(run_id, ok=True, error=None)

    def _model_end(self, st: dict[str, Any], response: Any, run_id: UUID, is_root: bool) -> None:
        msg = None
        try:
            msg = response.generations[0][0].message
        except Exception:  # noqa: BLE001 - a plain LLM result has no message
            pass
        gen_info = {}
        try:
            gen_info = response.generations[0][0].generation_info or {}
        except Exception:  # noqa: BLE001
            pass
        meta = getattr(msg, "response_metadata", None) or {}
        raw = next((meta[k] for k in ("finish_reason", "stop_reason") if isinstance(meta.get(k), str) and meta[k]), None)
        raw = raw or (gen_info.get("finish_reason") if isinstance(gen_info.get("finish_reason"), str) else None)
        um = getattr(msg, "usage_metadata", None)
        usage = None
        if isinstance(um, dict):
            usage = Usage(input_tokens=um.get("input_tokens"), output_tokens=um.get("output_tokens"),
                          reasoning_tokens=(um.get("output_token_details") or {}).get("reasoning"))
        calls = getattr(msg, "tool_calls", None)
        returned = meta.get("model_name") or meta.get("model")
        vals = {"model_returned": returned, "usage": usage, "finish_reason_raw": raw, "tool_calls_requested_count": len(calls) if calls is not None else None}
        end = build_event(ModelCallEnd, _tags(vals, inferred=("finish_reason_raw",)), trace_id=st["trace_id"], session_id=st["session_id"],
                          parent_event_id=st.get("calls", {}).get(run_id), call_id=str(run_id), **vals)
        self._write(st, end)
        st["last_model_call"], st["last_finish"] = end.event_id, raw
        for tc in calls or []:
            self._request(st, tc.get("name", ""), tc.get("args"), tc.get("id"), end.event_id, str(run_id), observed_at="model_output")

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):  # noqa: ANN001
        root = self._root.get(run_id)
        st = self._tr.get(root) if root else None
        if st is None:
            return
        et = type(error).__name__
        end = build_event(ModelCallEnd, {"error_type": "verified"}, trace_id=st["trace_id"], session_id=st["session_id"],
                          parent_event_id=st.get("calls", {}).get(run_id), call_id=str(run_id), error_type=et)
        self._emit(self._write, st, end)
        if root == run_id:  # a bare model call is the root run
            self._emit(self._finish_root, self._tr.pop(root), ok=False, error=error)

    # ---- tools ---------------------------------------------------------------------------------------------
    def _request(self, st: dict[str, Any], name: str, args: Any, call_id: str | None, model_event: str | None, model_call: str | None, *, observed_at: str) -> Any:
        tagged = tag_tool_call(name, args if isinstance(args, dict) else None, self.declared.get(name), overrides=self.overrides, rules=self.rules,
                               unknown_default=self.unknown_default)
        eid = str(uuid.uuid4())
        cap = self.writer.capture_value(args, trace_id=st["trace_id"], event_id=eid, kind="args") if args is not None else None
        tags = _tags({"tool_call_id": call_id, "model_call_id": model_call, "args": cap}, inferred=("tool_call_id",) if observed_at == "tool_start" else ())
        if tagged.capability_hint is not None:
            tags["capability_hint"] = "inferred"
        ev = build_event(ToolCallRequested, tags, trace_id=st["trace_id"], event_id=eid, session_id=st["session_id"], parent_event_id=model_event or st["agent_start_id"],
                         tool_call_id=call_id, model_call_id=model_call, observed_at=observed_at,
                         tool=ToolInfo(name=name, declared=self.declared.get(name)), args=cap, severity=tagged.severity, severity_basis=tagged.basis,
                         rule_ids=list(tagged.rule_ids), flags=tagged.flags, capability_hint=tagged.capability_hint)
        self._write(st, ev)
        st["requested"][call_id or eid] = (ev.event_id, tagged)
        return ev

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):  # noqa: ANN001
        root, st = self._state(run_id, parent_run_id)
        if st is None:
            st = self._emit(self._begin, root, serialized, kwargs)
            if st is None:
                return
        name = _name(serialized, kwargs)
        call_id = kwargs.get("tool_call_id")
        args = inputs if isinstance(inputs, dict) else None
        known = st["requested"].get(call_id) if call_id else None
        if known is None:
            ev = self._emit(self._request, st, name, args if args is not None else input_str, call_id, None, None, observed_at="tool_start")
            known = st["requested"].get(call_id or (ev.event_id if ev else None))
        self._tool[run_id] = {"call_id": call_id, "name": name, "t0": time.monotonic(), "requested": known, "st": st}

    def _executed(self, run_id: UUID, status: str, output: Any, error: BaseException | None) -> None:
        t = self._tool.pop(run_id, None)
        if t is None:
            return
        st = t["st"]
        req_id, tagged = t["requested"] if t["requested"] else (None, None)
        sev, basis = (tagged.severity, tagged.basis) if tagged else ("state_changing", "default_unknown")
        eid = str(uuid.uuid4())
        content = getattr(output, "content", output)
        res = self.writer.capture_value(content, trace_id=st["trace_id"], event_id=eid, kind="result") if output is not None else None
        et = type(error).__name__ if error is not None else None
        if isinstance(error, TimeoutError):
            status = "timeout"
        dur = int((time.monotonic() - t["t0"]) * 1000)
        vals = {"tool_call_id": t["call_id"], "error_type": et, "duration_ms": dur, "result": res}
        tags = _tags(vals, inferred=("duration_ms",))
        ev = build_event(ToolCallExecuted, tags, trace_id=st["trace_id"], event_id=eid, session_id=st["session_id"], parent_event_id=req_id or st["agent_start_id"],
                         requested_event_id=req_id, tool_name=t["name"], status=status, severity=sev, severity_basis=basis, **vals)
        self._write(st, ev)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):  # noqa: ANN001
        self._emit(self._executed, run_id, "success", output, None)
        self._finish_if_root(run_id, ok=True, error=None)

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):  # noqa: ANN001
        self._emit(self._executed, run_id, "error", None, error)
        self._finish_if_root(run_id, ok=False, error=error)

    def _finish_if_root(self, run_id: UUID, *, ok: bool, error: BaseException | None) -> None:
        """A bare model call or a bare tool call is its own root run; close its trace when it ends."""
        if self._root.get(run_id) == run_id and run_id in self._tr:
            self._emit(self._finish_root, self._tr.pop(run_id), ok=ok, error=error)


def _lc_version() -> str | None:
    try:
        return _metadata.version("langchain-core")
    except _metadata.PackageNotFoundError:
        return None


def langchain_tools(kit: Any) -> list[Any]:
    """Real ``StructuredTool`` objects (``StructuredTool.from_function``, ``langchain_core/tools/structured.py:133``) that wrap
    the inert tools, so a LangChain agent can call them. The argument schema is built from the kit's declared parameters."""
    from pydantic import create_model

    from langchain_core.tools import StructuredTool

    kinds = {"str": str, "int": int, "float": float, "bool": bool}
    out = []
    for tool in kit.tools.values():
        schema = create_model(f"{tool.name}_args", **{p: (kinds[ty], ...) for p, ty in tool.params.items()})

        def run(_tool=tool, **kwargs: Any) -> str:
            return _tool(**kwargs)

        out.append(StructuredTool.from_function(func=run, name=tool.name, description=tool.description, args_schema=schema))
    return out
