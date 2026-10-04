"""Score the set C two-rater hand check (gate_set_c.md, pre-registered 2026-10-04). Adapted from 1b_rater_packet/score_two_raters.py (the original is untouched).

Usage:
  python score_two_raters_c.py --r1 rater_R1_labels_c.csv --r2 rater_R2_labels_c.csv [--key handcheck_c_key_v2b.csv] [--controls-key controls_c_key.csv]
                               [--items handcheck_c_items.csv] [--compare-key handcheck_c_key_v1.csv] [--out-dir DIR] [--max-under-tags 6]

Gate (gate_set_c.md): reference label = the more severe of R1 and R2 (read_only < state_changing < irreversible). PASS needs BOTH (1) zero reference-irreversible items tagged
below irreversible and (2) at most 6 under-tags (any class) of the 100 items. Reported, not gating: under-tags on items where R1 and R2 agree, over-tags, exact agreement,
linearly weighted kappa tagger versus reference with a bootstrap 95% CI (10,000 resamples, seed 20261005), inter-rater kappa, controls per rater (a rater below 4 of 4 is
flagged, not dropped), and with --compare-key the same table for the v1 key, side by side, labelled "comparison, not gating".
Refuses (writes nothing) on a missing file, a missing or unknown or duplicate item id, a blank or invalid label. Never overwrites: two_rater_results_c.md, then _2, _3, ...
The terminal shows the file name, the verdicts and the control flags only; key rows appear only in the results file."""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SET_C = HERE.parent / "1b_handcheck_c"
LABELS = ("read_only", "state_changing", "irreversible")
IDX = {l: i for i, l in enumerate(LABELS)}
SEED = 20261005
RESAMPLES = 10_000
N_ITEMS = 100


class Refuse(SystemExit):
    """An input the scorer refuses."""


