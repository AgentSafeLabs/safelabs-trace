"""Cost estimate (user-filled prices only) and the budget stop."""

import json
import shutil
from pathlib import Path

import pytest

from rt_helpers import SALT, make_cfg, make_runner, model, run
from trace_runner.cli import main
from trace_runner.config import BudgetCfg
from trace_runner.orchestrator import Paths, read_rows, verify_manifest
from trace_runner.pricing import Price, PriceTable, PriceTableError, estimate, format_estimate, load_price_table, trial_tokens_worst

HERE = Path(__file__).resolve().parent.parent


def test_estimate_refuses_when_the_price_table_is_missing(tmp_path):
    with pytest.raises(PriceTableError, match="not found"):
        load_price_table(tmp_path / "nope.yaml", ["m1"])


def test_estimate_refuses_the_shipped_placeholder_table():
    ids = ["claude-haiku-4-5-20251001", "gpt-5.4-nano", "gemini-3.1-flash-lite"]
    with pytest.raises(PriceTableError, match="no usable price"):
        load_price_table(HERE / "price_table.yaml", ids)


@pytest.mark.parametrize("row", ["{input_per_mtok: null, output_per_mtok: 1}", "{input_per_mtok: 0, output_per_mtok: 1}", "{input_per_mtok: '1', output_per_mtok: 1}",
                                 "{output_per_mtok: 1}", "{input_per_mtok: -1, output_per_mtok: 1}", "{input_per_mtok: true, output_per_mtok: 1}"])
def test_estimate_refuses_unusable_prices(tmp_path, row):
    p = tmp_path / "p.yaml"
    p.write_text(f"prices:\n  m1: {row}\n")
    with pytest.raises(PriceTableError):
        load_price_table(p, ["m1"])


def test_a_table_marked_fake_is_refused_unless_it_is_a_dry_run(tmp_path):
    with pytest.raises(PriceTableError, match="fake"):
        load_price_table(HERE / "configs" / "dryrun_price_table.yaml", ["gpt-5.4-nano"])
    load_price_table(HERE / "configs" / "dryrun_price_table.yaml", ["gpt-5.4-nano"], allow_fake=True)


def test_cli_estimate_and_real_run_refuse_without_a_filled_table(capsys, tmp_path):
    assert main(["--config", str(HERE / "configs" / "pilot.yaml"), "--estimate"]) == 2
    assert "no usable price" in capsys.readouterr().err
    assert main(["--config", str(HERE / "configs" / "pilot.yaml"), "--confirm-real", "--out", str(tmp_path / "o")]) == 2
    assert "no usable price" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()  # nothing started


def test_cli_estimate_with_a_user_filled_table_prints_the_projection(tmp_path, capsys):
    cfgtxt = (HERE / "configs" / "pilot.yaml").read_text().replace("price_table: price_table.yaml", f"price_table: {tmp_path / 'mine.yaml'}")
    (tmp_path / "pilot.yaml").write_text(cfgtxt)
    (tmp_path / "mine.yaml").write_text("prices:\n  claude-haiku-4-5-20251001: {input_per_mtok: 2.0, output_per_mtok: 10.0}\n"
                                        "  gpt-5.4-nano: {input_per_mtok: 1.0, output_per_mtok: 4.0}\n  gemini-3.1-flash-lite: {input_per_mtok: 0.5, output_per_mtok: 2.0}\n")
    assert main(["--config", str(tmp_path / "pilot.yaml"), "--estimate"]) == 0
    out = capsys.readouterr().out
    # 50 items x 2 frameworks x 3 models x 1 trial = 300 trials; per trial in = 2 x (1500 + 70) = 3140 tokens
    assert "TOTAL 300 trials  in 942,000" in out and "cap USD 20.00" in out
    # expected: haiku 100 trials x (3140 x 2 + 384 x 10)/1e6 = 1.012; nano 100 x (3140 + 286 x 4)/1e6 = 0.4284; lite 100 x (1570 + 201 x 2)/1e6 = 0.1972
    assert "expected USD 1.64" in out


