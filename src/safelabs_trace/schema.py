"""safelabs_trace/schema.py: the trace event model (design.md section E1).

One JSONL line is one event. The first line of every trace is a ``trace.header`` whose ``coverage``
manifest says, per event type, whether the adapter can emit it. Rules:

* None means not exposed by the framework; an empty list or a zero count means exposed and nothing
  occurred (the same rule ``safelabs.agents.schemas.AgentResponse`` uses).
* Each event type names the fields whose origin matters (``TRACKED``). ``prov`` maps each tracked field
  that has a value to ``verified`` (read directly from a framework object) or ``inferred`` (derived or
  mapped); a tracked field that is None must be absent or ``unknown``.
* Events observe only. They never carry tool arguments, tool results or model text, only a
  ``Capture`` (digest, size, type, key names, and for opt-in full capture a reference to a local file).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

SCHEMA_VERSION = "safelabs-trace/0.1"

Prov = Literal["verified", "inferred", "unknown"]
Severity = Literal["read_only", "state_changing", "irreversible"]
SeverityBasis = Literal["manual", "declared", "argument_rule", "name_rule", "default_unknown"]
CoverageState = Literal["emitted", "partial", "not_exposed"]
StopStatus = Literal["end_of_turn", "token_limit", "tool_use", "session_stop", "content_filter", "other", "unknown"]

#: The 11 event types of the design (the header and the truncation marker are control records).
EVENT_TYPES = (
    "session.start", "session.end", "agent.start", "agent.end", "model.call.start", "model.call.end",
    "tool.call.requested", "tool.call.executed", "plan.step", "policy.decision", "stop",
)

# Raw provider stop reason to the unified status. INFERRED mapping (design.md E1.2); the raw value is always kept.
_STOP_MAP = {
    "stop": "end_of_turn", "end_turn": "end_of_turn", "stop_sequence": "end_of_turn", "completed": "end_of_turn",
    "length": "token_limit", "max_tokens": "token_limit", "max_output_tokens": "token_limit",
    "tool_calls": "tool_use", "tool_use": "tool_use", "function_call": "tool_use",
    "content_filter": "content_filter", "safety": "content_filter", "refusal": "content_filter",
}


def map_stop_reason(raw: str | None) -> str:
    """Unified stop status for a raw stop reason (case-insensitive); None gives unknown, unmapped gives other."""
    if raw is None:
        return "unknown"
    return _STOP_MAP.get(str(raw).strip().lower(), "other")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AgentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    name: str | None = None


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


class ToolInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str | None = None  # OTel gen_ai.tool.type vocabulary: function, extension, datastore
    declared: dict[str, Any] | None = None  # declared hints (for example MCP annotations); None = none declared or not exposed


class Capture(BaseModel):
    """What the trace keeps of a tool argument set or result. Never the content in the default modes."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["none", "digest", "full"]
    digest: str | None = None  # salted HMAC-SHA-256, truncated; None only in mode none
    size: int | None = None  # canonical byte length
    type: str | None = None  # python type name
    keys: list[str] | None = None  # sorted argument names for a dict
    ref: str | None = None  # full mode only: "<file>#<event_id>:<kind>"
    salt_id: str | None = None  # identifies the salt, never the salt


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    TRACKED: ClassVar[tuple[str, ...]] = ()

    schema_version: str = Field(default=SCHEMA_VERSION, alias="schema")
    type: str
    trace_id: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_event_id: str | None = None
    seq: int | None = None  # assigned by the writer, per trace
    ts: str = Field(default_factory=_now)
    session_id: str | None = None
    turn_id: str | None = None
    agent: AgentRef | None = None
    truncated: bool = False
    prov: dict[str, Prov] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_prov(self) -> "TraceEvent":
        tracked = set(self.TRACKED) | {"ts"}
        bad = sorted(set(self.prov) - tracked)
        if bad:
            raise ValueError(f"prov has field(s) that are not tracked for {self.type}: {bad}")
        for name in self.TRACKED:
            value, tag = getattr(self, name), self.prov.get(name)
            if value is None:
                if tag not in (None, "unknown"):
                    raise ValueError(f"{name} is None, so its prov must be unknown or absent, not {tag!r}")
            elif tag not in ("verified", "inferred"):
                raise ValueError(f"{name} is set, so its prov must be verified or inferred, not {tag!r}")
        if "ts" in self.prov and self.prov["ts"] not in ("verified", "inferred"):
            raise ValueError("prov for ts must be verified or inferred")
        return self


