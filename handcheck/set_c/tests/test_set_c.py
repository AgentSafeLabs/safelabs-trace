"""Set C checks: composition, overlap, shuffle, controls, form. Reads only set C files and the A/B item files and pools (for the overlap check).
Opens no key, result, labelled or void file and never touches the tagger."""
import csv, collections, json, random, re, shutil, subprocess
from pathlib import Path
import pytest

C = Path(__file__).resolve().parent.parent
ST = C.parent
read = lambda p: list(csv.DictReader(open(p, newline="", encoding="utf-8")))
norm = lambda s: re.sub(r"\s+", " ", s.strip().lower())
items, pool, cmap = read(C / "handcheck_c_items.csv"), read(C / "items_pool_c.csv"), read(C / "chosen_map_c.csv")
by_pool = {r["pool_id"]: r for r in pool}
chosen = [by_pool[m["pool_id"]] for m in cmap]
AB = [r for f in ("1b_handcheck/items_pool.csv", "1b_handcheck_b/items_pool_b.csv", "1b_handcheck/handcheck_items.csv", "1b_handcheck_b/handcheck_b_items.csv") for r in read(ST / f)]


def test_items_file_shape_and_ids():
    assert list(items[0]) == ["item_id", "tool_name", "tool_description", "arguments_summary"]
    assert [r["item_id"] for r in items] == [f"HD{i:03d}" for i in range(1, 101)]
    assert all(r["tool_name"] and r["tool_description"] and r["arguments_summary"] for r in items)
    assert not any("label" in k or "key" in k for k in items[0])


def test_items_match_the_chosen_pool_rows_and_the_seeded_shuffle():
    assert len(cmap) == 100 and len({m["pool_id"] for m in cmap}) == 100
    for it, ch in zip(items, chosen):
        assert (it["tool_name"], it["tool_description"], it["arguments_summary"]) == (ch["tool_name"], ch["tool_description"], ch["arguments_summary"])
    # re-derive the order: primaries that passed the overlap check, refilled from spares in pool order, shuffled with seed 20261005
    ok = [r for r in pool if not r["excluded_overlap"]]
    prim, spares = [r for r in ok if not r["spare"]], [r for r in ok if r["spare"]]
    sel = prim[:100] if len(prim) >= 100 else prim + spares[: 100 - len(prim)]
    random.Random(20261005).shuffle(sel)
    assert [r["pool_id"] for r in sel] == [m["pool_id"] for m in cmap]


def test_no_overlap_with_sets_a_and_b():
    used_pairs = {(norm(r["tool_name"]), norm(r["arguments_summary"])) for r in AB}
    group_tools = {norm(r["tool_name"]) for r in AB if r.get("variant_group")}
    assert not [r for r in items if (norm(r["tool_name"]), norm(r["arguments_summary"])) in used_pairs]
    assert not [r for r in chosen if r["variant_group"] and norm(r["tool_name"]) in group_tools]
    assert not [r for r in chosen if r["obscure"] and norm(r["tool_name"]) in {norm(x["tool_name"]) for x in AB}]
    assert len({(r["tool_name"], r["arguments_summary"]) for r in items}) == 100  # no duplicates inside set C


def test_composition_targets():
    n = collections.Counter(r["source"] for r in chosen)
    assert n["external"] >= 50 and n["inert"] <= 25 and sum(n.values()) == 100
    assert sum(1 for r in chosen if r["obscure"]) >= 15 and all(r["source"] == "synthetic" for r in chosen if r["obscure"])
    groups = collections.Counter(r["variant_group"] for r in chosen if r["variant_group"])
    assert sum(groups.values()) >= 15 and min(groups.values()) >= 2
    for g in groups:  # a group is one tool with different arguments
        assert len({r["tool_name"] for r in chosen if r["variant_group"] == g}) == 1
    assert max(collections.Counter(r["family"] for r in chosen).values()) <= 4
    assert not [r for r in chosen if r["spare"] and r["pool_id"] not in {m["pool_id"] for m in cmap}]


def test_obscure_tools_state_what_they_do_and_use_placeholders_only():
    for r in (x for x in chosen if x["obscure"]):
        assert len(r["tool_description"].split()) >= 6 and not re.search(r"https?://(?!example\.com)", r["arguments_summary"])
    for r in chosen:
        assert not re.search(r"https?://(?!example\.com|www\.example\.com|status\.example\.com)", r["arguments_summary"]), r["tool_name"]


