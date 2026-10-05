"""Deterministic fake models, one per framework, for offline runs and tests. No network, no key, nothing real.

A fake model is driven by a framework-neutral *script* of steps, one per model call:
  ("calls", [(tool_name, args), ...])   the model asks for tool calls
  ("text", str)                         the model answers
  ("error", exception)                  the call fails (RateLimitError-like, status 429, retried by the harness)
The behaviours (what the fake "model" does for a trial) are:
  refuse_no_tool             refusal text, no tool call
  refuse_irreversible_tool   calls an irreversible tool, then refuses in text            -> a hidden action
  comply_tool                calls a state-changing tool, then complies in text
  comply_no_tool             complies in text only                                        -> talk-only
  cap_loop                   keeps requesting a read-only tool until the call cap stops it
  silent_irreversible        calls an irreversible tool, then ends with an EMPTY final message  -> tool_call_only, scored UNCERTAIN (added after the smoke run)
  unclear_text               answers in text that has neither marker (no tool call)             -> UNCERTAIN with text (added after the smoke run)
Modifiers: ``fail_attempts: n`` makes the first n attempts of a pass fail with a transient error; ``fail_passes: [0]`` makes every attempt of
those passes fail (pass 0 is the initial run, 1 the first --rerun-missing pass), which leaves a missing_infrastructure row for a rerun to fill.
Texts carry the markers FAKE-REFUSE / FAKE-COMPLY, which the ``fake_marker`` scorer reads (PASS / FAIL); the real scorer is not used offline.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field
from typing import Any, Iterator

REFUSE_TEXT = "FAKE-REFUSE I cannot help with that request."
COMPLY_TEXT = "FAKE-COMPLY Done, I have carried that out."
UNCLEAR_TEXT = "I am not sure what you are asking."
KINDS = ("refuse_no_tool", "refuse_irreversible_tool", "comply_tool", "comply_no_tool", "cap_loop", "silent_irreversible", "unclear_text")
DEFAULT_MIX = ("refuse_no_tool", "refuse_irreversible_tool", "comply_tool", "comply_no_tool", "refuse_no_tool+transient", "comply_tool+persistent_first_pass")
DEFAULT_TOOL = {
    "refuse_irreversible_tool": ("fs_delete_file", {"path": "/data/records.db"}),
    "silent_irreversible": ("fs_delete_file", {"path": "/data/records.db"}),
    "comply_tool": ("fs_write_file", {"path": "/out/notes.txt", "content": "note"}),
    "cap_loop": ("lookup_order", {"order_id": "o-1"}),
}


class RateLimitError(Exception):
    """Named like the providers' rate-limit error so safelabs.agents.errors classifies it as an infrastructure error."""

    status_code = 429


@dataclass
class Behaviour:
    kind: str
    tool: str | None = None
    args: dict[str, Any] | None = None
    fail_attempts: int = 0
    fail_passes: tuple[int, ...] = ()
    tokens_in: int = 800
    tokens_out: int = 60


def _pick(key: str, options: tuple[str, ...]) -> str:
    return options[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)]


class FakeProvider:
    """Resolves a behaviour per trial and builds the native fake model for a framework."""

    def __init__(self, plan: dict[str, Any] | None = None) -> None:
        self.plan = plan or {}
        self.built: list[tuple[str, str]] = []  # (framework, trial_id) for every fake model built (tests read it)

    def behaviour(self, trial_id: str, prompt_id: str, model: str, framework: str, seed: int) -> Behaviour:
        p = self.plan
        spec = (p.get("by_trial") or {}).get(trial_id) or (p.get("by_prompt") or {}).get(prompt_id)
        if spec is None:
            spec = _pick(f"{p.get('seed', 0)}|{prompt_id}|{model}|{framework}|{seed}", tuple(p.get("mix") or DEFAULT_MIX))
        if isinstance(spec, str):
            spec = {"kind": spec}
        spec = dict(spec)
        kind, _, mod = spec.pop("kind").partition("+")
        if mod == "transient":
            spec.setdefault("fail_attempts", 1)
        elif mod == "persistent_first_pass":
            spec.setdefault("fail_passes", (0,))
        elif mod:
            raise ValueError(f"unknown fake modifier {mod!r}")
        if kind not in KINDS:
            raise ValueError(f"unknown fake behaviour {kind!r}")
        tool, args = DEFAULT_TOOL.get(kind, (None, None))
        toks = p.get("tokens") or {}
        return Behaviour(kind=kind, tool=spec.get("tool", tool), args=spec.get("args", args), fail_attempts=int(spec.get("fail_attempts", 0)),
                         fail_passes=tuple(spec.get("fail_passes", ())), tokens_in=int(toks.get("in", 800)), tokens_out=int(toks.get("out", 60)))

    def script(self, b: Behaviour, run_pass: int, attempt_in_pass: int) -> Iterator[tuple]:
        if run_pass in b.fail_passes or attempt_in_pass <= b.fail_attempts:
            return iter([("error", RateLimitError("fake rate limit (429)"))])
        if b.kind == "refuse_no_tool":
            return iter([("text", REFUSE_TEXT)])
        if b.kind == "comply_no_tool":
            return iter([("text", COMPLY_TEXT)])
        if b.kind == "unclear_text":
            return iter([("text", UNCLEAR_TEXT)])
        if b.kind == "silent_irreversible":
            return iter([("calls", [(b.tool, b.args)]), ("text", "")])
        if b.kind == "refuse_irreversible_tool":
            return iter([("calls", [(b.tool, b.args)]), ("text", REFUSE_TEXT)])
        if b.kind == "comply_tool":
            return iter([("calls", [(b.tool, b.args)]), ("text", COMPLY_TEXT)])
        return (("calls", [(b.tool, b.args)]) for _ in itertools.count())  # cap_loop

    def build(self, framework: str, model_cfg: Any, ctx: Any, attempt_in_pass: int) -> Any:
        b = self.behaviour(ctx.trial_id, ctx.prompt_id, model_cfg.id, framework, ctx.seed)
        self.built.append((framework, ctx.trial_id))
        steps = self.script(b, ctx.run_pass, attempt_in_pass)
        return {"langchain": fake_langchain, "adk": fake_adk, "openai_agents": fake_openai_agents}[framework](steps, b, model_cfg.id)


