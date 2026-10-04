"""safelabs_trace/_common.py: code the framework handlers share (moved out of ``langchain_handler.py`` and ``adk_handler.py``; behaviour unchanged).

Everything here builds or tags events; nothing here imports a framework. The handlers keep their own state and decide when to write.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from safelabs_trace.schema import (
    AgentEnd, AgentRef, SessionEnd, Stop, ToolCallExecuted, ToolCallRequested, ToolInfo, build_event, map_stop_reason,
)
from safelabs_trace.severity import Tagged, tag_tool_call


def tags(values: dict[str, Any], inferred: tuple[str, ...] = ()) -> dict[str, str]:
    """Provenance tags for the fields that have a value: ``verified`` unless the field is listed as inferred."""
    return {k: ("inferred" if k in inferred else "verified") for k, v in values.items() if v is not None}


def remember_description(store: dict[str, str], name: Any, description: Any) -> None:
    """Keep a tool description in memory (never written to a trace) for the tagger. Ignores non-strings and empty values."""
    if isinstance(name, str) and name and isinstance(description, str) and description.strip():
        store[name] = description[:2000]


def safe_emit(errors: list[str], fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run ``fn``; on any exception record ``Type: message`` (200 characters) in ``errors`` and return None. Tracing never changes a run."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
        return None


def build_tool_requested(writer: Any, *, trace_id: str, session_id: str | None, parent_event_id: str | None, name: str, args: Any, call_id: str | None,
                         model_call_id: str | None, observed_at: str, declared: dict[str, Any] | None, overrides: dict[str, str] | None,
                         rules: dict[str, Any] | None, unknown_default: str, description: str | None = None) -> tuple[ToolCallRequested, Tagged]:
    """Tag a tool call (on the in-memory arguments) and build its ``tool.call.requested`` event. The arguments are captured through the
    writer (digest-only by default) and never stored. Returns (event, tagging result); the caller writes the event.
    ``description`` (the tool description, in memory) goes to the tagger only; it is never part of the event."""
    tagged = tag_tool_call(name, args if isinstance(args, dict) else None, declared, overrides=overrides, rules=rules, unknown_default=unknown_default,
                           description=description)
    eid = str(uuid.uuid4())
    cap = writer.capture_value(args, trace_id=trace_id, event_id=eid, kind="args") if args is not None else None
    prov = tags({"tool_call_id": call_id, "model_call_id": model_call_id, "args": cap}, inferred=("tool_call_id",) if observed_at == "tool_start" else ())
    if tagged.capability_hint is not None:
        prov["capability_hint"] = "inferred"
    ev = build_event(ToolCallRequested, prov, trace_id=trace_id, event_id=eid, session_id=session_id, parent_event_id=parent_event_id,
                     tool_call_id=call_id, model_call_id=model_call_id, observed_at=observed_at, tool=ToolInfo(name=name, declared=declared), args=cap,
                     severity=tagged.severity, severity_basis=tagged.basis, rule_ids=list(tagged.rule_ids), flags=tagged.flags,
                     capability_hint=tagged.capability_hint)
    return ev, tagged  # type: ignore[return-value]


def build_tool_executed(writer: Any, *, trace_id: str, session_id: str | None, parent_event_id: str | None, requested_event_id: str | None, tool_name: str,
                        status: str, severity: str, severity_basis: str, tool_call_id: str | None, result: Any, capture_result: bool,
                        error: BaseException | None, t0: float, error_type: str | None = None) -> ToolCallExecuted:
    """Build ``tool.call.executed``. ``t0`` is a ``time.monotonic()`` start; a ``TimeoutError`` makes the status ``timeout``. The result is
    captured through the writer only when ``capture_result`` is true. ``error_type`` overrides the type read from ``error``."""
    eid = str(uuid.uuid4())
    res = writer.capture_value(result, trace_id=trace_id, event_id=eid, kind="result") if capture_result else None
    et = type(error).__name__ if error is not None else error_type
    if isinstance(error, TimeoutError):
        status = "timeout"
    vals = {"tool_call_id": tool_call_id, "error_type": et, "duration_ms": int((time.monotonic() - t0) * 1000), "result": res}
    return build_event(ToolCallExecuted, tags(vals, inferred=("duration_ms",)), trace_id=trace_id, event_id=eid, session_id=session_id,
                       parent_event_id=parent_event_id, requested_event_id=requested_event_id, tool_name=tool_name, status=status,
                       severity=severity, severity_basis=severity_basis, **vals)  # type: ignore[return-value]


def build_stop(*, trace_id: str, session_id: str | None, parent_event_id: str | None, raw: str | None, raw_tag: str, source_event_id: str | None) -> Stop:
    """``stop`` with the unified status mapped from the raw reason; ``raw_tag`` is how the raw value was obtained (verified or inferred)."""
    return build_event(Stop, {"stop_raw": raw_tag} if raw else {}, trace_id=trace_id, session_id=session_id, parent_event_id=parent_event_id,
                       stop_raw=raw, stop_status=map_stop_reason(raw), source_event_id=source_event_id)  # type: ignore[return-value]


def build_agent_end(*, trace_id: str, session_id: str | None, parent_event_id: str | None, outcome: str, error: BaseException | None = None,
                    agent_name: str | None = None, error_type: str | None = None) -> AgentEnd:
    et = type(error).__name__ if error is not None else error_type
    extra = {"agent": AgentRef(name=agent_name)} if agent_name is not None else {}
    return build_event(AgentEnd, tags({"error_type": et}), trace_id=trace_id, session_id=session_id, parent_event_id=parent_event_id,
                       outcome=outcome, error_type=et, **extra)  # type: ignore[return-value]


def build_session_end(*, trace_id: str, session_id: str | None, parent_event_id: str | None, ok: bool, error: BaseException | None, t0: float,
                      event_count: int) -> SessionEnd:
    et = type(error).__name__ if error is not None else None
    vals = {"error_type": et, "duration_ms": int((time.monotonic() - t0) * 1000), "event_count": event_count}
    return build_event(SessionEnd, tags(vals, inferred=("duration_ms", "event_count")), trace_id=trace_id, session_id=session_id,
                       parent_event_id=parent_event_id, reason="completed" if ok else "error", **vals)  # type: ignore[return-value]
