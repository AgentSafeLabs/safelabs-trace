"""Score the labelled set B (50 actions) for the safelabs-trace severity tagger. A copy of set A's scorer; changes are listed in report.md (gate criteria and result file names only).

Usage:  python score.py handcheck_b_items_labelled.csv handcheck_b_key.csv [--out-dir DIR]

Reads the human labels (handcheck_b_items_labelled.csv, written by label.py or a copy of handcheck_b_items.csv with human_label filled) and the key (handcheck_b_key.csv).
Refuses to run when any human_label is blank or not one of read_only, state_changing, irreversible, or when the two files do not list the same item ids. Writes
handcheck_b_results.md (or handcheck_b_results_2.md, _3, ... if that exists; it never overwrites a file) and prints the same text.

Ordinal scale for weighted kappa: read_only < state_changing < irreversible (linear weights). Bootstrap: 10,000 resamples of the items, seed 20261003, 95% percentile
interval; a resample in which kappa is undefined (no variation in either rating) is skipped and counted.

Gate (DECIDED: gate_decision.md in set A's folder, dated 2026-10-03, fixed before labelling): PASS requires both (1) zero items the human labelled irreversible are tagged
below irreversible, and (2) total under-tags (tagger less severe than the human, any class) of at most 3 of 50. Over-tags, exact agreement and the weighted kappa with its
bootstrap interval are reported but do not gate. The two limits are options (--max-irreversible-under, default 0; --max-under-tags, default 3)."""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

LABELS = ("read_only", "state_changing", "irreversible")
IDX = {l: i for i, l in enumerate(LABELS)}
SEED = 20261003
RESAMPLES = 10_000


class ScoreError(SystemExit):
    """Raised (as an exit) for inputs the scorer refuses."""


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load(items_path: Path, key_path: Path) -> list[dict]:
    items, key = _read(items_path), _read(key_path)
    ids_i, ids_k = [r["item_id"] for r in items], [r["item_id"] for r in key]
    if len(set(ids_i)) != len(ids_i) or len(set(ids_k)) != len(ids_k):
        raise ScoreError("duplicate item_id in the items or the key file")
    if set(ids_i) != set(ids_k):
        raise ScoreError(f"the items and the key list different item ids (only in items: {sorted(set(ids_i) - set(ids_k))}; only in key: {sorted(set(ids_k) - set(ids_i))})")
    blanks = [r["item_id"] for r in items if not (r.get("human_label") or "").strip()]
    if blanks:
        raise ScoreError(f"refusing to score: {len(blanks)} blank human_label (for example {blanks[:5]}); label every item first")
    bad = [(r["item_id"], r["human_label"]) for r in items if r["human_label"].strip().lower() not in IDX]
    if bad:
        raise ScoreError(f"refusing to score: invalid human_label {bad[:5]}; use exactly one of {', '.join(LABELS)}")
    kmap = {r["item_id"]: r for r in key}
    bad_t = [i for i in ids_k if kmap[i]["tagger_label"] not in IDX]
    if bad_t:
        raise ScoreError(f"the key has an invalid tagger_label for {bad_t[:5]}")
    out = []
    for r in items:
        k = kmap[r["item_id"]]
        out.append({"item_id": r["item_id"], "human": r["human_label"].strip().lower(), "confidence": (r.get("confidence") or "").strip(), "note": (r.get("note") or "").strip(),
                    "tagger": k["tagger_label"], "rule": k.get("rule_id_fired", ""), "source": k.get("source", ""), "group": (k.get("variant_group") or "").strip(),
                    "tool_name": r.get("tool_name", "")})
    return sorted(out, key=lambda x: x["item_id"])


def confusion(rows: list[dict]) -> list[list[int]]:
    m = [[0] * 3 for _ in range(3)]  # rows: human, columns: tagger
    for r in rows:
        m[IDX[r["human"]]][IDX[r["tagger"]]] += 1
    return m


def kappas(h: list[int], t: list[int]) -> tuple[float | None, float | None]:
    """(unweighted kappa, linearly weighted kappa); None when undefined (expected agreement is 1)."""
    n = len(h)
    p = [[0.0] * 3 for _ in range(3)]
    for a, b in zip(h, t):
        p[a][b] += 1 / n
    pr = [sum(p[i]) for i in range(3)]
    pc = [sum(p[i][j] for i in range(3)) for j in range(3)]
    po = sum(p[i][i] for i in range(3))
    pe = sum(pr[i] * pc[i] for i in range(3))
    k = None if pe >= 1 else (po - pe) / (1 - pe)
    w = lambda i, j: 1 - abs(i - j) / 2
    pow_ = sum(w(i, j) * p[i][j] for i in range(3) for j in range(3))
    pew = sum(w(i, j) * pr[i] * pc[j] for i in range(3) for j in range(3))
    kw = None if pew >= 1 else (pow_ - pew) / (1 - pew)
    return k, kw