class HeaderEvent(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("framework_version",)
    type: Literal["trace.header"] = "trace.header"
    adapter: str
    framework: str
    framework_version: str | None = None
    coverage: dict[str, CoverageState]
    capture: Literal["none", "digest", "full"] = "digest"
    tagger_version: str | None = None
    rules_version: str | None = None
    salt_id: str | None = None
    package_version: str | None = None

    @model_validator(mode="after")
    def _check_coverage(self) -> "HeaderEvent":
        missing = sorted(set(EVENT_TYPES) - set(self.coverage))
        extra = sorted(set(self.coverage) - set(EVENT_TYPES))
        if missing or extra:
            raise ValueError(f"coverage must list exactly the 11 event types (missing {missing}, unknown {extra})")
        return self


class SessionStart(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("session_id",)
    type: Literal["session.start"] = "session.start"
    trial: dict[str, str | int] | None = None  # caller-supplied label (prompt id, seed), not a framework fact


class SessionEnd(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("error_type", "duration_ms", "event_count")
    type: Literal["session.end"] = "session.end"
    reason: Literal["completed", "error", "timeout", "cancelled", "abandoned"]
    error_type: str | None = None
    duration_ms: int | None = None
    event_count: int | None = None


class AgentStart(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("parent_agent_id",)
    type: Literal["agent.start"] = "agent.start"
    parent_agent_id: str | None = None


class AgentEnd(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("error_type",)
    type: Literal["agent.end"] = "agent.end"
    outcome: Literal["completed", "error", "interrupted", "handoff"]
    error_type: str | None = None


class ModelCallStart(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("provider", "model_requested", "params", "tools_offered")
    type: Literal["model.call.start"] = "model.call.start"
    call_id: str
    provider: str | None = None
    model_requested: str | None = None
    params: dict[str, Any] | None = None
    tools_offered: list[str] | None = None  # names; None = not exposed, [] = exposed, none offered


class ModelCallEnd(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("model_returned", "usage", "finish_reason_raw", "tool_calls_requested_count", "error_type")
    type: Literal["model.call.end"] = "model.call.end"
    call_id: str
    model_returned: str | None = None
    usage: Usage | None = None
    finish_reason_raw: str | None = None
    tool_calls_requested_count: int | None = None
    error_type: str | None = None


class ToolCallRequested(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("tool_call_id", "model_call_id", "args", "capability_hint")
    type: Literal["tool.call.requested"] = "tool.call.requested"
    tool_call_id: str | None = None
    model_call_id: str | None = None
    observed_at: Literal["model_output", "tool_start"] = "model_output"
    tool: ToolInfo
    args: Capture | None = None
    severity: Severity
    severity_basis: SeverityBasis
    rule_ids: list[str] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)
    capability_hint: str | None = None


class ToolCallExecuted(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("tool_call_id", "error_type", "duration_ms", "result", "from_cache")
    type: Literal["tool.call.executed"] = "tool.call.executed"
    tool_call_id: str | None = None
    requested_event_id: str | None = None
    tool_name: str
    status: Literal["success", "error", "timeout", "blocked"]
    error_type: str | None = None
    duration_ms: int | None = None
    result: Capture | None = None
    from_cache: bool | None = None
    severity: Severity
    severity_basis: SeverityBasis


class PlanStep(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("text_digest", "text_len")
    type: Literal["plan.step"] = "plan.step"
    step_index: int | None = None
    source: str
    text_digest: str | None = None
    text_len: int | None = None


class PolicyDecision(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("reason_code",)
    type: Literal["policy.decision"] = "policy.decision"
    decision: Literal["allow", "deny", "modify", "ask", "defer"]
    evaluator: Literal["deterministic", "agent", "composite", "human", "unknown"] = "unknown"
    source: str
    target_event_id: str | None = None
    reason_code: str | None = None


class Stop(TraceEvent):
    TRACKED: ClassVar[tuple[str, ...]] = ("stop_raw",)
    type: Literal["stop"] = "stop"
    stop_raw: str | None = None
    stop_status: StopStatus = "unknown"
    source_event_id: str | None = None


class TraceTruncated(TraceEvent):
    type: Literal["trace.truncated"] = "trace.truncated"
    dropped_events: int
    reason: str
    final: bool = False


Event = Annotated[
    Union[HeaderEvent, SessionStart, SessionEnd, AgentStart, AgentEnd, ModelCallStart, ModelCallEnd, ToolCallRequested,
          ToolCallExecuted, PlanStep, PolicyDecision, Stop, TraceTruncated],
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter = TypeAdapter(Event)
EVENT_CLASSES = {c.model_fields["type"].default: c for c in (
    HeaderEvent, SessionStart, SessionEnd, AgentStart, AgentEnd, ModelCallStart, ModelCallEnd, ToolCallRequested,
    ToolCallExecuted, PlanStep, PolicyDecision, Stop, TraceTruncated)}


def build_event(cls: type[TraceEvent], tags: dict[str, Prov] | None = None, **fields: Any) -> TraceEvent:
    """Build an event and complete ``prov`` explicitly: every tracked field that has a value needs a tag in
    ``tags`` (no silent default); tracked fields that are None are recorded as unknown."""
    tags = dict(tags or {})
    prov: dict[str, Prov] = {}
    for name in cls.TRACKED:
        if fields.get(name) is None:
            prov[name] = "unknown"
        elif name in tags:
            prov[name] = tags[name]
        else:
            raise ValueError(f"{cls.__name__}: field {name} is set but has no provenance tag")
    if "ts" in tags:
        prov["ts"] = tags["ts"]
    return cls(prov=prov, **fields)


def parse_event(data: dict[str, Any] | str) -> TraceEvent:
    """Parse one JSON object (or line) into its typed event."""
    return _ADAPTER.validate_python(json.loads(data) if isinstance(data, str) else data)


def dump_event(event: TraceEvent) -> dict[str, Any]:
    """JSON-ready dict with every field present (None stays explicit), using the wire name ``schema``."""
    return event.model_dump(mode="json", by_alias=True)


def to_line(event: TraceEvent) -> str:
    return json.dumps(dump_event(event), ensure_ascii=False, separators=(",", ":"))
