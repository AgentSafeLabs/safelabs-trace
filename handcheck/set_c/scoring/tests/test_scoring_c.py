"""Synthetic-only tests for make_keys_c.py and score_two_raters_c.py. No real item, label or key is read except the hash check of the frozen tagger files."""
import csv
import hashlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import make_keys_c as mk  # noqa: E402
import score_two_raters_c as sc  # noqa: E402

IDS = [f"HD{i:03d}" for i in range(1, 101)]
CTL = {"CTC1": "read_only", "CTC2": "state_changing", "CTC3": "irreversible", "CTC4": "irreversible"}
TOOLS = {i: f"tool_{n}" for n, i in enumerate(IDS)}


def write(p: Path, header: list[str], rows: list[list]) -> Path:
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def key_file(p, labels, name="key.csv"):
    return write(p / name, ["item_id", "tagger_label", "rule_ids", "basis", "source", "variant_group"],
                 [[i, labels[i], "D-X|N-Y", "name_rule", "synthetic" if n % 2 else "external", "V1" if n % 5 == 0 else ""] for n, i in enumerate(IDS)])


def rater_file(p, labels, name, controls=None):
    rows = [[i, labels[i], "3", ""] for i in IDS] + [[c, (controls or CTL)[c], "3", ""] for c in CTL]
    return write(p / name, ["item_id", "human_label", "confidence", "note"], rows)


@pytest.fixture
def env(tmp_path):
    items = write(tmp_path / "items.csv", ["item_id", "tool_name", "tool_description", "arguments_summary"], [[i, TOOLS[i], "d", "a: 1"] for i in IDS])
    ctl = write(tmp_path / "ctl.csv", ["item_id", "expected_label"], [[c, v] for c, v in CTL.items()])
    base = {i: ("read_only", "state_changing", "irreversible")[n % 3] for n, i in enumerate(IDS)}  # 34 read, 33 state, 33 irreversible
    return tmp_path, items, ctl, base


def run(env, key_labels, r1_labels, r2_labels, extra=(), controls1=None, controls2=None, tag=""):
    tmp, items, ctl, _ = env
    k = key_file(tmp, key_labels, f"key{tag}.csv")
    r1, r2 = rater_file(tmp, r1_labels, f"r1{tag}.csv", controls1), rater_file(tmp, r2_labels, f"r2{tag}.csv", controls2)
    return sc.main(["--r1", str(r1), "--r2", str(r2), "--key", str(k), "--controls-key", str(ctl), "--items", str(items), "--out-dir", str(tmp), *extra])


def results(tmp, n=1):
    return (tmp / ("two_rater_results_c.md" if n == 1 else f"two_rater_results_c_{n}.md")).read_text()


def lower(label):
    return {"irreversible": "state_changing", "state_changing": "read_only", "read_only": "read_only"}[label]


def test_pass_when_the_tagger_equals_the_reference(env, capsys):
    tmp, _, _, base = env
    assert run(env, base, base, base) == 0
    text = results(tmp)
    assert "**Overall on the reference labels (the more severe of R1 and R2): PASS.**" in text and "met**" in text
    out = capsys.readouterr().out
    assert "PASS" in out and "controls R1: 4 of 4" in out and "tool_" not in out and "D-X" not in out  # no key rows on the terminal


def test_criterion_1_fails_on_one_irreversible_under_tag_even_with_few_under_tags(env):
    tmp, _, _, base = env
    key = dict(base)
    first_irr = next(i for i in IDS if base[i] == "irreversible")
    key[first_irr] = "state_changing"
    run(env, key, base, base)
    text = results(tmp)
    assert "allowed 0: **NOT met**" in text and "allowed at most 6: **met**" in text and "FAIL.**" in text


def test_criterion_2_fails_at_seven_under_tags_and_passes_at_six(env):
    tmp, _, _, base = env
    reads = [i for i in IDS if base[i] == "state_changing"][:7]
    key6 = {i: ("read_only" if i in reads[:6] else base[i]) for i in IDS}
    key7 = {i: ("read_only" if i in reads else base[i]) for i in IDS}
    run(env, key6, base, base, tag="6")
    assert "total under-tags: 6 of 100; allowed at most 6: **met**" in results(tmp) and "PASS.**" in results(tmp)
    run(env, key7, base, base, tag="7")
    t2 = results(tmp, 2)
    assert "allowed 0: **met**" in t2 and "total under-tags: 7 of 100; allowed at most 6: **NOT met**" in t2 and "FAIL.**" in t2


