"""Checks on the real set B files: structure, no overlap with set A, and that label.py never touches the key. No label is read, written or invented."""

import csv
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SET_A = HERE.parent / "1b_handcheck"


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_the_items_file_has_exactly_the_blind_columns_and_blank_answers():
    r = rows(HERE / "handcheck_b_items.csv")
    assert len(r) == 50 and list(r[0].keys()) == ["item_id", "tool_name", "tool_description", "arguments_summary", "human_label", "confidence", "note"]
    assert sorted(x["item_id"] for x in r) == [f"HB{i:02d}" for i in range(1, 51)]
    assert all(x["human_label"] == x["confidence"] == x["note"] == "" for x in r)


def test_nothing_in_the_items_file_leaks_the_tagger_or_the_source():
    text = (HERE / "handcheck_b_items.csv").read_text().lower()
    assert not re.search(r"tagger|rule_id|severity_basis|default_unknown|\bN-[A-Z]+\b|inert tool|synthetic", text, re.I)


def test_no_item_in_set_b_duplicates_a_set_a_item():
    b = {(x["tool_name"], x["arguments_summary"]) for x in rows(HERE / "handcheck_b_items.csv")}
    a_items = {(x["tool_name"], x["arguments_summary"]) for x in rows(SET_A / "handcheck_items.csv")}
    a_pool = {(x["tool_name"], x["arguments_summary"]) for x in rows(SET_A / "items_pool.csv")}
    assert not b & a_items and not b & a_pool
    assert len(b) == 50  # no duplicates inside set B either
    pool_b = {(x["tool_name"], x["arguments_summary"]) for x in rows(HERE / "items_pool_b.csv")}
    assert not pool_b & a_items and not pool_b & a_pool


def test_set_b_uses_no_variant_group_tool_of_set_a():
    a_items = {(x["tool_name"], x["arguments_summary"]) for x in rows(SET_A / "handcheck_items.csv")}
    pool_a = rows(SET_A / "items_pool.csv")
    used = {x["variant_group"] for x in pool_a if x["variant_group"] and (x["tool_name"], x["arguments_summary"]) in a_items}
    tools_a = {x["tool_name"] for x in pool_a if x["variant_group"] in used}
    pool_b = rows(HERE / "items_pool_b.csv")
    assert not {x["tool_name"] for x in pool_b if x["variant_group"]} & tools_a


def test_label_py_never_references_the_key_file():
    src = (HERE / "label.py").read_text()
    for needle in ("handcheck_b_key", "_key.csv", "key.csv", "handcheck_key"):
        assert needle not in src, needle
    assert "open(" in src and src.count("handcheck_") == src.count("handcheck_b_items")  # the only data files it names are the items and the labelled copy


def test_the_labelling_guide_is_set_as_guide_plus_one_line():
    b = (HERE / "labelling_guide.md").read_text().split("\n")
    a = (SET_A / "labelling_guide.md").read_text().split("\n")
    assert b[0] == "Set B" and b[1] == "" and b[2:] == a


def test_pool_was_written_before_the_selection_and_has_no_tagger_columns():
    header = rows(HERE / "items_pool_b.csv")[0].keys()
    assert not {"tagger_label", "rule_id", "basis", "rule_id_fired"} & set(header)