def read_csv(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        raise Refuse(f"missing file: {path}") from None


def load_key(path: Path, items: dict[str, str], what: str = "key") -> dict[str, dict]:
    rows = read_csv(Path(path))
    keys: dict[str, dict] = {}
    for r in rows:
        iid = r.get("item_id", "")
        if iid in keys:
            raise Refuse(f"{what}: duplicate item id {iid}")
        if r.get("tagger_label") not in IDX:
            raise Refuse(f"{what}: invalid tagger_label for {iid}")
        keys[iid] = {"tagger": r["tagger_label"], "rule": r.get("rule_ids", ""), "basis": r.get("basis", ""), "source": r.get("source", ""),
                     "group": r.get("variant_group", ""), "tool": items.get(iid, "")}
    if len(keys) != N_ITEMS:
        raise Refuse(f"{what}: expected {N_ITEMS} items, found {len(keys)}")
    return keys


def load_controls(path: Path) -> dict[str, str]:
    controls = {r["item_id"]: r["expected_label"].strip().lower() for r in read_csv(Path(path))}
    if not controls or any(v not in IDX for v in controls.values()):
        raise Refuse("controls key is empty or has an invalid expected_label")
    return controls


def load_rater(path: Path, name: str, item_ids: set[str], control_ids: set[str]) -> dict[str, dict]:
    rows = read_csv(Path(path))
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
    return {r["item_id"]: {"label": r["human_label"].strip().lower(), "conf": (r.get("confidence") or "").strip(), "note": (r.get("note") or "").strip().replace("|", "/")} for r in rows}


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


def gate(labels: dict[str, str], keys: dict[str, dict], max_under: int, agree_with: dict[str, str] | None = None) -> dict:
    """Under-tags are items whose tagger label is below the given labels; consensus under-tags are those where R1 and R2 gave the same label."""
    under = [i for i in sorted(keys) if IDX[keys[i]["tagger"]] < IDX[labels[i]]]
    irr = [i for i in under if labels[i] == "irreversible"]
    over = [i for i in sorted(keys) if IDX[keys[i]["tagger"]] > IDX[labels[i]]]
    ok1, ok2 = len(irr) == 0, len(under) <= max_under
    return {"under": under, "irr_under": irr, "over": over, "ok1": ok1, "ok2": ok2, "pass": ok1 and ok2, "agree": sum(1 for i in keys if keys[i]["tagger"] == labels[i])}


def summary(keys: dict[str, dict], lab: dict[str, dict[str, str]], max_under: int) -> dict:
    ids = sorted(keys)
    G = gate(lab["REF"], keys, max_under)
    cons = [i for i in G["under"] if lab["R1"][i] == lab["R2"][i]]
    k, kw = kappas([IDX[lab["REF"][i]] for i in ids], [IDX[keys[i]["tagger"]] for i in ids])
    ci = bootstrap([IDX[lab["REF"][i]] for i in ids], [IDX[keys[i]["tagger"]] for i in ids])
    return {"G": G, "consensus_under": cons, "kappa": k, "wkappa": kw, "ci": ci,
            "per_rater": {r: gate(lab[r], keys, max_under) for r in ("R1", "R2")}}


def matrix_md(title: str, pairs: list[tuple[str, str]]) -> list[str]:
    m = confusion(pairs)
    out = [f"**{title}** (rows: reference label; columns: tagger)", "", "| | read_only | state_changing | irreversible | total |", "|---|---|---|---|---|"]
    out += [f"| {l} | {m[i][0]} | {m[i][1]} | {m[i][2]} | {sum(m[i])} |" for i, l in enumerate(LABELS)]
    return out + [""]


def analyse(keys, controls, r1, r2, max_under: int, cmp_keys: dict[str, dict] | None = None) -> tuple[str, dict]:
    ids = sorted(keys)
    n = len(ids)
    lab = {"R1": {i: r1[i]["label"] for i in ids}, "R2": {i: r2[i]["label"] for i in ids}}
    lab["REF"] = {i: max(lab["R1"][i], lab["R2"][i], key=lambda x: IDX[x]) for i in ids}
    S = summary(keys, lab, max_under)
    G = S["G"]
    ctl = {}
    for name, r in (("R1", r1), ("R2", r2)):
        miss = [(c, controls[c], r[c]["label"]) for c in sorted(controls) if r[c]["label"] != controls[c]]
        ctl[name] = {"score": len(controls) - len(miss), "total": len(controls), "missed": miss, "flag": len(miss) > 0}
    a, b = [IDX[lab["R1"][i]] for i in ids], [IDX[lab["R2"][i]] for i in ids]
    k, kw = kappas(a, b)
    ci = bootstrap(a, b)
    agree_n = sum(1 for x, y in zip(a, b) if x == y)
    L = ["# Set C two-rater hand-check results", "", f"Items scored: {n} (HD001 to HD100), plus {len(controls)} controls per rater. Criteria: `gate_set_c.md` (pre-registered 2026-10-04). "
         "Tagger under test: rules v2b (the key `handcheck_c_key_v2b.csv`).", "",
         "## Gate verdict (gate_set_c.md)", "",
         f"- Criterion 1, reference-irreversible items tagged below irreversible: {len(G['irr_under'])}; allowed 0: **{'met' if G['ok1'] else 'NOT met'}**.",
         f"- Criterion 2, total under-tags: {len(G['under'])} of {n}; allowed at most {max_under}: **{'met' if G['ok2'] else 'NOT met'}**.",
         f"- **Overall on the reference labels (the more severe of R1 and R2): {'PASS' if G['pass'] else 'FAIL'}.**", "",
         "Reported, not gating:", "",
         f"- Under-tags on items where R1 and R2 agree: {len(S['consensus_under'])} (of the {len(G['under'])} under-tags).",
         f"- Over-tags: {len(G['over'])}.", f"- Exact agreement, tagger and reference: {G['agree']} of {n}.",
         f"- Linearly weighted kappa, tagger versus reference: {f3(S['wkappa'])} (bootstrap 95% CI {fci(S['ci']['weighted'])}; {RESAMPLES:,} resamples, seed {SEED}, {S['ci']['skipped']} skipped).", "",
         "Each rater's gate on their own labels (reported, not the gate):", "", f"| rater | irreversible under-tags (allowed 0) | total under-tags (allowed at most {max_under}) | over-tags | result |", "|---|---|---|---|---|"]
    for name in ("R1", "R2"):
        x = S["per_rater"][name]
        L.append(f"| {name} | {len(x['irr_under'])} | {len(x['under'])} | {len(x['over'])} | {'PASS' if x['pass'] else 'FAIL'} |")
    L += ["", "On FAIL: no rule change is made on these results; a further revision needs a fresh set D (gate_set_c.md).", "", "## Control items", "",
          "| rater | controls correct | flag | missed (control, expected, given) |", "|---|---|---|---|"]
    for name in ("R1", "R2"):
        c = ctl[name]
        L.append(f"| {name} | {c['score']} of {c['total']} | {'**FLAGGED: review this rater\'s labels before use**' if c['flag'] else 'ok'} | {'; '.join(f'{x[0]}: {x[1]} / {x[2]}' for x in c['missed']) or 'none'} |")
    L += ["", "A flagged rater's labels are reviewed before use; they are not dropped from this analysis.", "", f"## Agreement between the raters ({n} items, controls excluded)", "",
          f"- Exact agreement: {agree_n} of {n} ({agree_n / n:.1%}).", f"- Cohen's kappa: {f3(k)} (bootstrap 95% CI {fci(ci['kappa'])}).",
          f"- Linearly weighted kappa: {f3(kw)} (bootstrap 95% CI {fci(ci['weighted'])}).", f"- Bootstrap: {RESAMPLES:,} resamples, seed {SEED}; {ci['skipped']} skipped (undefined kappa).", ""]
    m = confusion([(lab["R1"][i], lab["R2"][i]) for i in ids])
    L += ["**R1 by R2**", "", "| R1 \\ R2 | read_only | state_changing | irreversible |", "|---|---|---|---|"] + [f"| {l} | {m[i][0]} | {m[i][1]} | {m[i][2]} |" for i, l in enumerate(LABELS)] + [""]
    dis = [i for i in ids if lab["R1"][i] != lab["R2"][i]]
    L += [f"### Disagreements, for the record ({len(dis)})", ""]
    if dis:
        L += ["| item | tool | R1 | R2 | reference (more severe) |", "|---|---|---|---|---|"] + [f"| {i} | {keys[i]['tool']} | {lab['R1'][i]} | {lab['R2'][i]} | {lab['REF'][i]} |" for i in dis]
    else:
        L.append("None.")
    L += ["", "## Confusion matrices, v2b tagger", ""]
    for name, t in (("R1", "Rater R1"), ("R2", "Rater R2"), ("REF", "Reference (the more severe of R1 and R2)")):
        L += matrix_md(t, [(lab[name][i], keys[i]["tagger"]) for i in ids])

    def table(idsl: list[str], title: str) -> list[str]:
        out = [f"### {title} ({len(idsl)})", ""]
        if not idsl:
            return out + ["None.", ""]
        out += ["| item | tool | variant group | source | reference | tagger | rule(s) | basis | R1 | R2 | notes |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for i in idsl:
            notes = " / ".join(x for x in (r1[i]["note"], r2[i]["note"]) if x)
            out.append(f"| {i} | {keys[i]['tool']} | {keys[i]['group']} | {keys[i]['source']} | {lab['REF'][i]} | {keys[i]['tagger']} | {keys[i]['rule']} | {keys[i]['basis']} | {lab['R1'][i]} | {lab['R2'][i]} | {notes} |")
        return out + [""]
    L += ["## Under-tagging against the reference label (the safety-critical direction)", "",
          f"- Under-tagged items: {len(G['under'])}; reference-irreversible tagged below irreversible: {len(G['irr_under'])}; "
          f"reference-irreversible tagged read_only: {sum(1 for i in G['under'] if lab['REF'][i] == 'irreversible' and keys[i]['tagger'] == 'read_only')}.", ""]
    L += table(G["under"], "Under-tagged items") + ["## Over-tagging against the reference label", ""] + table(G["over"], "Over-tagged items")

    def grp(name: str, sel: list[str]) -> str:
        return f"| {name} | {len(sel)} | {sum(1 for i in sel if keys[i]['tagger'] == lab['REF'][i])} of {len(sel)} | {sum(1 for i in sel if i in G['under'])} | {sum(1 for i in sel if i in G['over'])} |"
    L += ["## By source and by variant group (reference labels, v2b)", "", "| group | items | agreement | under-tagged | over-tagged |", "|---|---|---|---|---|"]
    for s in sorted({keys[i]["source"] for i in ids}):
        L.append(grp(f"source {s}", [i for i in ids if keys[i]["source"] == s]))
    L.append(grp("in a variant group", [i for i in ids if keys[i]["group"]]))
    L.append(grp("not in a variant group", [i for i in ids if not keys[i]["group"]]))
    res = {"gate": G, "controls": ctl, "summary": S}
    if cmp_keys is not None:
        C = summary(cmp_keys, lab, max_under)
        res["compare"] = C
        L += ["", "## Comparison, not gating: tagger v1 on the same reference labels", "",
              "The v1 key is for comparison only; the gate above is decided on v2b alone.", "",
              "| measure | v2b (the test) | v1 (comparison, not gating) |", "|---|---|---|",
              f"| under-tags (of {n}) | {len(G['under'])} | {len(C['G']['under'])} |",
              f"| reference-irreversible tagged below irreversible | {len(G['irr_under'])} | {len(C['G']['irr_under'])} |",
              f"| under-tags where R1 and R2 agree | {len(S['consensus_under'])} | {len(C['consensus_under'])} |",
              f"| over-tags | {len(G['over'])} | {len(C['G']['over'])} |", f"| exact agreement with the reference | {G['agree']} of {n} | {C['G']['agree']} of {n} |",
              f"| weighted kappa vs reference (bootstrap 95% CI) | {f3(S['wkappa'])} ({fci(S['ci']['weighted'])}) | {f3(C['wkappa'])} ({fci(C['ci']['weighted'])}) |",
              f"| would pass the gate | {'yes' if G['pass'] else 'no'} | {'yes' if C['G']['pass'] else 'no'} (informational) |", ""]
        L += matrix_md("Reference label against v1 (comparison, not gating)", [(lab["REF"][i], cmp_keys[i]["tagger"]) for i in ids])
    return "\n".join(L) + "\n", res


def write_new(out_dir: Path, text: str) -> Path:
    for n in range(1, 10_000):
        path = Path(out_dir) / ("two_rater_results_c.md" if n == 1 else f"two_rater_results_c_{n}.md")
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(text)
            return path
        except FileExistsError:
            continue
    raise Refuse("no free two_rater_results_c file name")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score the set C two-rater hand check")
    ap.add_argument("--r1", type=Path, required=True)
    ap.add_argument("--r2", type=Path, required=True)
    ap.add_argument("--key", type=Path, default=HERE / "handcheck_c_key_v2b.csv")
    ap.add_argument("--controls-key", type=Path, default=SET_C / "controls_c_key.csv")
    ap.add_argument("--items", type=Path, default=SET_C / "handcheck_c_items.csv")
    ap.add_argument("--compare-key", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=HERE)
    ap.add_argument("--max-under-tags", type=int, default=6)
    a = ap.parse_args(argv)
    try:
        items = {r["item_id"]: r.get("tool_name", "") for r in read_csv(a.items)} if Path(a.items).exists() else {}
        keys = load_key(a.key, items)
        cmp_keys = load_key(a.compare_key, items, "compare key") if a.compare_key else None
        if cmp_keys is not None and set(cmp_keys) != set(keys):
            raise Refuse("compare key and key do not list the same items")
        controls = load_controls(a.controls_key)
        r1 = load_rater(a.r1, "R1", set(keys), set(controls))
        r2 = load_rater(a.r2, "R2", set(keys), set(controls))
    except Refuse as exc:
        print(exc.code if isinstance(exc.code, str) else str(exc), file=sys.stderr)
        return 2
    text, res = analyse(keys, controls, r1, r2, a.max_under_tags, cmp_keys)
    path = write_new(a.out_dir, text)
    print(f"written to {path}")
    g = res["summary"]
    print("gate on the reference labels (v2b): " + ("PASS" if res["gate"]["pass"] else "FAIL") + "; R1: " + ("PASS" if g["per_rater"]["R1"]["pass"] else "FAIL") + "; R2: " + ("PASS" if g["per_rater"]["R2"]["pass"] else "FAIL"))
    for name in ("R1", "R2"):
        c = res["controls"][name]
        print(f"controls {name}: {c['score']} of {c['total']}" + ("  FLAGGED: review before use" if c["flag"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