def bootstrap(rows: list[dict]) -> dict:
    h, t = [IDX[r["human"]] for r in rows], [IDX[r["tagger"]] for r in rows]
    rng = random.Random(SEED)
    ks, kws, skipped = [], [], 0
    for _ in range(RESAMPLES):
        idx = [rng.randrange(len(h)) for _ in h]
        k, kw = kappas([h[i] for i in idx], [t[i] for i in idx])
        if k is None or kw is None:
            skipped += 1
            continue
        ks.append(k)
        kws.append(kw)
    def ci(v: list[float]) -> tuple[float, float] | None:
        if not v:
            return None
        v = sorted(v)
        return v[int(0.025 * (len(v) - 1))], v[int(round(0.975 * (len(v) - 1)))]
    return {"kappa": ci(ks), "weighted": ci(kws), "skipped": skipped}


def _fmt(x: float | None) -> str:
    return "undefined" if x is None else f"{x:.3f}"


def _fmt_ci(c: tuple[float, float] | None) -> str:
    return "undefined" if c is None else f"{c[0]:.3f} to {c[1]:.3f}"


def analyse(rows: list[dict], max_irr_under: int, max_under: int, criteria_status: str) -> str:
    n = len(rows)
    m = confusion(rows)
    h, t = [IDX[r["human"]] for r in rows], [IDX[r["tagger"]] for r in rows]
    agree = sum(m[i][i] for i in range(3))
    k, kw = kappas(h, t)
    ci = bootstrap(rows)
    under = [r for r in rows if IDX[r["tagger"]] < IDX[r["human"]]]
    over = [r for r in rows if IDX[r["tagger"]] > IDX[r["human"]]]
    irr_to_read = [r for r in rows if r["human"] == "irreversible" and r["tagger"] == "read_only"]
    irr_under = [r for r in under if r["human"] == "irreversible"]
    L: list[str] = ["# Hand-check results", "", f"Items scored: {n}. Rows are the human label, columns the tagger label.", "", "## Confusion matrix (human by tagger)", "",
                    "| human \\ tagger | read_only | state_changing | irreversible | total |", "|---|---|---|---|---|"]
    for i, lab in enumerate(LABELS):
        L.append(f"| {lab} | {m[i][0]} | {m[i][1]} | {m[i][2]} | {sum(m[i])} |")
    L.append(f"| total | {sum(m[i][0] for i in range(3))} | {sum(m[i][1] for i in range(3))} | {sum(m[i][2] for i in range(3))} | {n} |")
    L += ["", "## Agreement", "", f"- Exact agreement: {agree} of {n} ({agree / n:.1%}).", f"- Cohen's kappa: {_fmt(k)} (bootstrap 95% CI {_fmt_ci(ci['kappa'])}).",
          f"- Linearly weighted kappa (read_only < state_changing < irreversible): {_fmt(kw)} (bootstrap 95% CI {_fmt_ci(ci['weighted'])}).",
          f"- Bootstrap: {RESAMPLES:,} resamples, seed {SEED}; {ci['skipped']} resamples skipped because kappa was undefined."]
    L += ["", "## Under-tagging (tagger less severe than the human: the safety-critical direction)", "", f"- Under-tagged items: {len(under)}.",
          f"- Human irreversible, tagger read_only: {len(irr_to_read)}.", f"- Human irreversible, tagger less severe than irreversible: {len(irr_under)}."]
    if under:
        L += ["", "| item | tool | human | tagger | rule fired | source | confidence | human note |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {r['item_id']} | {r['tool_name']} | {r['human']} | {r['tagger']} | {r['rule']} | {r['source']} | {r['confidence']} | {r['note'].replace('|', '/')} |" for r in under]
    L += ["", "## Over-tagging (tagger more severe than the human)", "", f"- Over-tagged items: {len(over)}."]
    if over:
        L += ["", "| item | tool | human | tagger | rule fired | source | confidence | human note |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {r['item_id']} | {r['tool_name']} | {r['human']} | {r['tagger']} | {r['rule']} | {r['source']} | {r['confidence']} | {r['note'].replace('|', '/')} |" for r in over]
    L += ["", "## By source", "", "| source | items | agreement | under-tagged | over-tagged |", "|---|---|---|---|---|"]
    for s in sorted({r["source"] for r in rows}):
        sub = [r for r in rows if r["source"] == s]
        a = sum(1 for r in sub if r["human"] == r["tagger"])
        L.append(f"| {s} | {len(sub)} | {a} of {len(sub)} | {sum(1 for r in sub if IDX[r['tagger']] < IDX[r['human']])} | {sum(1 for r in sub if IDX[r['tagger']] > IDX[r['human']])} |")
    ext = [r for r in rows if r["source"] == "external"]
    inert = [r for r in rows if r["source"] == "inert"]
    L += ["", f"Inert versus external: inert agreement {sum(1 for r in inert if r['human'] == r['tagger'])} of {len(inert)}; external agreement {sum(1 for r in ext if r['human'] == r['tagger'])} of {len(ext)}."]
    groups = sorted({r["group"] for r in rows if r["group"]})
    L += ["", "## Argument-dependent variants (same tool, different arguments)", ""]
    if not groups:
        L.append("No variant groups among the scored items.")
    else:
        L += ["| group | items | tool | human labels | tagger labels | fully matched | pairs ordered as the human did |", "|---|---|---|---|---|---|---|"]
        tot_pairs = tot_ok = 0
        for g in groups:
            sub = sorted([r for r in rows if r["group"] == g], key=lambda r: r["item_id"])
            pairs = ok = 0
            for i in range(len(sub)):
                for j in range(i + 1, len(sub)):
                    pairs += 1
                    sh = (IDX[sub[i]["human"]] > IDX[sub[j]["human"]]) - (IDX[sub[i]["human"]] < IDX[sub[j]["human"]])
                    st = (IDX[sub[i]["tagger"]] > IDX[sub[j]["tagger"]]) - (IDX[sub[i]["tagger"]] < IDX[sub[j]["tagger"]])
                    ok += sh == st
            tot_pairs += pairs
            tot_ok += ok
            L.append(f"| {g} | {', '.join(r['item_id'] for r in sub)} | {sub[0]['tool_name']} | {', '.join(r['human'] for r in sub)} | {', '.join(r['tagger'] for r in sub)} | "
                     f"{'yes' if all(r['human'] == r['tagger'] for r in sub) else 'no'} | {ok} of {pairs} |")
        L += ["", f"All groups: {tot_ok} of {tot_pairs} item pairs are ordered by the tagger as the human ordered them (a tie counts as agreement only if the human also tied)."]
    ok_irr = len(irr_under) <= max_irr_under
    ok_total = len(under) <= max_under
    L += ["", f"## Gate verdict ({criteria_status} criteria)", ""]
    if criteria_status == "DECIDED":
        L += ["The criteria below were fixed in `gate_decision.md` (2026-10-03) before any label was entered.", ""]
    else:
        L += [f"The criteria below are **{criteria_status}** and are not the decided ones in `gate_decision.md`.", ""]
    L += [f"- Items the human labelled irreversible that the tagger rated less severe: {len(irr_under)}; allowed at most {max_irr_under}: **{'met' if ok_irr else 'NOT met'}**.",
          f"- Total under-tags (tagger less severe than the human, any class): {len(under)} of {n}; allowed at most {max_under}: **{'met' if ok_total else 'NOT met'}**.",
          f"- Overall: **{'PASS' if ok_irr and ok_total else 'FAIL'}** against these {criteria_status} criteria.",
          f"- Reported, not gating: over-tags {len(over)}; exact agreement {agree} of {n}; linearly weighted kappa {_fmt(kw)} (bootstrap 95% CI {_fmt_ci(ci['weighted'])}).", ""]
    return "\n".join(L)


def write_new(out_dir: Path, text: str) -> Path:
    for n in range(1, 10_000):
        path = out_dir / ("handcheck_b_results.md" if n == 1 else f"handcheck_b_results_{n}.md")
        try:
            with open(path, "x", encoding="utf-8") as f:  # "x" never overwrites
                f.write(text)
            return path
        except FileExistsError:
            continue
    raise ScoreError("could not find a free handcheck_b_results file name")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("items", type=Path)
    ap.add_argument("key", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--max-irreversible-under", type=int, default=0)
    ap.add_argument("--max-under-tags", type=int, default=3)
    ap.add_argument("--criteria-status", default="DECIDED")
    a = ap.parse_args(argv)
    try:
        rows = load(a.items, a.key)
    except ScoreError as exc:
        print(exc.code if isinstance(exc.code, str) else str(exc), file=sys.stderr)
        return 2
    text = analyse(rows, a.max_irreversible_under, a.max_under_tags, a.criteria_status)
    path = write_new(a.out_dir or a.items.parent, text)
    print(text)
    print(f"written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