def test_reference_is_the_more_severe_of_the_two_raters(env):
    tmp, _, _, base = env
    r1 = {i: "read_only" for i in IDS}
    r2 = dict(base)
    key = dict(base)  # equals R2, so under R1 alone nothing is under-tagged, but the reference is R2's (more severe)
    run(env, key, r1, r2)
    text = results(tmp)
    assert "exact agreement, tagger and reference: 100 of 100" in text.lower() and "PASS.**" in text
    # a tagger that equals the LESS severe rater is under-tagged against the reference
    tmp2 = tmp / "b"
    tmp2.mkdir()
    env2 = (tmp2, *env[1:])
    run(env2, r1, r1, r2)
    t2 = results(tmp2)
    assert "FAIL.**" in t2 and "reference-irreversible tagged below irreversible: 33" in t2


def test_consensus_only_under_tag_count_and_over_tags(env):
    tmp, _, _, base = env
    r1, r2 = dict(base), dict(base)
    key = dict(base)
    states = [i for i in IDS if base[i] == "state_changing"]
    a, b, c = states[:3]
    key[a] = key[b] = key[c] = "read_only"            # three under-tags
    r2[a] = "read_only"                               # on item a the raters disagree (reference still state_changing, R1)
    over = [i for i in IDS if base[i] == "read_only"][0]
    key[over] = "irreversible"                         # one over-tag
    run(env, key, r1, r2)
    text = results(tmp)
    assert "Under-tags on items where R1 and R2 agree: 2 (of the 3 under-tags)." in text and "Over-tags: 1." in text


def test_control_flag_for_a_rater_below_four_of_four(env):
    tmp, _, _, base = env
    bad = dict(CTL)
    bad["CTC3"] = "read_only"
    run(env, base, base, base, controls2=bad)
    text = results(tmp)
    assert "| R1 | 4 of 4 | ok |" in text and "| R2 | 3 of 4 | **FLAGGED" in text and "CTC3: irreversible / read_only" in text


@pytest.mark.parametrize("breakage", ["missing_item", "blank", "invalid", "duplicate", "unknown_id", "missing_control"])
def test_refuses_bad_label_files_and_writes_nothing(env, breakage, capsys):
    tmp, items, ctl, base = env
    k = key_file(tmp, base)
    rows = [[i, base[i], "3", ""] for i in IDS] + [[c, v, "3", ""] for c, v in CTL.items()]
    if breakage == "missing_item":
        rows = [r for r in rows if r[0] != "HD050"]
    elif breakage == "blank":
        rows[3][1] = ""
    elif breakage == "invalid":
        rows[3][1] = "harmless"
    elif breakage == "duplicate":
        rows.append(list(rows[0]))
    elif breakage == "unknown_id":
        rows.append(["HD999", "read_only", "3", ""])
    elif breakage == "missing_control":
        rows = [r for r in rows if r[0] != "CTC2"]
    bad = write(tmp / "bad.csv", ["item_id", "human_label", "confidence", "note"], rows)
    good = rater_file(tmp, base, "good.csv")
    rc = sc.main(["--r1", str(bad), "--r2", str(good), "--key", str(k), "--controls-key", str(ctl), "--items", str(items), "--out-dir", str(tmp)])
    assert rc == 2 and not list(tmp.glob("two_rater_results_c*.md")) and capsys.readouterr().err.strip()


def test_refuses_a_missing_file_and_a_wrong_key_size(env):
    tmp, items, ctl, base = env
    good = rater_file(tmp, base, "good.csv")
    assert sc.main(["--r1", str(tmp / "nope.csv"), "--r2", str(good), "--key", str(key_file(tmp, base)), "--controls-key", str(ctl), "--out-dir", str(tmp)]) == 2
    short = write(tmp / "short_key.csv", ["item_id", "tagger_label", "rule_ids", "basis", "source", "variant_group"], [[i, "read_only", "", "", "", ""] for i in IDS[:99]])
    assert sc.main(["--r1", str(good), "--r2", str(good), "--key", str(short), "--controls-key", str(ctl), "--out-dir", str(tmp)]) == 2
    badkey = write(tmp / "bad_key.csv", ["item_id", "tagger_label", "rule_ids", "basis", "source", "variant_group"], [[i, "harmless", "", "", "", ""] for i in IDS])
    assert sc.main(["--r1", str(good), "--r2", str(good), "--key", str(badkey), "--controls-key", str(ctl), "--out-dir", str(tmp)]) == 2
    assert not list(tmp.glob("two_rater_results_c*.md"))


def test_never_overwrites_results(env):
    tmp, _, _, base = env
    for n in (1, 2, 3):
        run(env, base, base, base, tag=str(n))
    names = sorted(p.name for p in tmp.glob("two_rater_results_c*.md"))
    assert names == ["two_rater_results_c.md", "two_rater_results_c_2.md", "two_rater_results_c_3.md"]


