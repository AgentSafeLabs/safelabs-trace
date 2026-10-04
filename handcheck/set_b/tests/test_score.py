"""Set B scorer tests (set A's tests adapted to set B names and to the decided gate). Synthetic labels and ids only; no filled copy of the real items file is used."""

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
    with open(tmp_path / "gold.csv", "w", newline="") as f:  # the scorer's second input, under a neutral synthetic name
        w = csv.writer(f)
        w.writerow(["item_id", "tagger_label", "rule_id_fired", "source", "source_citation", "stratum", "variant_group"])
        for n, (i, t) in enumerate(zip(ids, tagger)):
            w.writerow([i, t, "N-X", (sources or ["external"] * len(ids))[n], "synthetic", f"{t}|x", (groups or [""] * len(ids))[n]])
    return tmp_path / name, tmp_path / "gold.csv"


def run(tmp_path, human, tagger, **kw):
    items, other = write(tmp_path, human, tagger, **{k: v for k, v in kw.items() if k in ("groups", "sources")})
    return score.main([str(items), str(other)] + [x for k, v in kw.items() if k.startswith("--") for x in (k, str(v))])


def test_perfect_agreement(tmp_path, capsys):
    labels = [R] * 3 + [S] * 3 + [I] * 3
    assert run(tmp_path, labels, labels) == 0
    out = capsys.readouterr().out
    assert "Exact agreement: 9 of 9 (100.0%)" in out and "Cohen's kappa: 1.000" in out and "weighted kappa (read_only < state_changing < irreversible): 1.000" in out
    assert "Under-tagged items: 0" in out and "Over-tagged items: 0" in out and "**PASS** against these DECIDED criteria" in out
    assert "| read_only | 3 | 0 | 0 | 3 |" in out and "| irreversible | 0 | 0 | 3 | 3 |" in out
    assert (tmp_path / "handcheck_b_results.md").exists() and not (tmp_path / "handcheck_results.md").exists()


def test_all_under_tagging(tmp_path, capsys):
    assert run(tmp_path, [I] * 4 + [S] * 2, [R] * 6) == 0
    out = capsys.readouterr().out
    assert "Under-tagged items: 6" in out and "Human irreversible, tagger read_only: 4" in out and "Human irreversible, tagger less severe than irreversible: 4" in out
    assert "Over-tagged items: 0" in out and "**FAIL** against these DECIDED criteria" in out and out.count("**NOT met**") == 2
    assert "| T01 | tool_T01 | irreversible | read_only |" in out


def test_mixed_case_matches_hand_computed_values(tmp_path, capsys):
    assert run(tmp_path, [R, S, I, I], [R, S, I, S]) == 0
    out = capsys.readouterr().out
    assert "Exact agreement: 3 of 4 (75.0%)" in out and "Cohen's kappa: 0.636" in out and "weighted kappa (read_only < state_changing < irreversible): 0.714" in out
    assert "Under-tagged items: 1" in out and "Human irreversible, tagger read_only: 0" in out
    assert "allowed at most 0: **NOT met**" in out and "allowed at most 3: **met**" in out and "**FAIL**" in out  # one irreversible under-tag breaks criterion 1 only


def test_decided_gate_counts_total_under_tags_and_ignores_over_tags(tmp_path, capsys):
    assert run(tmp_path, [R, R, S, I, I, I], [S, S, S, I, I, I]) == 0  # two over-tags, no under-tag
    out = capsys.readouterr().out
    assert "Over-tagged items: 2" in out and "Under-tagged items: 0" in out and "**PASS**" in out and "Reported, not gating: over-tags 2" in out
    assert run(tmp_path, [S, S, S, S, R, R], [R, R, R, R, R, R]) == 0  # four under-tags, none irreversible
    out = capsys.readouterr().out
    assert "Total under-tags (tagger less severe than the human, any class): 4 of 6; allowed at most 3: **NOT met**" in out and "allowed at most 0: **met**" in out and "**FAIL**" in out
    assert run(tmp_path, [S, S, S, S, R, R], [R, R, R, R, R, R], **{"--max-under-tags": 4}) == 0
    assert "**PASS**" in capsys.readouterr().out


def test_exactly_three_under_tags_still_pass(tmp_path, capsys):
    assert run(tmp_path, [S, S, S, R], [R, R, R, R]) == 0
    assert "3 of 4; allowed at most 3: **met**" in capsys.readouterr().out


