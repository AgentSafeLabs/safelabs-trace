"""E. EXPLORATORY, NOT PRE-REGISTERED (raw p only; no Holm; nothing here is a headline):
 1. cheap vs frontier tier (langchain+adk only, the two frameworks present in both tiers), by tier and by provider pair;
 2. OpenAI Agents (cheap tier only; a smoke-gated framework): gate evidence and its cells next to langchain / adk;
 3. provider-side outcomes kept SCORED by the agreed rule (error_class content_policy: gpt-5.5; no_output_text: claude-opus-4-8): counts per cell and a sensitivity analysis that drops those trials;
 4. per-category (ASI01 to ASI10) breakdown."""
from common import *  # noqa
from m import *  # noqa
from stats import *  # noqa
import numpy as np

S = "06_exploratory"
trials = load_trials()
SRC = "tables/trial_level.csv"
LA = ("langchain", "adk")

# ---- 1. tier contrasts -------------------------------------------------------------------------------------------------------------
def tier_vec(tier, fws, models, drop=None, field="risky_excl"):
    per = [item_rates(trials, tier, fw, m, field, drop) for fw in fws for m in models]
    items = sorted(set.intersection(*[set(p) for p in per]))
    return {i: float(np.mean([p[i] for p in per])) for i in items}

rows = []
def add(label, a, b):
    c = contrast(a, b)
    rows.append({"contrast": label, **c})
add("cheap tier (3 models) - frontier tier (3 models), langchain+adk pooled", tier_vec("cheap", LA, CHEAP), tier_vec("frontier", LA, FRONTIER))
for fw in LA:
    add(f"cheap tier - frontier tier, {fw}", tier_vec("cheap", (fw,), CHEAP), tier_vec("frontier", (fw,), FRONTIER))
for c_m, f_m in zip(CHEAP, FRONTIER):  # provider pairs, in the order anthropic, openai, google
    add(f"{c_m} - {f_m}, langchain+adk pooled", tier_vec("cheap", LA, [c_m]), tier_vec("frontier", LA, [f_m]))
write_csv(TABLES / "t7_exploratory_tier_contrasts.csv", rows)
for r in rows:
    cite(S, "tier." + r["contrast"][:40].replace(" ", "_"), "EXPLORATORY " + r["contrast"] + " (item-level risky rate, bucket excluded; positive = cheap higher)", None, r["n_items"], r["diff_points"], "tables/t7_exploratory_tier_contrasts.csv",
         f"raw p {r['p_raw']:.5f}; bootstrap 95% CI {r['boot_lo']:.2f} to {r['boot_hi']:.2f} points", unit="points")

# ---- 3. provider-side outcomes -----------------------------------------------------------------------------------------------------
side = lambda t: t["error_class"] in ("content_policy", "no_output_text")
cnt = []
for tier in ("cheap", "frontier"):
    for fw in FRAMEWORKS[tier]:
        for m in MODELS[tier]:
            rr = [t for t in trials if t["tier"] == tier and t["framework"] == fw and t["model"] == m]
            cp = [t for t in rr if t["error_class"] == "content_policy"]
            no = [t for t in rr if t["error_class"] == "no_output_text"]
            if cp or no:
                other = [t for t in rr if side(t)]
                cnt.append({"tier": tier, "framework": fw, "model": m, "n_trials": len(rr), "content_policy": len(cp), "no_output_text": len(no), "pct_of_cell": 100 * (len(cp) + len(no)) / len(rr),
                            "of_which_uncertain": sum(t["verdict"] == "uncertain" for t in other), "of_which_tool_call_only": sum(t["tool_call_only"] for t in other),
                            "of_which_risky_action": sum(t["risky"] for t in other), "of_which_final_text_len_0": sum(1 for t in other if t["final_text_len"] == "0")})
                cite(S, f"provider_side.{m}.{fw}", f"trials with a provider-side outcome kept scored (content_policy {len(cp)}, no_output_text {len(no)}), {fw} x {m}", len(cp) + len(no), len(rr), None, SRC, "rule: kept scored (UNCERTAIN)")
write_csv(TABLES / "t8_provider_side_counts.csv", cnt)
# sensitivity: drop those trials (all cells), recompute headline rates for the affected models
sens = []
for tier, m in (("frontier", "gpt-5.5"), ("frontier", "claude-opus-4-8")):
    for fw in FRAMEWORKS[tier]:
        for variant, drop in (("as_run", None), ("provider_side_dropped", side)):
            rr = [t for t in trials if t["tier"] == tier and t["framework"] == fw and t["model"] == m and not (drop and drop(t))]
            c = counts(rr)
            dec = c["n_decided"]
            sens.append({"tier": tier, "framework": fw, "model": m, "variant": variant, "n_trials": c["n_trials"], **rcols("risky_excl", c["risky_excl"], c["n_known"]), **rcols("risky_incl", c["risky_incl"], c["n_known"]),
                         **rcols("asr_text", c["asr_text_k"], dec), **rcols("asr_aware", c["asr_aware_k"], dec), **rcols("uncertain_share", c["uncertain"], c["n_trials"])})
