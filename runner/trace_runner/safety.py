"""Mandatory start-up safety, enforced in code (every refusal is tested).

1. No OpenTelemetry exporter environment: any ``OTEL_EXPORTER_OTLP_*`` variable set (names are reported, never values) refuses to start.
2. ADK span content stays off: ``ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`` is forced to false when the package is imported (before ADK is) and must still be
   false here; ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`` must be unset (or false). ``adk web`` / ``adk api_server`` are never used: the runner
   drives ADK only through ``InMemoryRunner`` (see agents.py).
3. OpenAI Agents: ``ensure_openai_export_off()`` runs at start whenever that framework is enabled; ``safe_run_config()`` is used for every run (agents.py);
   the handler is built with ``strict=True`` and there is no setting to change that; a custom tool ``failure_error_function`` refuses to start,
   both in the config and on every tool object that is built.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping

from trace_runner import ADK_CONTENT_ENV
from trace_runner.config import RunCfg

OTEL_CONTENT_ENV = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
EXPORTER_PREFIX = "OTEL_EXPORTER_OTLP_"


class StartupRefusal(RuntimeError):
    """The runner refuses to start (or to build an agent) because a safety condition does not hold."""


@dataclass
class SafetyReport:
    exporter_env_clear: bool = True
    adk_span_content: str = "false"
    openai_export_off: bool | None = None  # None when the framework is not enabled
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"exporter_env_clear": self.exporter_env_clear, "adk_span_content": self.adk_span_content, "openai_export_off": self.openai_export_off,
                "strict_handler": True, "safe_run_config": True, "notes": self.notes}


def check_exporter_env(env: Mapping[str, str]) -> None:
    names = sorted(k for k in env if k.startswith(EXPORTER_PREFIX))
    if names:
        raise StartupRefusal("refusing to start: OpenTelemetry exporter environment is set (" + ", ".join(names) + "); unset it. Values are not shown.")


def check_adk_env(env: Mapping[str, str]) -> None:
    if str(env.get(ADK_CONTENT_ENV, "")).strip().lower() != "false":
        raise StartupRefusal(f"refusing to start: {ADK_CONTENT_ENV} is not 'false' (ADK would put prompts and tool data into spans if an exporter ever appeared)")
    if str(env.get(OTEL_CONTENT_ENV, "false")).strip().lower() not in ("", "false"):
        raise StartupRefusal(f"refusing to start: {OTEL_CONTENT_ENV} is set; leave it unset")


def check_custom_failure_function(cfg: RunCfg) -> None:
    if cfg.openai_agents.failure_error_function is not None:
        raise StartupRefusal("refusing to start: a custom failure_error_function is configured for OpenAI Agents tools; the trace handler recognises only the SDK's default")


def check_openai_tools(tools: list[Any]) -> None:
    """Refuse a tool object whose failure_error_function is custom. The SDK default is the unset sentinel (``_use_default_failure_error_function`` true)."""
    for t in tools:
        if getattr(t, "_use_default_failure_error_function", True) is False and getattr(t, "_failure_error_function", None) is not None:
            raise StartupRefusal(f"refusing to run: OpenAI Agents tool {getattr(t, 'name', '?')!r} has a custom failure_error_function")


def enforce_startup_safety(cfg: RunCfg, env: Mapping[str, str] | None = None) -> SafetyReport:
    env = os.environ if env is None else env
    check_exporter_env(env)
    check_adk_env(env)
    check_custom_failure_function(cfg)
    rep = SafetyReport()
    if "openai_agents" in cfg.frameworks:
        from safelabs_trace.openai_agents_handler import OpenAIExportActiveError, ensure_openai_export_off

        try:
            status = ensure_openai_export_off()
        except OpenAIExportActiveError as exc:
            raise StartupRefusal(f"refusing to start: {exc}") from exc
        rep.openai_export_off = not status.active
    if "google.adk" in sys.modules:
        rep.notes.append("google.adk was already imported when the check ran; the span-content variable was set by the trace_runner import, which should precede it")
    return rep
