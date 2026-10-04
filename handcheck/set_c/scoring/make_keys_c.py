"""Computes the set C tagger keys: handcheck_c_key_v2b.csv (the test) and handcheck_c_key_v1.csv (comparison only).

Order of events: (1) verify the sha256 of the frozen v2b severity.py and severity_rules.json (STOP, writing nothing, if either differs); (2) load the v2b tagger from the
repo (read-only) and the v1 tagger from 1b_impl; (3) tag each of the 100 items exactly as a handler does at run time: tag_tool_call(name, arguments_dict, declared=None,
description=...) for v2b (v1 has no description input). Arguments are the item's real argument dict, rebuilt from arguments_summary ("k: v; k2: v2", splitting only
where the next segment starts with an identifier and a colon, so a value that itself contains "; " stays whole). Item -> pool row through chosen_map_c.csv; source and
variant_group come from the set C pool. Key files are create-only. Nothing is printed except counts, hashes and versions: no per-item label.
Columns: item_id, tagger_label, rule_ids, basis, source, variant_group (rule_ids joined with '|')."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ST = HERE.parent
REPO_SRC = ST.parent / "safelabs-trace" / "src" / "safelabs_trace"
V1_SRC = ST / "1b_impl" / "safelabs-trace" / "src" / "safelabs_trace"
SET_C = ST / "1b_handcheck_c"
EXPECTED = {"severity.py": "caff427f7afdf5e84d28b194f57045eb39dbd0fad43549b37a869c1ecba5558c",
            "data/severity_rules.json": "28c0e58aa5e9c0f91c6fd5aaa721567e9696fcd966e5316d567045c7ff20a8f2"}
FIELDS = ["item_id", "tagger_label", "rule_ids", "basis", "source", "variant_group"]


class HashMismatch(SystemExit):
    pass


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_hashes(src: Path, expected: dict[str, str] = EXPECTED) -> dict[str, str]:
    """The sha256 of each frozen file; raises HashMismatch (STOP) when any differs or is missing."""
    got: dict[str, str] = {}
    for rel, want in expected.items():
        p = Path(src) / rel
        if not p.is_file():
            raise HashMismatch(f"STOP: {p} is missing")
        got[rel] = sha256(p)
        if got[rel] != want:
            raise HashMismatch(f"STOP: sha256 of {rel} is {got[rel]}, expected {want}; the tagger is not the frozen v2b")
    return got


def parse_arguments(summary: str) -> dict[str, str]:
    """Rebuild the argument dict from an arguments_summary. '(no arguments)' -> {}. Split only before 'identifier: ' so values may contain '; '."""
    s = summary.strip()
    if not s or s == "(no arguments)":
        return {}
    out: dict[str, str] = {}
    for seg in re.split(r";\s+(?=[A-Za-z_][A-Za-z0-9_]*: )", s):
        k, sep, v = seg.partition(": ")
        if not sep:
            raise ValueError(f"cannot parse argument segment {seg[:30]!r}")
        out[k.strip()] = v.strip()
    return out


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def read_csv(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def tag_all(items: list[dict], pool_by_id: dict[str, dict], cmap: dict[str, str], v2b, v1) -> tuple[list[dict], list[dict]]:
    out2, out1 = [], []
    for it in items:
        pool = pool_by_id[cmap[it["item_id"]]]
        assert (pool["tool_name"], pool["arguments_summary"]) == (it["tool_name"], it["arguments_summary"]), it["item_id"]
        args = parse_arguments(it["arguments_summary"])
        t2 = v2b.tag_tool_call(it["tool_name"], args, None, description=it["tool_description"])
        t1 = v1.tag_tool_call(it["tool_name"], args, None)
        for out, t in ((out2, t2), (out1, t1)):
            out.append({"item_id": it["item_id"], "tagger_label": t.severity, "rule_ids": "|".join(t.rule_ids), "basis": t.basis,
                        "source": pool["source"], "variant_group": pool["variant_group"]})
    return out2, out1


def write_new(path: Path, rows: list[dict]) -> None:
    with open(path, "x", newline="", encoding="utf-8") as f:  # create-only
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-src", type=Path, default=REPO_SRC)
    ap.add_argument("--v1-src", type=Path, default=V1_SRC)
    ap.add_argument("--set-c", type=Path, default=SET_C)
    ap.add_argument("--out-dir", type=Path, default=HERE)
    a = ap.parse_args(argv)
    hashes = verify_hashes(a.repo_src)  # STOP before anything is computed
    v2b = load_module("sev_v2b", a.repo_src / "severity.py")
    v1 = load_module("sev_v1", a.v1_src / "severity.py")
    items = read_csv(a.set_c / "handcheck_c_items.csv")
    pool = {r["pool_id"]: r for r in read_csv(a.set_c / "items_pool_c.csv")}
    cmap = {r["item_id"]: r["pool_id"] for r in read_csv(a.set_c / "chosen_map_c.csv")}
    assert len(items) == 100 and [r["item_id"] for r in items] == [f"HD{i:03d}" for i in range(1, 101)]
    k2, k1 = tag_all(items, pool, cmap, v2b, v1)
    write_new(a.out_dir / "handcheck_c_key_v2b.csv", k2)
    write_new(a.out_dir / "handcheck_c_key_v1.csv", k1)
    pool_mismatch = sum(1 for it in items if parse_arguments(it["arguments_summary"]) != json.loads(pool[cmap[it["item_id"]]]["arguments_json"]))
    print(f"verified sha256: {hashes}")
    print(f"tagger_version v2b={v2b.TAGGER_VERSION} rules_version v2b={v2b.load_rules()['rules_version']}; v1 tagger_version={v1.TAGGER_VERSION} rules_version={v1.load_rules()['rules_version']}")
    print(f"wrote 2 key files with {len(k2)} rows each; items whose rebuilt argument dict differs from the pool's arguments_json: {pool_mismatch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