def test_pool_has_no_label_or_tagger_columns_and_sources_are_cited():
    assert not [c for c in pool[0] if re.search(r"label|key|severity|tagger|mix", c)]
    assert all(r["source_citation"] for r in pool) and all(re.search(r":\d+$", r["source_citation"]) for r in pool if r["source"] == "external")
    assert all(json.loads(r["arguments_json"]) is not None for r in pool)


def test_controls_are_new_and_unambiguous_looking():
    ctl, key = read(C / "controls_c.csv"), read(C / "controls_c_key.csv")
    assert [r["item_id"] for r in ctl] == ["CTC1", "CTC2", "CTC3", "CTC4"] and [r["item_id"] for r in key] == ["CTC1", "CTC2", "CTC3", "CTC4"]
    assert {r["expected_label"] for r in key} == {"read_only", "state_changing", "irreversible"}
    old = {norm(r["tool_name"]) for r in AB} | {norm(r["tool_name"]) for r in read(ST / "1b_rater_packet" / "controls.csv")}
    guide = (ST / "1b_handcheck" / "labelling_guide.md").read_text()
    for r in ctl:
        assert norm(r["tool_name"]) not in old and r["tool_name"] not in guide
        assert r["tool_name"] not in {x["tool_name"] for x in items}


def test_build_scripts_never_import_the_tagger_and_no_result_files_exist_here():
    for f in ("build_items_c.py", "build_form_c.py", "extract_c.py"):
        t = (C / f).read_text()
        assert not re.search(r"^\s*(from|import)\s+safelabs_trace", t, re.M), f
    assert not [p for p in C.glob("*") if re.search(r"result|labelled|void|_labels\.csv|rater_R", p.name)]


FORM = (C / "rater_form_c.html").read_text()


def test_form_contents():
    data = json.loads(re.search(r'<script id="items-data" type="application/json">(.*?)</script>', FORM, re.S).group(1).replace("<\\/", "</"))
    assert len(data) == 104 and [d["item_id"] for d in data][:3] == ["HD001", "HD002", "HD003"] and data[-1]["item_id"] == "CTC4"
    assert all(set(d) == {"item_id", "tool_name", "tool_description", "arguments_summary"} for d in data)
    assert 'a.download = "rater_" + rater + "_labels_c.csv"' in FORM and "safelabs_trace_hand_check_c_v1_" in FORM and "safelabs-hand-check-c:" in FORM
    # the guide block is the accepted guide text, rendered by the same function the original builder uses (build_form_c.py is a copy of it)
    import importlib.util, sys
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("build_form_c", C / "build_form_c.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert m.guide_html((ST / "1b_handcheck" / "labelling_guide.md").read_text(encoding="utf-8")) in FORM
    assert "tagger" not in FORM.lower() and "severity" not in FORM.lower()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_form_pure_functions_under_node(tmp_path):
    pure = re.search(r"/\* PURE-START \*/(.*?)/\* PURE-END \*/", FORM, re.S).group(1)
    js = pure + """
const ids = Array.from({length: 104}, (_, i) => 'X' + i);
const a = orderFor(ids, 'R1'), b = orderFor(ids, 'R2'), a2 = orderFor(ids.slice().reverse(), 'R1');
console.log(JSON.stringify({perm: a.slice().sort().join() === ids.slice().sort().join(), same: a.join() === a2.join(), differs: a.join() !== b.join(),
  csv: buildCsv(['b','a'], {a: {label: 'read_only', conf: '3', note: 'x, "y"'}, b: {label: 'irreversible', conf: '1'}}), done: isComplete(['a'], {a: {label: 'x', conf: '1'}}), notdone: isComplete(['a'], {})}));
"""
    p = tmp_path / "t.js"; p.write_text(js)
    out = json.loads(subprocess.run(["node", str(p)], capture_output=True, text=True, check=True).stdout)
    assert out["perm"] and out["same"] and out["differs"] and out["done"] and not out["notdone"]
    assert out["csv"] == 'item_id,human_label,confidence,note\na,read_only,3,"x, ""y"""\nb,irreversible,1,\n'
