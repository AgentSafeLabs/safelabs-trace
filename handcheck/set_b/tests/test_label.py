"""label.py tests with scripted input on a synthetic three-item file (not the real items)."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import label  # noqa: E402


def make(tmp_path, n=3):
    p = tmp_path / "items.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(label.COLUMNS)
        for i in range(n):
            w.writerow([f"S{i + 1:02d}", f"tool_{i + 1}", "synthetic description", "synthetic arguments", "", "", ""])
    return p, tmp_path / "labelled.csv"


def feeder(answers):
    """An input function that answers from a list and raises EOFError when the list runs out (like a closed terminal)."""
    it = iter(answers)

    def input_fn(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return input_fn


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_full_run_saves_after_every_item_and_writes_all_columns(tmp_path):
    items, out = make(tmp_path)
    on_disk_at_prompt = []
    feed = feeder(["r", "1", "first note", "s", "2", "", "i", "3", "last note"])

    def input_fn(prompt):
        if prompt.startswith("Label") and out.exists():
            on_disk_at_prompt.append([x["human_label"] for x in rows(out)])  # what is already saved when the next item is asked
        return feed(prompt)

    shown = []
    assert label.main([str(items), str(out)], input_fn, shown.append) == 0
    assert on_disk_at_prompt == [["read_only", "", ""], ["read_only", "state_changing", ""]]
    r = rows(out)
    assert [(x["human_label"], x["confidence"], x["note"]) for x in r] == [("read_only", "1", "first note"), ("state_changing", "2", ""), ("irreversible", "3", "last note")]
    assert list(r[0].keys()) == label.COLUMNS
    assert any("Item 1 of 3" in s and "Back: type b to redo the previous item" in s for s in shown) and any("Item 3 of 3" in s for s in shown)
    assert any("All 3 items labelled" in s for s in shown)


def test_resumes_from_the_first_unlabelled_item(tmp_path):
    items, out = make(tmp_path)
    assert label.main([str(items), str(out)], feeder(["r", "1", "", "s", "2", ""]), lambda s: None) == 1  # two items answered, then the input ends
    assert [x["human_label"] for x in rows(out)] == ["read_only", "state_changing", ""]
    shown2 = []
    assert label.main([str(items), str(out)], feeder(["i", "3", "done"]), shown2.append) == 0
    assert any("Resuming: 2 of 3 already labelled" in s for s in shown2) and any("Item 3 of 3" in s for s in shown2) and not any("Item 1 of 3" in s for s in shown2)
    assert [x["human_label"] for x in rows(out)] == ["read_only", "state_changing", "irreversible"]


def test_back_redoes_the_previous_item_and_cannot_go_before_the_first(tmp_path):
    items, out = make(tmp_path)
    shown = []
    answers = ["b", "r", "1", "", "b", "i", "2", "changed", "s", "3", ""]  # b at item 1 is refused; b at item 2 redoes item 1; then item 1 and item 2 are answered
    assert label.main([str(items), str(out)], feeder(answers), shown.append) == 1  # three items, input ends at item 3
    r = rows(out)
    assert (r[0]["human_label"], r[0]["confidence"], r[0]["note"]) == ("irreversible", "2", "changed") and r[1]["human_label"] == "state_changing" and r[2]["human_label"] == ""
    assert any("no previous item" in s for s in shown)


def test_invalid_entries_are_asked_again(tmp_path):
    items, out = make(tmp_path, n=1)
    shown = []
    assert label.main([str(items), str(out)], feeder(["x", "", "read", "r", "5", "0", "2", "ok"]), shown.append) == 0
    assert sum("Please type one of" in s for s in shown) == 5 and rows(out)[0]["human_label"] == "read_only" and rows(out)[0]["confidence"] == "2"


def test_it_writes_only_the_labelled_file_and_leaves_the_items_file_alone(tmp_path):
    items, out = make(tmp_path)
    before = items.read_bytes()
    label.main([str(items), str(out)], feeder(["r", "1", "", "s", "1", "", "i", "1", ""]), lambda s: None)
    assert items.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == ["items.csv", "labelled.csv"]
