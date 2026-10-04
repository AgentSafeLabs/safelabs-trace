"""Mandatory start-up safety: the four refusals, and the always-on settings."""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from rt_helpers import SALT, make_cfg, make_runner, run
from trace_runner.config import ConfigError, load_config
from trace_runner.safety import StartupRefusal, check_openai_tools, enforce_startup_safety


def test_refusal_1_exporter_environment_variable(tmp_path, openai_sdk):
    cfg = make_cfg(tmp_path)
    with pytest.raises(StartupRefusal, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        enforce_startup_safety(cfg, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.invalid", "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})
    with pytest.raises(StartupRefusal, match="OTEL_EXPORTER_OTLP_TRACES_HEADERS"):  # any variable with the prefix, not just the endpoint
        enforce_startup_safety(cfg, {"OTEL_EXPORTER_OTLP_TRACES_HEADERS": "x=y", "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})


def test_refusal_1_values_are_never_shown(tmp_path):
    secret = "SUPER-SECRET-HEADER-VALUE"
    with pytest.raises(StartupRefusal) as e:
        enforce_startup_safety(make_cfg(tmp_path), {"OTEL_EXPORTER_OTLP_HEADERS": secret, "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})
    assert secret not in str(e.value)


def test_refusal_1_through_the_cli(tmp_path, monkeypatch, capsys):
    from trace_runner.cli import main

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    assert main(["--config", "configs/dryrun.yaml", "--dry-run", "--out", str(tmp_path / "o")]) == 2
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in capsys.readouterr().err


def test_refusal_2_adk_span_content_not_false(tmp_path):
    cfg = make_cfg(tmp_path, frameworks=["adk"])
    for bad in ({}, {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "true"}):
        with pytest.raises(StartupRefusal, match="ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"):
            enforce_startup_safety(cfg, bad)
    with pytest.raises(StartupRefusal, match="OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"):
        enforce_startup_safety(cfg, {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false", "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true"})


def test_adk_span_content_is_forced_false_before_adk_is_imported():
    code = ("import os, sys; os.environ['ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS']='true'; assert 'google.adk' not in sys.modules; "
            "import trace_runner; assert os.environ['ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS']=='false'; assert 'google.adk' not in sys.modules; print('ok')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr


def test_refusal_3_custom_failure_error_function_in_the_config(tmp_path):
    cfg = make_cfg(tmp_path, frameworks=["openai_agents"], openai_agents={"failure_error_function": "my_module.handler"})
    with pytest.raises(StartupRefusal, match="failure_error_function"):
        enforce_startup_safety(cfg, {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})


def test_refusal_3_custom_failure_error_function_on_a_tool_object():
    pytest.importorskip("agents")
    from agents import FunctionTool
    from agents.tool import set_function_tool_failure_error_function
    from safelabs_trace.inert_tools import InertToolKit
    from safelabs_trace.openai_agents_handler import openai_agents_tools

    tools = openai_agents_tools(InertToolKit())
    check_openai_tools(tools)  # the SDK default passes
    set_function_tool_failure_error_function(tools[0], lambda ctx, err: "custom")
    with pytest.raises(StartupRefusal, match="custom failure_error_function"):
        check_openai_tools(tools)


def test_refusal_4_openai_export_still_active_refuses(tmp_path, openai_sdk, monkeypatch):
    from safelabs_trace import openai_agents_handler as h

    def still_active():
        raise h.OpenAIExportActiveError("could not turn the export off")

    monkeypatch.setattr(h, "ensure_openai_export_off", still_active)
    with pytest.raises(StartupRefusal, match="could not turn the export off"):
        enforce_startup_safety(make_cfg(tmp_path, frameworks=["openai_agents"]), {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})


def test_ensure_openai_export_off_runs_once_at_start_and_only_when_the_framework_is_enabled(tmp_path, openai_sdk, monkeypatch):
    from safelabs_trace import openai_agents_handler as h

    calls = []
    real = h.ensure_openai_export_off
    monkeypatch.setattr(h, "ensure_openai_export_off", lambda: calls.append(1) or real())
    rep = enforce_startup_safety(make_cfg(tmp_path, frameworks=["openai_agents", "adk"]), {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})
    assert calls == [1] and rep.openai_export_off is True
    enforce_startup_safety(make_cfg(tmp_path, frameworks=["adk"]), {"ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"})
    assert calls == [1]


def test_safe_run_config_is_used_for_every_openai_run_and_the_handler_is_strict(tmp_path, openai_sdk, monkeypatch):
    from agents import Runner
    from safelabs_trace import openai_agents_handler as h

    configs, stricts = [], []
    real_run, real_handler = Runner.run.__func__, h.OpenAIAgentsTraceHandler

    class SpyHandler(real_handler):
        def __init__(self, *a, **k):
            stricts.append(k.get("strict", "default"))
            super().__init__(*a, **k)

    async def spy_run(cls, agent, input, **kw):  # noqa: A002
        configs.append((kw["run_config"], kw["max_turns"]))
        return await real_run(cls, agent, input, **kw)

    monkeypatch.setattr(Runner, "run", classmethod(spy_run))
    monkeypatch.setattr(h, "OpenAIAgentsTraceHandler", SpyHandler)
    cfg = make_cfg(tmp_path, n_items=3, frameworks=["openai_agents"], plan={"by_prompt": {"ASI01-900": {"kind": "refuse_no_tool", "fail_attempts": 1}}})
    run(make_runner(tmp_path, cfg).run())
    assert len(configs) == 4  # 3 trials + 1 retry attempt
    assert all(rc.tracing_disabled is True and rc.trace_include_sensitive_data is False and turns == cfg.max_model_calls for rc, turns in configs)
    assert stricts == [True] * 4


def test_the_config_has_no_way_to_turn_strict_off():
    with pytest.raises(ValidationError):
        make_cfg(__import__("pathlib").Path("."), openai_agents={"strict": False})


def test_credential_looking_config_keys_are_refused(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("run_name: x\nmodels:\n  - {id: m, provider: openai, litellm_route: openai/m, api_key: nope}\n")
    with pytest.raises(ConfigError, match="credential"):
        load_config(p)
    p.write_text("run_name: x\nmodels:\n  - {id: m, provider: openai, litellm_route: openai/m, est_output_tokens: 5}\n")
    load_config(p)  # est_output_tokens is not a credential
