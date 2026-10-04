import json

import pytest
from pydantic import ValidationError

from safelabs_trace.schema import (
    EVENT_TYPES, AgentEnd, AgentRef, AgentStart, Capture, HeaderEvent, ModelCallEnd, ModelCallStart, PlanStep, PolicyDecision, SessionEnd,
    SessionStart, Stop, ToolCallExecuted, ToolCallRequested, ToolInfo, TraceTruncated, Usage, build_event, dump_event, map_stop_reason,
    parse_event, to_line,
)
from tests.helpers import full_coverage

T = "trace-1"


def samples():
    cap = Capture(mode="digest", digest="0123456789abcdef", size=12, type="dict", keys=["a", "b"], salt_id="abcd1234")
    return [
        build_event(HeaderEvent, {"framework_version": "verified"}, trace_id=T, adapter="a", framework="f", framework_version="1.0", coverage=full_coverage(), salt_id="s"),
        build_event(SessionStart, {"session_id": "inferred"}, trace_id=T, session_id="s1", trial={"prompt_id": "P-1", "seed": 3}),
        build_event(AgentStart, {}, trace_id=T, agent=AgentRef(name="agent")),
        build_event(ModelCallStart, {"provider": "inferred", "tools_offered": "inferred"}, trace_id=T, call_id="c1", provider="p", tools_offered=[]),
        build_event(ModelCallEnd, {"usage": "verified", "finish_reason_raw": "inferred"}, trace_id=T, call_id="c1", usage=Usage(input_tokens=1, output_tokens=2), finish_reason_raw="stop"),
        build_event(ToolCallRequested, {"tool_call_id": "verified", "args": "verified"}, trace_id=T, tool_call_id="t1", tool=ToolInfo(name="x", declared={"readOnlyHint": False}),
                    args=cap, severity="state_changing", severity_basis="name_rule", rule_ids=["N-CHANGE"], flags={"egress": False}),
        build_event(ToolCallExecuted, {"tool_call_id": "verified", "duration_ms": "inferred", "result": "verified"}, trace_id=T, tool_call_id="t1", tool_name="x",
                    status="success", duration_ms=3, result=cap, severity="state_changing", severity_basis="name_rule"),
        build_event(PlanStep, {}, trace_id=T, source="s"),
        build_event(PolicyDecision, {"reason_code": "verified"}, trace_id=T, decision="deny", evaluator="deterministic", source="guard", reason_code="rule-1"),
        build_event(Stop, {"stop_raw": "verified"}, trace_id=T, stop_raw="stop", stop_status="end_of_turn"),
        build_event(AgentEnd, {}, trace_id=T, outcome="completed"),
        build_event(SessionEnd, {"duration_ms": "inferred"}, trace_id=T, reason="completed", duration_ms=5),
        TraceTruncated(trace_id=T, dropped_events=2, reason="trace limit", final=True),
    ]


@pytest.mark.parametrize("ev", samples(), ids=lambda e: e.type)
def test_round_trip_every_event_type(ev):
    d = dump_event(ev)
    assert parse_event(d) == ev
    assert parse_event(to_line(ev)) == ev
    assert d["schema"] == "safelabs-trace/0.1" and d["type"] == ev.type


def test_all_eleven_event_types_are_modelled_plus_header_and_marker():
    assert len(EVENT_TYPES) == 11
    types = {e.type for e in samples()}
    assert set(EVENT_TYPES) <= types and {"trace.header", "trace.truncated"} <= types


def test_none_stays_explicit_and_is_distinct_from_empty_list():
    s = samples()
    start, other = dump_event(s[3]), dump_event(build_event(ModelCallStart, {}, trace_id=T, call_id="c2"))
    assert start["tools_offered"] == [] and other["tools_offered"] is None
    assert "tools_offered" in other and "usage" in dump_event(s[4]) and "params" in other
    assert parse_event(other).tools_offered is None and parse_event(start).tools_offered == []


def test_provenance_rules():
    base = dict(trace_id=T, call_id="c")
    with pytest.raises(ValueError):  # a set field needs a tag
        build_event(ModelCallEnd, {}, finish_reason_raw="stop", **base)
    with pytest.raises(ValidationError):  # None with a verified tag
        ModelCallEnd(prov={"usage": "verified"}, **base)
    with pytest.raises(ValidationError):  # a field that is not tracked
        ModelCallEnd(prov={"call_id": "verified"}, **base)
    with pytest.raises(ValidationError):  # bad tag value
        ModelCallEnd(prov={"finish_reason_raw": "guess"}, finish_reason_raw="stop", **base)
    ev = build_event(ModelCallEnd, {}, **base)
    assert ev.prov["usage"] == "unknown" and ev.prov["finish_reason_raw"] == "unknown"
    ok = ModelCallEnd(prov={"finish_reason_raw": "inferred"}, finish_reason_raw="stop", **base)
    assert ok.prov["finish_reason_raw"] == "inferred"


def test_header_coverage_must_list_every_event_type():
    with pytest.raises(ValidationError):
        HeaderEvent(trace_id=T, adapter="a", framework="f", coverage={"stop": "emitted"})
    cov = full_coverage()
    cov["bogus.type"] = "emitted"
    with pytest.raises(ValidationError):
        HeaderEvent(trace_id=T, adapter="a", framework="f", coverage=cov)
    with pytest.raises(ValidationError):
        HeaderEvent(trace_id=T, adapter="a", framework="f", coverage=full_coverage(stop="maybe"))


def test_ids_links_and_envelope_defaults():
    a, b = samples()[1], samples()[2]
    assert a.event_id != b.event_id and len(a.event_id) == 36
    child = build_event(AgentStart, {}, trace_id=T, parent_event_id=a.event_id)
    assert child.parent_event_id == a.event_id and child.seq is None and child.truncated is False
    assert a.ts.endswith("+00:00") and "T" in a.ts


def test_unknown_type_and_extra_fields_are_rejected():
    d = dump_event(samples()[1])
    with pytest.raises(ValidationError):
        parse_event({**d, "type": "session.mystery"})
    with pytest.raises(ValidationError):
        parse_event({**d, "extra_field": 1})
    with pytest.raises(ValidationError):
        build_event(SessionEnd, {}, trace_id=T, reason="exploded")
    with pytest.raises(ValidationError):
        build_event(ToolCallRequested, {}, trace_id=T, tool=ToolInfo(name="x"), severity="harmless", severity_basis="name_rule")


def test_wire_line_is_one_json_object_without_newlines():
    line = to_line(samples()[5])
    assert "\n" not in line and json.loads(line)["tool"]["name"] == "x"


@pytest.mark.parametrize("raw,status", [("stop", "end_of_turn"), ("END_TURN", "end_of_turn"), ("length", "token_limit"), ("max_tokens", "token_limit"),
                                        ("tool_calls", "tool_use"), ("tool_use", "tool_use"), ("content_filter", "content_filter"), ("SAFETY", "content_filter"),
                                        ("weird", "other"), (None, "unknown")])
def test_stop_reason_mapping(raw, status):
    assert map_stop_reason(raw) == status
