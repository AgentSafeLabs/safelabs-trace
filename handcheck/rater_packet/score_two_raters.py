"""Score the two-rater hand check (gate_addendum_two_raters.md, 2026-10-04).

Usage:
  python score_two_raters.py [--r1 rater_R1_labels.csv] [--r2 rater_R2_labels.csv] [--key-a PATH] [--key-b PATH] [--controls-key controls_key.csv]
                             [--items-a PATH] [--items-b PATH] [--out-dir DIR] [--max-under-tags 6]

Inputs: the two rater files written by rater_form.html (item_id,human_label,confidence,note), the two set keys (read by path, only when this script runs) and controls_key.csv.
Refuses to run (writes nothing) when a rater file is missing an item, lists an unknown or duplicate item, or has a blank or invalid label. Writes two_rater_results.md
(then two_rater_results_2.md, _3, ...; never overwrites). The terminal output is limited to the file name, the gate verdicts and the control flags: key rows appear only in the
under-tag and over-tag tables of the results file.

Order for all kappas and for the reference label: read_only < state_changing < irreversible. Reference label = the more severe of R1 and R2. Gate on the reference labels over the
100 items: PASS needs (1) zero reference-irreversible items tagged below irreversible and (2) at most 6 under-tags (any class). Over-tags, exact agreement and weighted kappa are
reported, not gating. Each rater's own labels get the same gate, reported separately. A rater with fewer than 4 of 4 controls is flagged; labels are reviewed before use, not dropped.
Bootstrap: 10,000 resamples of the items, seed 20261004, 95% percentile interval; resamples with undefined kappa are skipped and counted."""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LABELS = ("read_only", "state_changing", "irreversible")
IDX = {l: i for i, l in enumerate(LABELS)}
SEED = 20261004
RESAMPLES = 10_000


class Refuse(SystemExit):
    """An input the scorer refuses."""


