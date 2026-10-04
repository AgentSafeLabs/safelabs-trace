"""Tests for score.py. Synthetic labels and synthetic item ids only; no filled copy of the real handcheck_items.csv is created or used."""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score  # noqa: E402

R, S, I = "read_only", "state_changing", "irreversible"


def write(tmp_path, human, tagger, *, groups=None, sources=None, name="items.csv"):
    ids = [f"T{i + 1:02d}" for i in range(len(human))]
    with open(tmp_path / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "tool_name", "tool_description", "arguments_summary", "human_label", "confidence", "note"])
        for i, h in zip(ids, human):
            w.writerow([i, "tool_" + i, "synthetic description", "synthetic arguments", h, "2", ""])
    with open(tmp_path / "key.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "tagger_label", "rule_id_fired", "source", "source_citation", "stratum", "variant_group"])
        for n, (i, t) in enumerate(zip(ids, tagger)):
            w.writerow([i, t, "N-X", (sources or ["external"] * len(ids))[n], "synthetic", f"{t}|x", (groups or [""] * len(ids))[n]])
    return tmp_path / name, tmp_path / "key.csv"


def run(tmp_path, human, tagger, **kw):
    items, key = write(tmp_path, human, tagger, **{k: v for k, v in kw.items() if k in ("groups", "sources")})
    rc = score.main([str(items), str(key)] + [x for k, v in kw.items() if k.startswith("--") for x in (k, str(v))])
    return rc


def test_perfect_agreement(tmp_path, capsys):
    labels = [R] * 3 + [S] * 3 + [I] * 3
    assert run(tmp_path, labels, labels) == 0
    out = capsys.readouterr().out
    assert "Exact agreement: 9 of 9 (100.0%)" in out and "Cohen's kappa: 1.000" in out and "weighted kappa (read_only < state_changing < irreversible): 1.000" in out
    assert "Under-tagged items: 0" in out and "Over-tagged items: 0" in out and "**PASS** against these PROPOSED criteria" in out
    assert "| read_only | 3 | 0 | 0 | 3 |" in out and "| irreversible | 0 | 0 | 3 | 3 |" in out
    assert (tmp_path / "handcheck_results.md").exists()


def test_all_under_tagging(tmp_path, capsys):
    human = [I] * 4 + [S] * 2
    tagger = [R] * 4 + [R] * 2
    assert run(tmp_path, human, tagger) == 0
    out = capsys.readouterr().out
    assert "Under-tagged items: 6" in out and "Human irreversible, tagger read_only: 4" in out and "Human irreversible, tagger less severe than irreversible: 4" in out
    assert "Over-tagged items: 0" in out and "**FAIL** against these PROPOSED criteria" in out and "**NOT met**" in out
    assert "| T01 | tool_T01 | irreversible | read_only |" in out


def test_mixed_case_matches_hand_computed_values(tmp_path, capsys):
    human, tagger = [R, S, I, I], [R, S, I, S]
    assert run(tmp_path, human, tagger) == 0
    out = capsys.readouterr().out
    assert "Exact agreement: 3 of 4 (75.0%)" in out and "Cohen's kappa: 0.636" in out and "weighted kappa (read_only < state_changing < irreversible): 0.714" in out
    assert "Under-tagged items: 1" in out and "Human irreversible, tagger read_only: 0" in out and "Human irreversible, tagger less severe than irreversible: 1" in out
    assert "Other disagreements: 0" in out and "**NOT met**" in out  # one irreversible under-tag against a limit of zero
    assert "| irreversible | 0 | 1 | 1 | 2 |" in out


def test_kappa_functions_directly():
    k, kw = score.kappas([0, 1, 2, 2], [0, 1, 2, 1])
    assert k == pytest.approx(0.6363636, abs=1e-6) and kw == pytest.approx(5 / 7)
    assert score.kappas([1, 1, 1], [1, 1, 1]) == (None, None)
    perfect = score.kappas([0, 1, 2, 0], [0, 1, 2, 0])
    assert perfect == (1.0, 1.0)


def test_over_tagging_and_the_gate_options(tmp_path, capsys):
    human, tagger = [R, R, S, I, I, I], [S, S, S, I, I, I]
    assert run(tmp_path, human, tagger, **{"--max-other-disagreements": 1}) == 0
    out = capsys.readouterr().out
    assert "Over-tagged items: 2" in out and "Under-tagged items: 0" in out and "Other disagreements: 2; allowed at most 1" in out and "**FAIL**" in out
    assert run(tmp_path, human, tagger, **{"--max-other-disagreements": 2}) == 0
    assert "**PASS**" in capsys.readouterr().out


def test_bootstrap_is_deterministic_and_handles_degenerate_resamples(tmp_path):
    rows = score.load(*write(tmp_path, [R, S, I, I, S, R, I], [R, S, I, S, S, R, R]))
    a, b = score.bootstrap(rows), score.bootstrap(rows)
    assert a == b and a["kappa"][0] <= a["kappa"][1] and a["weighted"][0] <= a["weighted"][1]
    mostly = score.load(*write(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, [R, R, R, R, S], [R, R, R, R, S]))
    assert score.bootstrap(mostly)["skipped"] > 0  # resamples that draw only one class have undefined kappa and are skipped, not crashed on


def test_by_source_and_variant_groups(tmp_path, capsys):
    human = [R, S, I, R, I]
    tagger = [R, S, S, R, I]
    assert run(tmp_path, human, tagger, groups=["G1", "G1", "G1", "", ""], sources=["inert", "inert", "inert", "external", "external"]) == 0
    out = capsys.readouterr().out
    assert "| inert | 3 | 2 of 3 | 1 | 0 |" in out and "| external | 2 | 2 of 2 | 0 | 0 |" in out
    assert "| G1 | T01, T02, T03 | tool_T01 | read_only, state_changing, irreversible | read_only, state_changing, state_changing | no | 2 of 3 |" in out
    assert "All groups: 2 of 3 item pairs" in out


def test_blank_label_is_refused_and_nothing_is_written(tmp_path, capsys):
    items, key = write(tmp_path, [R, "", I], [R, S, I])
    assert score.main([str(items), str(key)]) == 2
    assert "blank human_label" in capsys.readouterr().err and not list(tmp_path.glob("handcheck_results*"))
    with pytest.raises(SystemExit):
        score.load(items, key)


def test_whitespace_only_label_counts_as_blank(tmp_path):
    items, key = write(tmp_path, [R, "   ", I], [R, S, I])
    with pytest.raises(SystemExit, match="blank human_label"):
        score.load(items, key)


def test_invalid_label_is_refused(tmp_path, capsys):
    items, key = write(tmp_path, [R, "irreversable", I], [R, S, I])
    assert score.main([str(items), str(key)]) == 2
    assert "invalid human_label" in capsys.readouterr().err and not list(tmp_path.glob("handcheck_results*"))


def test_labels_are_accepted_case_and_space_insensitively(tmp_path):
    items, key = write(tmp_path, [" Read_Only ", "STATE_CHANGING", "irreversible"], [R, S, I])
    assert [r["human"] for r in score.load(items, key)] == [R, S, I]


def test_mismatched_item_ids_are_refused(tmp_path):
    items, key = write(tmp_path, [R, S, I], [R, S, I])
    rows = list(csv.reader(open(key)))
    rows[1][0] = "T99"
    with open(key, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    with pytest.raises(SystemExit, match="different item ids"):
        score.load(items, key)


def test_existing_results_files_are_never_overwritten(tmp_path, capsys):
    (tmp_path / "handcheck_results.md").write_text("KEEP ME")
    items, key = write(tmp_path, [R, S, I], [R, S, I])
    assert score.main([str(items), str(key)]) == 0
    assert (tmp_path / "handcheck_results.md").read_text() == "KEEP ME" and (tmp_path / "handcheck_results_2.md").exists()
    assert score.main([str(items), str(key)]) == 0
    assert (tmp_path / "handcheck_results_3.md").exists() and (tmp_path / "handcheck_results.md").read_text() == "KEEP ME"
    assert "handcheck_results_3.md" in capsys.readouterr().out
    assert (tmp_path / "handcheck_results_2.md").read_text() == (tmp_path / "handcheck_results_3.md").read_text()


def test_out_dir_option(tmp_path):
    items, key = write(tmp_path, [R, S, I], [R, S, I])
    out = tmp_path / "elsewhere"
    out.mkdir()
    assert score.main([str(items), str(key), "--out-dir", str(out)]) == 0
    assert (out / "handcheck_results.md").exists() and not (tmp_path / "handcheck_results.md").exists()