write_csv(TABLES / "t9_provider_side_sensitivity_rates.csv", sens)
sc = []
for (tier, fw, a, b) in [("frontier", fw, a, b) for fw in FRAMEWORKS["frontier"] for a, b in ((FRONTIER[0], FRONTIER[1]), (FRONTIER[0], FRONTIER[2]), (FRONTIER[1], FRONTIER[2]))]:
    base = contrast(item_rates(trials, tier, fw, a), item_rates(trials, tier, fw, b))
    drp = contrast(item_rates(trials, tier, fw, a, drop=side), item_rates(trials, tier, fw, b, drop=side))
    sc.append({"framework": fw, "A": a, "B": b, "diff_points_as_run": base["diff_points"], "p_raw_as_run": base["p_raw"], "n_items_as_run": base["n_items"], "diff_points_dropped": drp["diff_points"],
               "p_raw_dropped": drp["p_raw"], "n_items_dropped": drp["n_items"], "boot_lo_dropped": drp["boot_lo"], "boot_hi_dropped": drp["boot_hi"]})
write_csv(TABLES / "t10_provider_side_sensitivity_contrasts.csv", sc)

# ---- 4. per category ------------------------------------------------------------------------------------------------------------------
cats = sorted({t["category"] for t in trials})
cc, cm = [], []
for cat in cats:
    for tier in ("cheap", "frontier"):
        for fw in FRAMEWORKS[tier]:
            for m in MODELS[tier]:
                rr = [t for t in trials if t["category"] == cat and t["tier"] == tier and t["framework"] == fw and t["model"] == m]
                c = counts(rr)
                cc.append({"category": cat, "tier": tier, "framework": fw, "model": m, "n_trials": c["n_trials"], **rcols("risky_excl", c["risky_excl"], c["n_known"]), **rcols("risky_incl", c["risky_incl"], c["n_known"]),
                           **rcols("uncertain_share", c["uncertain"], c["n_trials"]), **rcols("asr_text", c["asr_text_k"], c["n_decided"]), **rcols("asr_aware", c["asr_aware_k"], c["n_decided"])})
        for m in MODELS[tier]:
            rr = [t for t in trials if t["category"] == cat and t["tier"] == tier and t["model"] == m]
            c = counts(rr)
            cm.append({"category": cat, "tier": tier, "model": m, "frameworks": "+".join(FRAMEWORKS[tier]), "n_trials": c["n_trials"], **rcols("risky_excl", c["risky_excl"], c["n_known"]),
                       **rcols("risky_incl", c["risky_incl"], c["n_known"]), **rcols("uncertain_share", c["uncertain"], c["n_trials"]), **rcols("asr_text", c["asr_text_k"], c["n_decided"]),
                       **rcols("asr_aware", c["asr_aware_k"], c["n_decided"])})
write_csv(TABLES / "t11_category_by_cell.csv", cc)
write_csv(TABLES / "t12_category_by_model.csv", cm)
# 2. OpenAI Agents gate evidence
integ = json.loads((TABLES / "integrity.json").read_text())
oa = integ["smoke_openai_agents"]
write_csv(TABLES / "t13_openai_agents_gate.csv", [{"item": "1 all 60 scored or missing, none absent or not_run_budget", "value": f"rows {oa['rows']}, not_run_budget {oa['not_run_budget']}"},
                                                  {"item": "2 missing_infrastructure at most 3 of 60", "value": oa["missing_infrastructure"]}, {"item": "3 manifest OK", "value": oa["verify"]},
                                                  {"item": "4 openai_export_off / strict_handler / exporter_env_clear", "value": f"{oa['safety'].get('openai_export_off')} / {oa['safety'].get('strict_handler')} / {oa['safety'].get('exporter_env_clear')}"},
                                                  {"item": "5 evidence for every trial", "value": "not checked here (the evidence folder is not opened under this task's rules); the run's console reports the evidence line count"}])
flush_citable(S)
for r in rows:
    print(r["contrast"][:70], f"{r['diff_points']:.2f}", f"p={r['p_raw']:.5f}")
print(*cnt, sep="\n")
for r in sens:
    print(r["framework"], r["model"][:10], r["variant"], r["n_trials"], f"{r['risky_excl_pct']:.1f}", f"{r['uncertain_share_pct']:.1f}")
for r in sc:
    print(r["framework"], r["A"][:8], r["B"][:8], f"{r['diff_points_as_run']:.2f} p {r['p_raw_as_run']:.4f} -> {r['diff_points_dropped']:.2f} p {r['p_raw_dropped']:.4f}")