def test_estimate_numbers(tmp_path):
    cfg = make_cfg(tmp_path, n_items=10, frameworks=["langchain", "adk"], models=[model("m1")], trials=2, budget=BudgetCfg(cap_usd=5.0))
    est = estimate(cfg, 10, PriceTable({"m1": Price(10.0, 20.0)}))
    t = est["total"]
    assert t["trials"] == 40 and t["input_tokens"] == 40 * 2 * 1570 and t["output_tokens"] == 40 * 300
    assert abs(t["usd_expected"] - (40 * 3140 * 10 + 40 * 300 * 20) / 1e6) < 1e-9
    assert "worst-case" in format_estimate(est)


def _budget_cfg(tmp_path, cap):
    return make_cfg(tmp_path, n_items=20, frameworks=["langchain", "adk"], plan={"tokens": {"in": 1000, "out": 100}, "by_prompt": {f"ASI01-9{i:02d}": "refuse_no_tool" for i in range(20)}},
                    budget=BudgetCfg(cap_usd=cap))


def test_budget_stop_marks_the_rest_not_run_budget_and_never_crosses_the_cap(tmp_path, openai_sdk):
    cap = 25.0
    cfg = _budget_cfg(tmp_path, cap)
    table = PriceTable({"m1": Price(1000.0, 2000.0)})  # one 1000-in/100-out call costs 1.20; the worst case for a trial is far higher
    worst = table.cost("m1", *trial_tokens_worst(cfg, "m1"))
    assert worst > 9
    r = make_runner(tmp_path, cfg, table)
    out = run(r.run())
    paths = Paths(tmp_path / "out")
    rows = read_rows(paths.results)
    tm = json.loads(paths.trace_manifest.read_text())
    assert out["stopped_for_budget"] and 0 < len(rows) < 40
    assert r.budget.spent <= cap and abs(r.budget.spent - 1.2 * len(rows)) < 1e-6
    # the stop is exactly where spent + worst case would cross the cap
    assert r.budget.spent + worst > cap and r.budget.spent - 1.2 + worst <= cap
    nrb = [e for e in tm["trials"].values() if e["status"] == "not_run_budget"]
    assert len(nrb) == 40 - len(rows) and all(e["trace_file"] is None and e["payload_hash"] is None for e in nrb)
    assert out["not_run_budget"] == len(nrb) and tm["budget"]["stopped"] is True
    assert verify_manifest(paths) == []  # not_run_budget trials have no row, rows all link to traces
    s = json.loads(paths.summary_json.read_text())
    assert s["excluded"]["not_run_budget"] == len(nrb)


def test_resume_after_a_budget_stop_runs_exactly_the_not_run_trials_and_the_cap_is_cumulative(tmp_path, openai_sdk):
    table = PriceTable({"m1": Price(1000.0, 2000.0)})
    r1 = make_runner(tmp_path, _budget_cfg(tmp_path, 25.0), table)
    run(r1.run())
    paths = Paths(tmp_path / "out")
    first = read_rows(paths.results)
    first_lines = paths.results.read_text().splitlines()
    # same cap again: spend so far counts, so nothing more can start
    r_same = make_runner(tmp_path, _budget_cfg(tmp_path, 25.0), table)
    assert run(r_same.run())["ran"] == 0
    # a larger cap lets the remainder run
    r2 = make_runner(tmp_path, _budget_cfg(tmp_path, 200.0), table)
    out = run(r2.run())
    rows = read_rows(paths.results)
    assert out["ran"] == 40 - len(first) and len(rows) == 40 and not out["stopped_for_budget"]
    assert paths.results.read_text().splitlines()[: len(first_lines)] == first_lines  # earlier rows untouched
    tm = json.loads(paths.trace_manifest.read_text())
    assert not [e for e in tm["trials"].values() if e["status"] == "not_run_budget"] and len(tm["config_sha256_history"]) >= 1
    assert abs(r2.budget.spent - 1.2 * 40) < 1e-6
    assert verify_manifest(paths) == []


def test_unreported_usage_is_charged_at_the_worst_case(tmp_path):
    from trace_runner.pricing import BudgetTracker

    cfg = make_cfg(tmp_path, n_items=1, models=[model("m1")], budget=BudgetCfg(cap_usd=100.0))
    t = PriceTable({"m1": Price(1000.0, 2000.0)})
    b = BudgetTracker(cfg, t)
    c = b.record("m1", None)
    assert b.unmetered == 1 and c == t.cost("m1", *trial_tokens_worst(cfg, "m1"))