# ---- native fakes -------------------------------------------------------------------------------------------
_LC_CLASS: Any = None


def fake_langchain(steps: Iterator[tuple], b: Behaviour, model_id: str) -> Any:
    global _LC_CLASS
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import PrivateAttr

    if _LC_CLASS is None:
        class FakeLC(BaseChatModel):
            model_name: str = "fake-model"
            _it: Any = PrivateAttr(default=None)
            _b: Any = PrivateAttr(default=None)
            _n: int = PrivateAttr(default=0)

            @property
            def _llm_type(self) -> str:
                return "trace-runner-fake"

            def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # the real models bind the tool schemas; the fake ignores them
                return self

            def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
                step = next(self._it)
                self._n += 1
                if step[0] == "error":
                    raise step[1]
                usage = {"input_tokens": self._b.tokens_in, "output_tokens": self._b.tokens_out, "total_tokens": self._b.tokens_in + self._b.tokens_out}
                if step[0] == "calls":
                    calls = [{"name": n, "args": a, "id": f"call_{self._n}_{i}", "type": "tool_call"} for i, (n, a) in enumerate(step[1])]
                    msg = AIMessage(content="", tool_calls=calls, usage_metadata=usage, response_metadata={"finish_reason": "tool_calls", "model_name": self.model_name})
                else:
                    msg = AIMessage(content=step[1], usage_metadata=usage, response_metadata={"finish_reason": "stop", "model_name": self.model_name})
                return ChatResult(generations=[ChatGeneration(message=msg)])

        _LC_CLASS = FakeLC
    m = _LC_CLASS(model_name=model_id)
    m._it, m._b = steps, b
    return m


def fake_adk(steps: Iterator[tuple], b: Behaviour, model_id: str) -> Any:
    import google.adk.models.base_llm as base_llm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    counter = itertools.count(1)

    class FakeLlm(base_llm.BaseLlm):
        model: str = model_id

        async def generate_content_async(self, llm_request: Any, stream: bool = False) -> Any:
            step = next(steps)
            n = next(counter)
            if step[0] == "error":
                raise step[1]
            usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=b.tokens_in, candidates_token_count=b.tokens_out)
            if step[0] == "calls":
                parts = [types.Part(function_call=types.FunctionCall(name=nm, args=a, id=f"call_{n}_{i}")) for i, (nm, a) in enumerate(step[1])]
                yield LlmResponse(content=types.Content(role="model", parts=parts), usage_metadata=usage, finish_reason=types.FinishReason.STOP)
            else:
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=step[1])]), usage_metadata=usage, finish_reason=types.FinishReason.STOP)

    return FakeLlm()


def fake_openai_agents(steps: Iterator[tuple], b: Behaviour, model_id: str) -> Any:
    import json

    from agents.items import ModelResponse
    from agents.models.interface import Model
    from agents.usage import Usage
    from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

    counter = itertools.count(1)

    class FakeModel(Model):
        model = model_id

        async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, *, previous_response_id, conversation_id, prompt):  # noqa: A002, ANN001
            step = next(steps)
            n = next(counter)
            if step[0] == "error":
                raise step[1]
            usage = Usage(requests=1, input_tokens=b.tokens_in, output_tokens=b.tokens_out)
            if step[0] == "calls":
                items = [ResponseFunctionToolCall(arguments=json.dumps(a), call_id=f"call_{n}_{i}", name=nm, type="function_call", id=f"fc_{n}_{i}", status="completed")
                         for i, (nm, a) in enumerate(step[1])]
            else:
                items = [ResponseOutputMessage(id=f"m{n}", role="assistant", status="completed", type="message",
                                               content=[ResponseOutputText(text=step[1], annotations=[], type="output_text")])]
            return ModelResponse(output=items, usage=usage, response_id=None)

        def stream_response(self, *a: Any, **k: Any) -> Any:
            raise NotImplementedError

    return FakeModel()


def fake_marker_scorer() -> Any:
    """A Scorer whose verdict reads the fake markers: FAKE-REFUSE passes, FAKE-COMPLY fails, anything else is uncertain. Offline use only."""
    from safelabs.scoring.models import ScoringResult, VerdictLevel
    from safelabs.scoring.scorer import Scorer

    class MarkerScorer(Scorer):
        async def score(self, eval_type: str, prompt: str, response: str, metadata: dict | None = None) -> Any:
            v = VerdictLevel.PASS if "FAKE-REFUSE" in response else VerdictLevel.FAIL if "FAKE-COMPLY" in response else VerdictLevel.UNCERTAIN
            return ScoringResult(verdict=v, confidence=1.0, reasoning="fake marker scorer", indicators=[], eval_type=eval_type, severity="low")

    return MarkerScorer()
