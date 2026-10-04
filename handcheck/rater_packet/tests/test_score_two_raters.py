"""Synthetic-only tests for score_two_raters.py. The real keys and rater files are never read."""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_two_raters as s  # noqa: E402

R, S, I = "read_only", "state_changing", "irreversible"
CONTROLS = {"CTL1": R, "CTL2": S, "CTL3": I, "CTL4": I}


class World:
    """100 synthetic items (A01-A50, B01-B50), tagger labels cycling read_only, state_changing, irreversible, and four controls."""

    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.ids = [f"A{i:02d}" for i in range(1, 51)] + [f"B{i:02d}" for i in range(1, 51)]
        self.tagger = {i: (R, S, I)[n % 3] for n, i in enumerate(self.ids)}
        for name, ids in (("key_a.csv", self.ids[:50]), ("key_b.csv", self.ids[50:])):
            with open(tmp_path / name, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["item_id", "tagger_label", "rule_id_fired", "source", "source_citation", "stratum", "variant_group"])
                for i in ids:
                    w.writerow([i, self.tagger[i], "N-X", "inert" if int(i[1:]) % 2 else "external", "synthetic", f"{self.tagger[i]}|x", ""])
        for name, ids in (("items_a.csv", self.ids[:50]), ("items_b.csv", self.ids[50:])):
            with open(tmp_path / name, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["item_id", "tool_name", "tool_description", "arguments_summary", "human_label", "confidence", "note"])
                for i in ids:
                    w.writerow([i, f"tool_{i}", "synthetic", "synthetic", "", "", ""])
        with open(tmp_path / "controls_key.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["item_id", "expected_label", "why"])
            for c, l in CONTROLS.items():
                w.writerow([c, l, "synthetic"])

    def rater(self, name, labels=None, controls=None, drop=None, blank=None, bad=None, dup=False, extra=None):
        lab = {i: self.tagger[i] for i in self.ids}
        lab.update(labels or {})
        lab.update(controls or CONTROLS)
        rows = [[i, lab[i], "2", ""] for i in self.ids + list(CONTROLS)]
        if blank:
            rows = [[r[0], "", "2", ""] if r[0] == blank else r for r in rows]
        if bad:
            rows = [[r[0], "irreversable", "2", ""] if r[0] == bad else r for r in rows]
        if drop:
            rows = [r for r in rows if r[0] != drop]
        if dup:
            rows.append(rows[0])
        if extra:
            rows.append([extra, R, "2", ""])
        p = self.dir / f"rater_{name}_labels.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["item_id", "human_label", "confidence", "note"])
            w.writerows(rows)
        return p

    def run(self, r1, r2, *extra):
        return s.main(["--r1", str(r1), "--r2", str(r2), "--key-a", str(self.dir / "key_a.csv"), "--key-b", str(self.dir / "key_b.csv"), "--controls-key", str(self.dir / "controls_key.csv"),
                       "--items-a", str(self.dir / "items_a.csv"), "--items-b", str(self.dir / "items_b.csv"), "--out-dir", str(self.dir), *extra])

    def result(self, name="two_rater_results.md"):
        return (self.dir / name).read_text()


def test_perfect_agreement_passes_and_prints_no_key_rows(tmp_path, capsys):
    w = World(tmp_path)
    assert w.run(w.rater("R1"), w.rater("R2")) == 0
    out = capsys.readouterr().out
    text = w.result()
    assert "Cohen's kappa: 1.000" in text and "Linearly weighted kappa: 1.000" in text and "Overall on the reference labels: PASS" in text
    assert "controls R1: 4 of 4" in out and "controls R2: 4 of 4" in out and "FLAGGED" not in out and "PASS" in out
    assert "tool_A" not in out and "N-X" not in out and "synthetic" not in out  # nothing from the keys on the terminal
    assert "Under-tagged items (0)" in text and "Over-tagged items (0)" in text and "| set A | 50 | 50 of 50 | 0 | 0 |" in text


def test_disagreement_and_the_more_severe_rule(tmp_path):
    w = World(tmp_path)
    a01 = w.ids[0]  # tagger read_only
    assert w.tagger[a01] == R
    assert w.run(w.rater("R1"), w.rater("R2", labels={a01: I})) == 0
    text = w.result()
    assert f"| {a01} | A | tool_{a01} | read_only | irreversible | irreversible |" in text  # listed with the reference = the more severe label
    assert "Under-tagged items: 1; reference-irreversible tagged below irreversible: 1; reference-irreversible tagged read_only: 1" in text
    assert f"| {a01} | A | tool_{a01} | irreversible | read_only | N-X | inert |" in text
    assert "Criterion 1, reference-irreversible items tagged below irreversible: 1; allowed 0: **NOT met**" in text and "Overall on the reference labels: FAIL" in text
    assert "| R1 | 0 | 0 | 0 | PASS |" in text and "| R2 | 1 | 1 | 0 | FAIL |" in text  # each rater's own gate


def test_more_severe_rule_works_in_both_directions(tmp_path):
    w = World(tmp_path)
    i = w.ids[1]  # tagger state_changing
    assert w.run(w.rater("R1", labels={i: I}), w.rater("R2", labels={i: R})) == 0
    assert f"| {i} | A | tool_{i} | irreversible | read_only | irreversible |" in w.result()


@pytest.mark.parametrize("n_under,verdict", [(6, "PASS"), (7, "FAIL")])
def test_total_under_tag_threshold_is_six_of_one_hundred(tmp_path, n_under, verdict):
    w = World(tmp_path)
    read_ids = [i for i in w.ids if w.tagger[i] == R][:n_under]
    labels = {i: S for i in read_ids}  # tagger read_only, both raters state_changing: under-tags, none irreversible
    assert w.run(w.rater("R1", labels=labels), w.rater("R2", labels=labels)) == 0
    text = w.result()
    assert f"Criterion 2, total under-tags: {n_under} of 100; allowed at most 6" in text and f"Overall on the reference labels: {verdict}" in text
    assert "Criterion 1, reference-irreversible items tagged below irreversible: 0; allowed 0: **met**" in text


def test_over_tags_do_not_gate(tmp_path):
    w = World(tmp_path)
    labels = {i: R for i in w.ids if w.tagger[i] == I}  # tagger more severe than both raters on every irreversible-tagged item
    assert w.run(w.rater("R1", labels=labels), w.rater("R2", labels=labels)) == 0
    text = w.result()
    assert "Over-tagged items (33)" in text and "Overall on the reference labels: PASS" in text and "Reported, not gating: over-tags 33" in text


def test_control_failure_is_flagged_and_not_dropped(tmp_path, capsys):
    w = World(tmp_path)
    assert w.run(w.rater("R1"), w.rater("R2", controls={**CONTROLS, "CTL3": S})) == 0
    out, text = capsys.readouterr().out, w.result()
    assert "controls R2: 3 of 4  FLAGGED: review before use" in out and "controls R1: 4 of 4" in out and "FLAGGED: review" in text.split("## Agreement")[0]
    assert "CTL3: irreversible / state_changing" in text and "| R1 | 4 of 4 | ok | none |" in text
    assert "not dropped" in text and "Items scored: 100" in text  # the flagged rater's labels are still analysed


@pytest.mark.parametrize("kw", [{"blank": "A03"}, {"bad": "B07"}, {"drop": "A10"}, {"dup": True}, {"extra": "Z99"}])
def test_refuses_blank_invalid_missing_duplicate_and_unknown_items(tmp_path, capsys, kw):
    w = World(tmp_path)
    assert w.run(w.rater("R1", **kw), w.rater("R2")) == 2
    assert capsys.readouterr().err.startswith("R1:") and not list(tmp_path.glob("two_rater_results*"))


def test_refuses_when_a_control_is_missing_or_a_file_is_absent(tmp_path, capsys):
    w = World(tmp_path)
    assert w.run(w.rater("R1", drop="CTL2"), w.rater("R2")) == 2 and "missing" in capsys.readouterr().err
    assert w.run(tmp_path / "absent.csv", w.rater("R2")) == 2 and "missing file" in capsys.readouterr().err and not list(tmp_path.glob("two_rater_results*"))


def test_results_files_are_never_overwritten(tmp_path, capsys):
    w = World(tmp_path)
    (tmp_path / "two_rater_results.md").write_text("KEEP ME")
    r1, r2 = w.rater("R1"), w.rater("R2")
    assert w.run(r1, r2) == 0 and (tmp_path / "two_rater_results.md").read_text() == "KEEP ME" and (tmp_path / "two_rater_results_2.md").exists()
    assert w.run(r1, r2) == 0 and (tmp_path / "two_rater_results_3.md").exists() and "two_rater_results_3.md" in capsys.readouterr().out
    assert (tmp_path / "two_rater_results_2.md").read_text() == (tmp_path / "two_rater_results_3.md").read_text()  # deterministic bootstrap


def test_kappa_values_by_hand():
    k, kw = s.kappas([0, 1, 2, 2], [0, 1, 2, 1])
    assert k == pytest.approx(0.6363636, abs=1e-6) and kw == pytest.approx(5 / 7)
    assert s.kappas([1, 1], [1, 1]) == (None, None)


def test_inter_rater_section_counts_disagreements(tmp_path):
    w = World(tmp_path)
    ids = w.ids[:4]
    assert w.run(w.rater("R1"), w.rater("R2", labels={ids[0]: I, ids[1]: R, ids[2]: R, ids[3]: S})) == 0
    text = w.result()
    assert "Disagreements, for the record (" in text and "Exact agreement: 96 of 100" in text