def read_csv(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        raise Refuse(f"missing file: {path}") from None


def load_keys(key_a: Path, key_b: Path, controls_key: Path, items_a: Path | None, items_b: Path | None) -> tuple[dict[str, dict], dict[str, str]]:
    """Per-item key rows (with set A or B and the tool name) and the expected control answers."""
    names: dict[str, str] = {}
    for p in (items_a, items_b):
        if p is not None and Path(p).exists():
            names.update({r["item_id"]: r.get("tool_name", "") for r in read_csv(Path(p))})
    keys: dict[str, dict] = {}
    for label, p in (("A", key_a), ("B", key_b)):
        for r in read_csv(Path(p)):
            if r["item_id"] in keys:
                raise Refuse(f"item id {r['item_id']} appears in both keys")
            if r["tagger_label"] not in IDX:
                raise Refuse(f"invalid tagger_label for {r['item_id']}")
            keys[r["item_id"]] = {"set": label, "tagger": r["tagger_label"], "rule": r.get("rule_id_fired", ""), "source": r.get("source", ""), "tool": names.get(r["item_id"], "")}
    controls = {r["item_id"]: r["expected_label"].strip().lower() for r in read_csv(Path(controls_key))}
    if any(v not in IDX for v in controls.values()) or not controls:
        raise Refuse("controls_key.csv is empty or has an invalid expected_label")
    return keys, controls


def load_rater(path: Path, name: str, item_ids: set[str], control_ids: set[str]) -> dict[str, dict]:
    rows = read_csv(path)
    if not rows or "item_id" not in rows[0] or "human_label" not in rows[0]:
        raise Refuse(f"{name}: {path} does not have the columns item_id,human_label,confidence,note")
    ids = [r["item_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise Refuse(f"{name}: duplicate item ids in {path}")
    expected = item_ids | control_ids
    missing, extra = sorted(expected - set(ids)), sorted(set(ids) - expected)
    if missing or extra:
        raise Refuse(f"{name}: item ids do not match (missing {missing[:6]}{'...' if len(missing) > 6 else ''}; unknown {extra[:6]})")
    blank = [r["item_id"] for r in rows if not (r["human_label"] or "").strip()]
    if blank:
        raise Refuse(f"{name}: refusing to score: {len(blank)} blank human_label (for example {blank[:5]})")
    bad = [(r["item_id"], r["human_label"]) for r in rows if r["human_label"].strip().lower() not in IDX]
    if bad:
        raise Refuse(f"{name}: refusing to score: invalid human_label {bad[:5]}; use exactly one of {', '.join(LABELS)}")
    return {r["item_id"]: {"label": r["human_label"].strip().lower(), "conf": (r.get("confidence") or "").strip(), "note": (r.get("note") or "").strip()} for r in rows}


def confusion(pairs: list[tuple[str, str]]) -> list[list[int]]:
    m = [[0] * 3 for _ in range(3)]
    for a, b in pairs:
        m[IDX[a]][IDX[b]] += 1
    return m


def kappas(a: list[int], b: list[int]) -> tuple[float | None, float | None]:
    n = len(a)
    p = [[0.0] * 3 for _ in range(3)]
    for x, y in zip(a, b):
        p[x][y] += 1 / n
    pr = [sum(p[i]) for i in range(3)]
    pc = [sum(p[i][j] for i in range(3)) for j in range(3)]
    po, pe = sum(p[i][i] for i in range(3)), sum(pr[i] * pc[i] for i in range(3))
    k = None if pe >= 1 else (po - pe) / (1 - pe)
    w = lambda i, j: 1 - abs(i - j) / 2
    pow_ = sum(w(i, j) * p[i][j] for i in range(3) for j in range(3))
    pew = sum(w(i, j) * pr[i] * pc[j] for i in range(3) for j in range(3))
    return k, (None if pew >= 1 else (pow_ - pew) / (1 - pew))


def bootstrap(a: list[int], b: list[int]) -> dict:
    rng = random.Random(SEED)
    ks, kws, skipped = [], [], 0
    for _ in range(RESAMPLES):
        idx = [rng.randrange(len(a)) for _ in a]
        k, kw = kappas([a[i] for i in idx], [b[i] for i in idx])
        if k is None or kw is None:
            skipped += 1
            continue
        ks.append(k)
        kws.append(kw)
    def ci(v: list[float]):
        if not v:
            return None
        v = sorted(v)
        return v[int(0.025 * (len(v) - 1))], v[int(round(0.975 * (len(v) - 1)))]
    return {"kappa": ci(ks), "weighted": ci(kws), "skipped": skipped}


f3 = lambda x: "undefined" if x is None else f"{x:.3f}"
fci = lambda c: "undefined" if c is None else f"{c[0]:.3f} to {c[1]:.3f}"


def matrix_md(title: str, rows_lab: str, pairs: list[tuple[str, str]]) -> list[str]:
    m = confusion(pairs)
    out = [f"**{title}** (rows: {rows_lab}; columns: tagger)", "", "| | read_only | state_changing | irreversible | total |", "|---|---|---|---|---|"]
    for i, l in enumerate(LABELS):
        out.append(f"| {l} | {m[i][0]} | {m[i][1]} | {m[i][2]} | {sum(m[i])} |")
    return out + [""]


def gate(labels: dict[str, str], keys: dict[str, dict], max_under: int) -> dict:
    under = [i for i in sorted(keys) if IDX[keys[i]["tagger"]] < IDX[labels[i]]]
    irr = [i for i in under if labels[i] == "irreversible"]
    over = [i for i in sorted(keys) if IDX[keys[i]["tagger"]] > IDX[labels[i]]]
    ok1, ok2 = len(irr) == 0, len(under) <= max_under
    return {"under": under, "irr_under": irr, "over": over, "ok1": ok1, "ok2": ok2, "pass": ok1 and ok2, "agree": sum(1 for i in keys if keys[i]["tagger"] == labels[i])}


def analyse(keys, controls, r1, r2, max_under: int) -> tuple[str, dict]:
    ids = sorted(keys)
    n = len(ids)
    lab = {"R1": {i: r1[i]["label"] for i in ids}, "R2": {i: r2[i]["label"] for i in ids}}
    lab["REF"] = {i: max(lab["R1"][i], lab["R2"][i], key=lambda x: IDX[x]) for i in ids}
    g = {k: gate(v, keys, max_under) for k, v in lab.items()}
    ctl = {}
    for name, r in (("R1", r1), ("R2", r2)):
        miss = [(c, controls[c], r[c]["label"]) for c in sorted(controls) if r[c]["label"] != controls[c]]
        ctl[name] = {"score": len(controls) - len(miss), "total": len(controls), "missed": miss, "flag": len(miss) > 0}
    a, b = [IDX[lab["R1"][i]] for i in ids], [IDX[lab["R2"][i]] for i in ids]
    k, kw = kappas(a, b)
    ci = bootstrap(a, b)
    ref_i, tag_i = [IDX[lab["REF"][i]] for i in ids], [IDX[keys[i]["tagger"]] for i in ids]
    kr, kwr = kappas(ref_i, tag_i)
    ci_ref = bootstrap(ref_i, tag_i)
    L = ["# Two-rater hand-check results", "", f"Items scored: {n} (set A and set B), plus {len(controls)} controls per rater. Criteria: `gate_addendum_two_raters.md` (2026-10-04).", "",
         "## Control items", "", "| rater | controls correct | flag | missed (control, expected, given) |", "|---|---|---|---|"]
    for name in ("R1", "R2"):
        c = ctl[name]
        flag_text = "**FLAGGED: review this rater's labels before use**" if c["flag"] else "ok"
        missed_text = "; ".join(f"{x[0]}: {x[1]} / {x[2]}" for x in c["missed"]) or "none"
        L.append(f"| {name} | {c['score']} of {c['total']} | {flag_text} | {missed_text} |")
    L += ["", "A flagged rater's labels are reviewed before use; they are not dropped from this analysis.", "", "## Agreement between the raters (100 items, controls excluded)", "",
          f"- Exact agreement: {sum(1 for x, y in zip(a, b) if x == y)} of {n} ({sum(1 for x, y in zip(a, b) if x == y) / n:.1%}).", f"- Cohen's kappa: {f3(k)} (bootstrap 95% CI {fci(ci['kappa'])}).",
          f"- Linearly weighted kappa: {f3(kw)} (bootstrap 95% CI {fci(ci['weighted'])}).", f"- Bootstrap: {RESAMPLES:,} resamples, seed {SEED}; {ci['skipped']} skipped (undefined kappa).", ""]
    m = confusion([(lab["R1"][i], lab["R2"][i]) for i in ids])
    L += ["**R1 by R2**", "", "| R1 \\ R2 | read_only | state_changing | irreversible |", "|---|---|---|---|"] + [f"| {l} | {m[i][0]} | {m[i][1]} | {m[i][2]} |" for i, l in enumerate(LABELS)] + [""]
    dis = [i for i in ids if lab["R1"][i] != lab["R2"][i]]
    L += [f"### Disagreements, for the record ({len(dis)})", ""]
    if dis:
        L += ["| item | set | tool | R1 | R2 | reference (more severe) |", "|---|---|---|---|---|---|"]
        L += [f"| {i} | {keys[i]['set']} | {keys[i]['tool']} | {lab['R1'][i]} | {lab['R2'][i]} | {lab['REF'][i]} |" for i in dis]
    else:
        L.append("None.")
    L += ["", "## Confusion matrices against the tagger", ""]
    for name, desc in (("R1", "R1"), ("R2", "R2"), ("REF", "reference label")):
        L += matrix_md(("Reference (the more severe of R1 and R2)" if name == "REF" else f"Rater {name}"), desc, [(lab[name][i], keys[i]["tagger"]) for i in ids])
    G = g["REF"]
    def table(idsl: list[str], title: str) -> list[str]:
        out = [f"### {title} ({len(idsl)})", ""]
        if not idsl:
            return out + ["None.", ""]
        out += ["| item | set | tool | reference | tagger | rule fired | source | R1 | R2 | notes |", "|---|---|---|---|---|---|---|---|---|---|"]
        for i in idsl:
            notes = " / ".join(x for x in (r1[i]["note"], r2[i]["note"]) if x).replace("|", "/")
            out.append(f"| {i} | {keys[i]['set']} | {keys[i]['tool']} | {lab['REF'][i]} | {keys[i]['tagger']} | {keys[i]['rule']} | {keys[i]['source']} | {lab['R1'][i]} | {lab['R2'][i]} | {notes} |")
        return out + [""]
    L += ["## Under-tagging against the reference label (the safety-critical direction)", "", f"- Under-tagged items: {len(G['under'])}; reference-irreversible tagged below irreversible: {len(G['irr_under'])}; "
          f"reference-irreversible tagged read_only: {sum(1 for i in G['under'] if lab['REF'][i] == 'irreversible' and keys[i]['tagger'] == 'read_only')}.", ""]
    L += table(G["under"], "Under-tagged items") + ["## Over-tagging against the reference label", ""] + table(G["over"], "Over-tagged items")
    L += ["## Gate verdict (criteria of gate_addendum_two_raters.md)", "", f"- Criterion 1, reference-irreversible items tagged below irreversible: {len(G['irr_under'])}; allowed 0: **{'met' if G['ok1'] else 'NOT met'}**.",
          f"- Criterion 2, total under-tags: {len(G['under'])} of {n}; allowed at most {max_under}: **{'met' if G['ok2'] else 'NOT met'}**.", f"- **Overall on the reference labels: {'PASS' if G['pass'] else 'FAIL'}.**",
          f"- Reported, not gating: over-tags {len(G['over'])}; exact agreement tagger and reference {G['agree']} of {n}; linearly weighted kappa tagger versus reference {f3(kwr)} (bootstrap 95% CI {fci(ci_ref['weighted'])}).", "",
          "Each rater's gate on their own labels:", "", "| rater | irreversible under-tags (allowed 0) | total under-tags (allowed at most %d) | over-tags | result |" % max_under, "|---|---|---|---|---|"]
    for name in ("R1", "R2"):
        x = g[name]
        L.append(f"| {name} | {len(x['irr_under'])} | {len(x['under'])} | {len(x['over'])} | {'PASS' if x['pass'] else 'FAIL'} |")
    L += ["", "On FAIL: revise the rules and re-check on a fresh set; no rule change is made on these 100 items alone.", "", "## By set and by source (reference labels)", "",
          "| group | items | agreement | under-tagged | over-tagged |", "|---|---|---|---|---|"]
    def grp(name: str, sel: list[str]) -> str:
        return f"| {name} | {len(sel)} | {sum(1 for i in sel if keys[i]['tagger'] == lab['REF'][i])} of {len(sel)} | {sum(1 for i in sel if i in G['under'])} | {sum(1 for i in sel if i in G['over'])} |"
    for s in ("A", "B"):
        L.append(grp(f"set {s}", [i for i in ids if keys[i]["set"] == s]))
    for s in sorted({keys[i]["source"] for i in ids}):
        L.append(grp(f"source {s}", [i for i in ids if keys[i]["source"] == s]))
    return "\n".join(L) + "\n", {"gate": g, "controls": ctl}


def write_new(out_dir: Path, text: str) -> Path:
    for n in range(1, 10_000):
        path = out_dir / ("two_rater_results.md" if n == 1 else f"two_rater_results_{n}.md")
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(text)
            return path
        except FileExistsError:
            continue
    raise Refuse("no free two_rater_results file name")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score the two-rater hand check")
    ap.add_argument("--r1", type=Path, default=HERE / "rater_R1_labels.csv")
    ap.add_argument("--r2", type=Path, default=HERE / "rater_R2_labels.csv")
    ap.add_argument("--key-a", type=Path, default=HERE.parent / "1b_handcheck" / "handcheck_key.csv")
    ap.add_argument("--key-b", type=Path, default=HERE.parent / "1b_handcheck_b" / "handcheck_b_key.csv")
    ap.add_argument("--controls-key", type=Path, default=HERE / "controls_key.csv")
    ap.add_argument("--items-a", type=Path, default=HERE.parent / "1b_handcheck" / "handcheck_items.csv")
    ap.add_argument("--items-b", type=Path, default=HERE.parent / "1b_handcheck_b" / "handcheck_b_items.csv")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    ap.add_argument("--max-under-tags", type=int, default=6)
    a = ap.parse_args(argv)
    try:
        keys, controls = load_keys(a.key_a, a.key_b, a.controls_key, a.items_a, a.items_b)
        r1 = load_rater(a.r1, "R1", set(keys), set(controls))
        r2 = load_rater(a.r2, "R2", set(keys), set(controls))
    except Refuse as exc:
        print(exc.code if isinstance(exc.code, str) else str(exc), file=sys.stderr)
        return 2
    text, res = analyse(keys, controls, r1, r2, a.max_under_tags)
    path = write_new(a.out_dir, text)
    print(f"written to {path}")
    print("gate on the reference labels: " + ("PASS" if res["gate"]["REF"]["pass"] else "FAIL") + "; R1: " + ("PASS" if res["gate"]["R1"]["pass"] else "FAIL") + "; R2: " + ("PASS" if res["gate"]["R2"]["pass"] else "FAIL"))
    for name in ("R1", "R2"):
        c = res["controls"][name]
        print(f"controls {name}: {c['score']} of {c['total']}" + ("  FLAGGED: review before use" if c["flag"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
