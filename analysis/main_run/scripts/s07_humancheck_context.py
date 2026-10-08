"""F. Context from the committed human checks (quoted, NOT recomputed: the script only checks that each quoted figure is still present in the committed file), and an EXTRAPOLATION of the main-run
UNCERTAIN shares using the pilot_v2 answers sheet. The extrapolation is not a result and relabels no trial (plan section 7)."""
from common import *  # noqa
from m import *  # noqa

S = "07_humancheck_context"
HC = REPO / "handcheck"
quotes = [
    (HC / "set_c_results/two_rater_results_c.md", ["Overall on the reference labels (the more severe of R1 and R2): FAIL", "reference-irreversible items tagged below irreversible: 11", "Cohen's kappa: 0.938 (bootstrap 95% CI 0.874 to 0.985)",
                                                   "Linearly weighted kappa, tagger versus reference: 0.822 (bootstrap 95% CI 0.736 to 0.899", "| irreversible | 0 | 11 | 23 | 34 |"]),
    (HC / "pilot_v2/results/results_calls.md", ["irreversible: 4.1% (2/49; 95% CI 1.1 to 13.7)", "**Outcome: EXCLUDING.**", "Cohen's kappa over the 60 non-control items: **0.904**"]),
    (HC / "pilot_v2/results/results_answers.md", ["unsafe 56.9% (33/58; 95% CI 44.1 to 68.8)", "Cohen's kappa over the 60 non-control items: **0.932**", "32.0% (8/25; 95% CI 17.2 to 51.6)",
                                                   "76.5% (13/17; 95% CI 52.7 to 90.4)", "75.0% (12/16; 95% CI 50.5 to 89.8)"]),
]
chk = []
for f, ss in quotes:
    text = f.read_text(encoding="utf-8")
    for s in ss:
        chk.append({"file": str(f.relative_to(ROOT)), "quoted_text": s, "present_in_file": int(s in text)})
write_csv(TABLES / "t14_humancheck_quotes_check.csv", chk)
assert all(c["present_in_file"] for c in chk), "a quoted figure is not in the committed file any more"

PILOT = {"claude-haiku-4-5-20251001": (8, 25), "gemini-3.1-flash-lite": (13, 17), "gpt-5.4-nano": (12, 16), "ALL": (33, 58)}
trials = load_trials()
rows = []
for tier in ("cheap", "frontier"):
    for m in MODELS[tier]:
        rr = [t for t in trials if t["tier"] == tier and t["model"] == m]
        c = counts(rr)
        txt = sum(1 for t in rr if t["verdict"] == "uncertain" and t["final_text_len"] not in ("", "0"))
        k, n = PILOT.get(m, PILOT["ALL"])
        lo, hi = wilson(k, n)
        base = c["fail"] + c["vulnerable"]
        n_tr = c["n_trials"]
        rows.append({"tier": tier, "model": m, "frameworks": "+".join(FRAMEWORKS[tier]), "n_trials": n_tr, "observed_fail_or_vulnerable": base, "observed_text_unsafe_pct": 100 * base / n_tr,
                     "uncertain": c["uncertain"], "uncertain_share_pct": 100 * c["uncertain"] / n_tr, "uncertain_with_text": txt,
                     "pilot_v2_share_used": "own model" if m in PILOT else "pooled (no labelled frontier model)", "pilot_unsafe_pct": 100 * k / n, "pilot_lo_pct": 100 * lo, "pilot_hi_pct": 100 * hi,
                     "implied_extra_unsafe_point": txt * k / n, "implied_extra_unsafe_lo": txt * lo, "implied_extra_unsafe_hi": txt * hi,
                     "implied_text_unsafe_pct_point": 100 * (base + txt * k / n) / n_tr, "implied_text_unsafe_pct_lo": 100 * (base + txt * lo) / n_tr, "implied_text_unsafe_pct_hi": 100 * (base + txt * hi) / n_tr})
write_csv(TABLES / "t15_extrapolation_uncertain_share.csv", rows)
for r in rows:
    print(r["tier"], r["model"][:14], f"uncertain {r['uncertain_share_pct']:.1f}% with-text {r['uncertain_with_text']}  observed unsafe {r['observed_text_unsafe_pct']:.1f}% -> implied {r['implied_text_unsafe_pct_point']:.1f}% ({r['implied_text_unsafe_pct_lo']:.1f} to {r['implied_text_unsafe_pct_hi']:.1f})")
