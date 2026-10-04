"""A small LangChain chat model over LiteLLM, used only by real runs (no LangChain provider package is installed or needed).
Offline tests exercise it with ``litellm.completion`` / ``acompletion`` replaced by fakes. Keys are read by LiteLLM from the environment; nothing here sees them."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


def to_openai_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content if isinstance(m.content, str) else json.dumps(m.content)})
        elif isinstance(m, AIMessage):
            d: dict[str, Any] = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                d["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in m.tool_calls]
            out.append(d)
        else:
            raise ValueError(f"unsupported message type {type(m).__name__}")
    return out


def from_response(resp: Any) -> AIMessage:
    choice = resp.choices[0]
    msg = choice.message
    calls = []
    for tc in getattr(msg, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append({"name": tc.function.name, "args": args if isinstance(args, dict) else {}, "id": tc.id, "type": "tool_call"})
    u = getattr(resp, "usage", None)
    usage = None if u is None else {"input_tokens": int(u.prompt_tokens), "output_tokens": int(u.completion_tokens), "total_tokens": int(u.prompt_tokens) + int(u.completion_tokens)}
    return AIMessage(content=msg.content or "", tool_calls=calls, usage_metadata=usage,
                     response_metadata={"finish_reason": choice.finish_reason, "model_name": getattr(resp, "model", None)})


class LiteLLMChat(BaseChatModel):
    model: str
    bound_tools: list[dict[str, Any]] | None = None

    @property
    def _llm_type(self) -> str:
        return "litellm"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "LiteLLMChat":
        return self.model_copy(update={"bound_tools": [convert_to_openai_tool(t) for t in tools]})

    def _kwargs(self, messages: list[BaseMessage]) -> dict[str, Any]:
        kw: dict[str, Any] = {"model": self.model, "messages": to_openai_messages(messages), "drop_params": True}
        if self.bound_tools:
            kw["tools"] = self.bound_tools
        return kw

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        import litellm

        return ChatResult(generations=[ChatGeneration(message=from_response(litellm.completion(**self._kwargs(messages))))])

    async def _agenerate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        import litellm

        return ChatResult(generations=[ChatGeneration(message=from_response(await litellm.acompletion(**self._kwargs(messages))))])
