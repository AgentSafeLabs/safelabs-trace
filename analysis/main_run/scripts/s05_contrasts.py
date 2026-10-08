"""D. The pre-registered contrasts (MAIN_RUN_PLAN section 5): item-level headline risky-action rate (bucket excluded as not risky), trials averaged within item, paired by item.
(a) framework contrasts: for each model, each pair of frameworks; (b) model contrasts: for each framework, each pair of models within a tier (3 pairs per tier).
Holm-Bonferroni (alpha 0.05) within each family. Two readings of the frameworks present are reported:
  LITERAL (headline): the frameworks that are in the main run, i.e. openai_agents included in the cheap tier (the smoke gate passed, the plan says it then joins the main runs);
  LANGCHAIN+ADK ONLY (sensitivity, author choice): the family restricted to the two frameworks that exist in both tiers.
Every contrast is reported, significant or not."""
from common import *  # noqa
from stats import *  # noqa
from itertools import combinations

S = "05_contrasts"
trials = load_trials()
rate = {(tier, fw, m): item_rates(trials, tier, fw, m) for tier in MODELS for fw in FRAMEWORKS[tier] for m in MODELS[tier]}
fam_fw, fam_m = [], []
for tier in ("cheap", "frontier"):
    for m in MODELS[tier]:
        for a, b in combinations(FRAMEWORKS[tier], 2):
            fam_fw.append({"family": "framework", "tier": tier, "model": m, "framework": f"{a} - {b}", "A": a, "B": b, **contrast(rate[(tier, a, m)], rate[(tier, b, m)])})
    for fw in FRAMEWORKS[tier]:
        for a, b in combinations(MODELS[tier], 2):
            fam_m.append({"family": "model", "tier": tier, "model": f"{a} - {b}", "framework": fw, "A": a, "B": b, **contrast(rate[(tier, fw, a)], rate[(tier, fw, b)])})
for fam in (fam_fw, fam_m):
    for r, h in zip(fam, holm([r["p_raw"] for r in fam])):
        r["p_holm_literal_family"] = h
    sub = [r for r in fam if "openai_agents" not in (r["A"], r["B"]) and r["framework"] != "openai_agents"]
    for r, h in zip(sub, holm([r["p_raw"] for r in sub])):
        r["p_holm_langchain_adk_family"] = h
    for r in fam:
        r["sig_literal_0.05"] = int(r["p_holm_literal_family"] < 0.05)
        r["sig_lc_adk_0.05"] = "" if "p_holm_langchain_adk_family" not in r else int(r["p_holm_langchain_adk_family"] < 0.05)
        r["positive_means"] = f"{r['A']} higher than {r['B']}"
cols = ["family", "tier", "model", "framework", "A", "B", "n_items", "mean_A_pct", "mean_B_pct", "diff_points", "boot_lo", "boot_hi", "n_items_differing", "p_raw", "p_holm_literal_family", "sig_literal_0.05",
        "p_holm_langchain_adk_family", "sig_lc_adk_0.05", "positive_means"]
write_csv(TABLES / "t5_contrasts_framework.csv", fam_fw, cols)
write_csv(TABLES / "t6_contrasts_model.csv", fam_m, cols)
for r in fam_fw + fam_m:
    cite(S, f"contrast.{r['family']}.{r['tier']}.{r['model']}.{r['framework']}".replace(" ", ""), f"{r['family']} contrast {r['tier']}: {r['model']} / {r['framework']} (A - B; item-level risky rate, bucket excluded)",
         None, r["n_items"], r["diff_points"], "tables/t5_contrasts_framework.csv, tables/t6_contrasts_model.csv", f"raw p {r['p_raw']:.5f}; Holm (literal family) {r['p_holm_literal_family']:.5f}; bootstrap 95% CI {r['boot_lo']:.2f} to {r['boot_hi']:.2f} points", unit="points")
flush_citable(S)
for r in fam_fw + fam_m:
    print(r["family"], r["tier"], r["model"][:34], r["framework"][:22], f"diff {r['diff_points']:.2f} p {r['p_raw']:.5f} holm {r['p_holm_literal_family']:.4f} lcadk {r.get('p_holm_langchain_adk_family', '')}")
