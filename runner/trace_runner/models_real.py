"""Real model objects, all routed through LiteLLM (decision D4; nothing is installed). Built only in a real run; the keys stay in the environment,
where LiteLLM reads them. The model ids in the config are placeholders until this is first used (``verified: false`` in the config)."""

from __future__ import annotations

import os
from typing import Any

from trace_runner.config import PROVIDER_ENV, ModelCfg, RunCfg


class RealModels:
    def build(self, framework: str, model_cfg: ModelCfg, ctx: Any, attempt_in_pass: int) -> Any:
        route = model_cfg.litellm_route
        if framework == "adk":
            from google.adk.models.lite_llm import LiteLlm

            return LiteLlm(model=route)
        if framework == "openai_agents":
            from agents.extensions.models.litellm_model import LitellmModel

            return LitellmModel(model=route)
        if framework == "langchain":
            from trace_runner.litellm_chat import LiteLLMChat

            return LiteLLMChat(model=route)
        raise ValueError(f"unknown framework {framework!r}")


def missing_key_names(cfg: RunCfg, env: Any = None) -> list[str]:
    """Names (never values) of the provider key variables that are not set for the configured models."""
    env = os.environ if env is None else env
    need = sorted({PROVIDER_ENV[m.provider] for m in cfg.models})
    return [n for n in need if n not in env]
