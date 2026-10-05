"""CLI behaviour, the pilot and dry-run configs, item selection, real-run preconditions, and a source-level check that keys are never read."""

import json
import re
from pathlib import Path

import pytest

from trace_runner.cli import main
from trace_runner.config import ConfigError, load_config
from trace_runner.items import load_items, select_ids
from trace_runner.models_real import missing_key_names

HERE = Path(__file__).resolve().parent.parent


def test_pilot_config_matches_the_decisions():
    assert load_config(HERE / "configs" / "smoke.yaml")[0].max_model_calls == 8
    assert load_config(HERE / "configs" / "pilot.yaml")[0].output_dir == "../../runs/pilot" and load_config(HERE / "configs" / "smoke.yaml")[0].output_dir == "../../runs/smoke"
    cfg, _ = load_config(HERE / "configs" / "pilot.yaml")
    assert cfg.items.source == "safeagent300" and cfg.items.seed == 20261004 and cfg.items.per_category == 5 and len(cfg.items.ids) == 50
    assert cfg.frameworks == ["langchain", "adk"] and cfg.trials == 1 and cfg.max_model_calls == 8 and cfg.budget.cap_usd == 20.0 and cfg.budget.calls_per_trial == 3  # D8: 4 -> 8 after the smoke run (calls_per_trial 2 -> 3, INFERRED) and cfg.tools is None
    assert [m.id for m in cfg.models] == ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite"] and not any(m.verified for m in cfg.models)
    items = load_items(cfg.items)  # regenerates the seeded selection and compares it with the recorded ids
    from collections import Counter

    assert Counter(i.category.value for i in items) == {f"ASI{n:02d}": 5 for n in range(1, 11)}
    assert len(items) * len(cfg.frameworks) * len(cfg.models) * cfg.trials == 300


def test_recorded_ids_that_do_not_match_the_seeded_selection_are_refused():
    cfg, _ = load_config(HERE / "configs" / "pilot.yaml")
    bad = cfg.items.model_copy(update={"ids": [cfg.items.ids[1], cfg.items.ids[0], *cfg.items.ids[2:]]})
    with pytest.raises(ConfigError, match="does not match"):
        load_items(bad)
    with pytest.raises(ConfigError, match="empty"):
        load_items(cfg.items.model_copy(update={"ids": []}))


def test_select_ids_is_deterministic_and_stratified():
    cats = {"A": [f"A-{i}" for i in range(30)], "B": [f"B-{i}" for i in range(30)]}
    a, b = select_ids(cats, 5, 7), select_ids(cats, 5, 7)
    assert a == b and len(a) == 10 and sum(x.startswith("A") for x in a) == 5 and select_ids(cats, 5, 8) != a


def test_select_items_command_prints_the_recorded_ids(capsys):
    assert main(["--config", str(HERE / "configs" / "pilot.yaml"), "--select-items"]) == 0
    printed = capsys.readouterr().out.split()
    cfg, _ = load_config(HERE / "configs" / "pilot.yaml")
    assert printed == cfg.items.ids


def test_dry_run_command_writes_all_outputs_and_refuses_to_reuse_a_folder(tmp_path, capsys):
    out = tmp_path / "d"
    assert main(["--config", str(HERE / "configs" / "dryrun.yaml"), "--dry-run", "--out", str(out)]) == 0
    for f in ("results.jsonl", "results.manifest.json", "trace_manifest.json", "divergence_summary.json", "divergence_summary.md", ".gitignore"):
        assert (out / f).exists(), f
    assert len(list((out / "traces").glob("*.jsonl"))) == 45  # 5 items x 3 frameworks x 3 models
    tm = json.loads((out / "trace_manifest.json").read_text())
    assert tm["mode"] == "dry_run" and tm["safety"]["strict_handler"] and tm["safety"]["exporter_env_clear"] and tm["budget"]["price_table_fake"]
    assert main(["--config", str(HERE / "configs" / "dryrun.yaml"), "--dry-run", "--out", str(out)]) == 2  # rows already there
    assert main(["--config", str(HERE / "configs" / "dryrun.yaml"), "--dry-run", "--out", str(out), "--rerun-missing"]) == 0
    assert main(["--config", str(HERE / "configs" / "dryrun.yaml"), "--dry-run", "--out", str(out), "--verify"]) == 0
    assert "manifest OK" in capsys.readouterr().out
    s = json.loads((out / "divergence_summary.json").read_text())
    assert s["excluded"]["missing_infrastructure"] == 0 and len(s["by_cell"]) == 9  # the two persistent failures were filled by the rerun


def test_real_run_needs_confirmation_keys_and_a_salt(tmp_path, monkeypatch, capsys):
    prices = tmp_path / "p.yaml"
    prices.write_text("prices:\n  claude-haiku-4-5-20251001: {input_per_mtok: 1.0, output_per_mtok: 2.0}\n  gpt-5.4-nano: {input_per_mtok: 1.0, output_per_mtok: 2.0}\n"
                      "  gemini-3.1-flash-lite: {input_per_mtok: 1.0, output_per_mtok: 2.0}\n")
    (tmp_path / "c.yaml").write_text((HERE / "configs" / "pilot.yaml").read_text().replace("price_table: price_table.yaml", f"price_table: {prices}"))
    base = ["--config", str(tmp_path / "c.yaml"), "--out", str(tmp_path / "o")]
    assert main(base) == 2 and "--confirm-real" in capsys.readouterr().err
    assert main([*base, "--confirm-real"]) == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err and "OPENAI_API_KEY" in err and "GEMINI_API_KEY" in err
    assert not (tmp_path / "o").exists()


def test_missing_key_names_reports_names_only():
    cfg, _ = load_config(HERE / "configs" / "pilot.yaml")
    assert missing_key_names(cfg, {"OPENAI_API_KEY": "value-not-shown"}) == ["ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    assert missing_key_names(cfg, {"OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "x", "GEMINI_API_KEY": "x"}) == []


def test_the_runner_source_never_reads_an_environment_variable_value():
    """Keys are read by the provider libraries, not here: no os.environ reads, no getenv, in the runner package (it only assigns two safe variables)."""
    for p in (HERE / "trace_runner").glob("*.py"):
        text = p.read_text()
        assert not re.search(r"os\.getenv|os\.environ\.get\(|os\.environ\[[^\]]+\]\s*[^=\s]|environ\.items|environ\.copy", text), p.name
    safety = (HERE / "trace_runner" / "safety.py").read_text()
    assert "os.environ if env is None" in safety  # the only environment access: the mapping handed to the checks, whose values are never printed


def test_the_runner_never_starts_adk_web_or_api_server_or_a_subprocess():
    for p in (HERE / "trace_runner").glob("*.py"):
        text = p.read_text()
        assert "subprocess" not in text and "os.system" not in text, p.name
    agents = (HERE / "trace_runner" / "agents.py").read_text()
    assert "InMemoryRunner" in agents and "get_fast_api_app" not in agents and "from google.adk.cli" not in agents and "import api_server" not in agents and "adk web\"" not in agents