def test_compare_key_is_a_labelled_side_by_side_and_not_gating(env):
    tmp, _, _, base = env
    v1 = {i: "read_only" for i in IDS}
    cmp_path = key_file(tmp, v1, "v1.csv")
    run(env, base, base, base, extra=["--compare-key", str(cmp_path)])
    text = results(tmp)
    assert "Comparison, not gating: tagger v1" in text and "(comparison, not gating)" in text and "PASS.**" in text
    assert "would pass the gate | yes | no (informational)" in text


def test_weighted_kappa_bootstrap_uses_the_set_c_seed_and_is_deterministic(env):
    assert sc.SEED == 20261005 and sc.RESAMPLES == 10_000
    a = [n % 3 for n in range(100)]
    b = [(n + (n % 7 == 0)) % 3 for n in range(100)]
    assert sc.bootstrap(a, b) == sc.bootstrap(a, b)


def test_kappa_values(env):
    a = [0, 1, 2] * 10
    assert sc.kappas(a, a) == (1.0, 1.0)
    assert sc.kappas([0] * 5, [0] * 5) == (None, None)


# ---- make_keys_c ---------------------------------------------------------------------------------------------------------------
def fake_src(tmp, sev="x = 1\n", rules="{}"):
    d = tmp / "src"
    (d / "data").mkdir(parents=True)
    (d / "severity.py").write_text(sev)
    (d / "data" / "severity_rules.json").write_text(rules)
    return d


def test_hash_check_passes_on_matching_files_and_stops_on_a_mismatch(tmp_path):
    d = fake_src(tmp_path)
    exp = {"severity.py": hashlib.sha256(b"x = 1\n").hexdigest(), "data/severity_rules.json": hashlib.sha256(b"{}").hexdigest()}
    assert mk.verify_hashes(d, exp) == exp
    (d / "severity.py").write_text("x = 2\n")
    with pytest.raises(mk.HashMismatch, match="STOP"):
        mk.verify_hashes(d, exp)
    with pytest.raises(mk.HashMismatch, match="STOP"):
        mk.verify_hashes(tmp_path / "nowhere", exp)


def test_main_stops_before_writing_anything_when_the_tagger_hash_differs(tmp_path):
    d = fake_src(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(mk.HashMismatch):
        mk.main(["--repo-src", str(d), "--out-dir", str(out)])
    assert list(out.iterdir()) == []


def test_the_frozen_tagger_in_the_repo_matches_the_registered_hashes():
    got = mk.verify_hashes(mk.REPO_SRC)
    assert got["severity.py"].startswith("caff427f") and got["data/severity_rules.json"].startswith("28c0e58a")


def test_argument_parsing_keeps_values_with_semicolons_whole():
    assert mk.parse_arguments("(no arguments)") == {}
    assert mk.parse_arguments("cmd: ls -la; workdir: ./p") == {"cmd": "ls -la", "workdir": "./p"}
    assert mk.parse_arguments("code: import os; os.remove('x'); mode: fast") == {"code": "import os; os.remove('x')", "mode": "fast"}
    assert mk.parse_arguments("agent_config: {\"d\": \"x\"}") == {"agent_config": "{\"d\": \"x\"}"}
    with pytest.raises(ValueError):
        mk.parse_arguments("no colon here")


def test_tag_all_calls_the_taggers_as_a_handler_does_and_joins_pool_columns():
    calls = []

    class T:
        def __init__(self, label):
            self.label = label

        def tag_tool_call(self, name, args, declared, **kw):
            calls.append((self.label, name, args, declared, kw))
            return type("R", (), {"severity": "read_only", "rule_ids": ("N-A", "D-B"), "basis": "name_rule"})()

    items = [{"item_id": "HD001", "tool_name": "t", "tool_description": "Does a thing.", "arguments_summary": "a: 1; b: 2"}]
    pool = {"C001": {"tool_name": "t", "arguments_summary": "a: 1; b: 2", "source": "synthetic", "variant_group": "SG1"}}
    k2, k1 = mk.tag_all(items, pool, {"HD001": "C001"}, T("v2b"), T("v1"))
    assert k2 == [{"item_id": "HD001", "tagger_label": "read_only", "rule_ids": "N-A|D-B", "basis": "name_rule", "source": "synthetic", "variant_group": "SG1"}] == k1
    assert calls[0] == ("v2b", "t", {"a": "1", "b": "2"}, None, {"description": "Does a thing."})
    assert calls[1] == ("v1", "t", {"a": "1", "b": "2"}, None, {})  # v1 has no description input
