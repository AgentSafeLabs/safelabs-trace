"""Checks on the real packet files: the form is offline and blind, its data matches the item files, its behaviour works (node shim), and the documents say what they must.
No label is read, written or invented; no key is opened."""

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
STAGING = HERE.parent
FORM = (HERE / "rater_form.html").read_text(encoding="utf-8")
LABEL_WORDS = ("read_only", "state_changing", "irreversible")


def rows(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def data():
    m = re.search(r'id="items-data" type="application/json">(.*?)</script>', FORM, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


A = rows(STAGING / "1b_handcheck" / "handcheck_items.csv")
B = rows(STAGING / "1b_handcheck_b" / "handcheck_b_items.csv")
C = rows(HERE / "controls.csv")


def test_the_form_embeds_exactly_the_100_items_and_4_controls_with_four_fields_each():
    d = data()
    assert len(d) == 104 and all(list(x) == ["item_id", "tool_name", "tool_description", "arguments_summary"] for x in d)
    want = {r["item_id"]: {k: r[k] for k in ("item_id", "tool_name", "tool_description", "arguments_summary")} for r in A + B + C}
    assert {x["item_id"]: x for x in d} == want
    assert {x["item_id"] for x in d} >= {"CTL1", "CTL2", "CTL3", "CTL4"} and len({x["item_id"] for x in d}) == 104


def test_the_form_is_blind_no_key_names_no_tagger_words_no_label_next_to_an_item():
    for needle in ("handcheck_key", "handcheck_b_key", "controls_key", "key.csv", "tagger", "rule_id", "default_unknown", "severity_basis", "design.md"):
        assert needle not in FORM, needle
    for x in data():
        blob = json.dumps(x)
        assert not any(w in blob for w in LABEL_WORDS), x["item_id"]  # an item record never carries a label word
        assert not any(x[k] in LABEL_WORDS for k in x)


def test_the_form_is_offline_no_external_scripts_fonts_requests_or_urls():
    assert not re.findall(r"<script[^>]*\ssrc=", FORM) and "<link" not in FORM and "@import" not in FORM and "url(" not in FORM
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "navigator.sendBeacon", "import(", "document.cookie", "eval("):
        assert banned not in FORM, banned
    for url in re.findall(r"https?://[^\s\"'<>)]*", FORM):
        assert url.startswith("https://example.com"), url


def test_urls_inside_item_text_are_example_com_only():
    for x in data():
        for url in re.findall(r"https?://[^\s\"']*", x["tool_description"] + " " + x["arguments_summary"]):
            assert url.startswith("https://example.com"), (x["item_id"], url)


def test_the_guide_panel_has_the_accepted_text_and_no_internal_notes():
    guide = (STAGING / "1b_handcheck" / "labelling_guide.md").read_text(encoding="utf-8")
    plain = re.sub(r"<[^>]+>", "", FORM)
    plain = plain.replace("&#x27;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    for line in re.findall(r"^- \*\*(?:read_only|state_changing|irreversible)\*\*: (.+)$", guide, re.M):
        assert re.sub(r"\*\*|`", "", line) in plain
    for line in re.findall(r"^\d+\. (.+)$", guide.split("## Decision rules")[1].split("## Worked examples")[0], re.M):
        assert re.sub(r"\*\*|`", "", line) in plain
    for tool in ("get_weather_forecast", "rename_project_folder", "empty_trash_bin"):
        assert tool in plain
    assert 'id="guide" open' in FORM and "<summary>" in FORM and "design.md" not in plain and "handcheck" not in plain


def test_the_three_label_choices_and_confidence_words_are_present_with_no_default():
    for text in ("read_only: only looks", "state_changing: changes, can be undone", "irreversible: cannot be undone", "1: guess", "2: fairly sure", "3: certain"):
        assert text in FORM
    assert "checked" not in re.sub(r"\.checked|checked =|:checked", "", re.sub(r"<script>.*?</script>", "", FORM, flags=re.S))  # no static default selection


def test_controls_are_new_unambiguous_and_not_worked_examples():
    ids = [r["item_id"] for r in C]
    assert ids == ["CTL1", "CTL2", "CTL3", "CTL4"]
    key = rows(HERE / "controls_key.csv")
    assert [r["expected_label"] for r in key] == ["read_only", "state_changing", "irreversible", "irreversible"]
    names = {r["tool_name"] for r in A + B}
    assert not {r["tool_name"] for r in C} & (names | {"get_weather_forecast", "rename_project_folder", "empty_trash_bin"})


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_form_behaves_in_a_dom_shim():
    out = subprocess.run(["node", str(HERE / "tests" / "form_behaviour.js"), str(HERE / "rater_form.html")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    assert d["beforeChoice"] == {"progress": "Answered 0 of 0", "downloadDisabled": True, "items": 0}
    r1 = d["afterR1"]
    assert r1["items"] == 104 and r1["progress"] == "Answered 0 of 104" and r1["downloadDisabled"] is True and r1["anyChecked"] == 0 and r1["noteBoxes"] == 104
    assert r1["labelTexts"] == ["read_only: only looks", "state_changing: changes, can be undone", "irreversible: cannot be undone"] and r1["confTexts"] == ["1: guess", "2: fairly sure", "3: certain"]
    assert d["orders"]["r1StableOnReselect"] and d["orders"]["r1VersusR2Differ"] and d["orders"]["r2Count"] == 104
    assert d["at103"] == {"progress": "Answered 103 of 104", "downloadDisabled": True} and d["labelOnly"]["downloadDisabled"] is True  # a label without a confidence does not count
    assert d["complete"] == {"progress": "Answered 104 of 104", "downloadDisabled": False}
    assert d["download"]["filename"] == "rater_R1_labels.csv" and d["download"]["type"].startswith("text/csv")
    reader = list(csv.reader(d["download"]["csv"].splitlines(keepends=False)))
    assert reader[0] == ["item_id", "human_label", "confidence", "note"] and len(reader) == 105 and [r[0] for r in reader[1:]] == sorted(x["item_id"] for x in data())
    assert all(r[1] in LABEL_WORDS and r[2] in ("1", "2", "3") for r in reader[1:]) and any('has, comma "quote"' in r[3] for r in reader[1:])
    assert d["resume"]["progress"] == "Answered 104 of 104" and d["resume"]["checked"] == 208 and d["resume"]["firstNote"].startswith('has, comma "quote"')
    assert d["otherRater"] == {"progress": "Answered 0 of 104", "downloadDisabled": True} and d["nextButton"]["scrolledTo"] is True


def test_the_gate_addendum_states_the_decided_rules():
    t = (HERE / "gate_addendum_two_raters.md").read_text()
    for needle in ("2026-10-04", "all 100 items", "more severe", "at most 6 of 100", "Zero items whose reference label is irreversible", "10,000", "20261004", "fewer than 4 of 4",
                   "not silently dropped", "No rule change is made on the basis of these 100 items alone", "Each rater's gate result"):
        assert needle in t, needle


def test_brief_and_recruitment_texts():
    brief = (HERE / "rater_brief.md").read_text()
    rec = (HERE / "recruitment_message.md").read_text()
    assert "60" in brief and "75" in brief and "alone" in brief and "trick" in brief and "rater_form.html" in brief and "Download my answers" in brief
    for t in (brief, rec):
        assert not re.search(r"tagger|severity tagger|expected result|safelabs", t, re.I)
    assert rec.count("[FEE]") >= 2 and "<!--" in rec and "confidential" in rec.lower() and "personal data" in rec.lower()