def test_kappa_functions_directly():
    k, kw = score.kappas([0, 1, 2, 2], [0, 1, 2, 1])
    assert k == pytest.approx(0.6363636, abs=1e-6) and kw == pytest.approx(5 / 7)
    assert score.kappas([1, 1, 1], [1, 1, 1]) == (None, None)
    assert score.kappas([0, 1, 2, 0], [0, 1, 2, 0]) == (1.0, 1.0)


def test_bootstrap_is_deterministic_and_handles_degenerate_resamples(tmp_path):
    rows = score.load(*write(tmp_path, [R, S, I, I, S, R, I], [R, S, I, S, S, R, R]))
    a, b = score.bootstrap(rows), score.bootstrap(rows)
    assert a == b and a["kappa"][0] <= a["kappa"][1] and a["weighted"][0] <= a["weighted"][1]
    sub = tmp_path / "x"
    sub.mkdir()
    mostly = score.load(*write(sub, [R, R, R, R, S], [R, R, R, R, S]))
    assert score.bootstrap(mostly)["skipped"] > 0


def test_by_source_and_variant_groups(tmp_path, capsys):
    assert run(tmp_path, [R, S, I, R, I], [R, S, S, R, I], groups=["B1", "B1", "B1", "", ""], sources=["inert", "inert", "inert", "external", "external"]) == 0
    out = capsys.readouterr().out
    assert "| inert | 3 | 2 of 3 | 1 | 0 |" in out and "| external | 2 | 2 of 2 | 0 | 0 |" in out
    assert "| B1 | T01, T02, T03 | tool_T01 | read_only, state_changing, irreversible | read_only, state_changing, state_changing | no | 2 of 3 |" in out
    assert "All groups: 2 of 3 item pairs" in out


def test_blank_label_is_refused_and_nothing_is_written(tmp_path, capsys):
    items, other = write(tmp_path, [R, "", I], [R, S, I])
    assert score.main([str(items), str(other)]) == 2
    assert "blank human_label" in capsys.readouterr().err and not list(tmp_path.glob("handcheck_b_results*"))
    with pytest.raises(SystemExit):
        score.load(items, other)


def test_whitespace_only_label_counts_as_blank(tmp_path):
    items, other = write(tmp_path, [R, "   ", I], [R, S, I])
    with pytest.raises(SystemExit, match="blank human_label"):
        score.load(items, other)


def test_invalid_label_is_refused(tmp_path, capsys):
    items, other = write(tmp_path, [R, "irreversable", I], [R, S, I])
    assert score.main([str(items), str(other)]) == 2
    assert "invalid human_label" in capsys.readouterr().err and not list(tmp_path.glob("handcheck_b_results*"))


def test_labels_are_accepted_case_and_space_insensitively(tmp_path):
    items, other = write(tmp_path, [" Read_Only ", "STATE_CHANGING", "irreversible"], [R, S, I])
    assert [r["human"] for r in score.load(items, other)] == [R, S, I]


def test_mismatched_item_ids_are_refused(tmp_path):
    items, other = write(tmp_path, [R, S, I], [R, S, I])
    rows = list(csv.reader(open(other)))
    rows[1][0] = "T99"
    with open(other, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    with pytest.raises(SystemExit, match="different item ids"):
        score.load(items, other)


def test_existing_results_files_are_never_overwritten(tmp_path, capsys):
    (tmp_path / "handcheck_b_results.md").write_text("KEEP ME")
    items, other = write(tmp_path, [R, S, I], [R, S, I])
    assert score.main([str(items), str(other)]) == 0
    assert (tmp_path / "handcheck_b_results.md").read_text() == "KEEP ME" and (tmp_path / "handcheck_b_results_2.md").exists()
    assert score.main([str(items), str(other)]) == 0
    assert (tmp_path / "handcheck_b_results_3.md").exists() and (tmp_path / "handcheck_b_results.md").read_text() == "KEEP ME"
    assert "handcheck_b_results_3.md" in capsys.readouterr().out


def test_out_dir_option(tmp_path):
    items, other = write(tmp_path, [R, S, I], [R, S, I])
    out = tmp_path / "elsewhere"
    out.mkdir()
    assert score.main([str(items), str(other), "--out-dir", str(out)]) == 0
    assert (out / "handcheck_b_results.md").exists() and not (tmp_path / "handcheck_b_results.md").exists()
