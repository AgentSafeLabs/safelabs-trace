"""B and C. Primary outcomes (risky-action rate excl./incl. the unclassified-shell bucket, text-only and action-aware ASR + lift, verdict coverage incl. the UNCERTAIN share) and secondary outcomes
(irreversible rate, hidden-action, acted-without-answer, cap-hit), per framework x model, per model, and pooled per tier, with Wilson 95% CIs (trial level, as the runner does)."""
from common import *  # noqa
from m import *  # noqa

S = "03_primary_secondary"
trials = load_trials()
SRC = "tables/trial_level.csv (from runs/main_cheap, runs/main_frontier)"
prim_r, prim_a, prim_v, sec = [], [], [], []
for gt, lab, rows in groups(trials):
    c = counts(rows)
    base = {"group": gt, **lab}
    prim_r.append({**base, "n_trials": c["n_trials"], **rcols("risky_excl", c["risky_excl"], c["n_known"]), **rcols("risky_incl", c["risky_incl"], c["n_known"]),
                   "only_in_bucket_trials": c["risky_only_in_bucket"], **rcols("risky_removed", c["risky_excl"], c["n_known"] - c["risky_only_in_bucket"])})
    dec = c["n_decided"]
    prim_a.append({**base, "n_trials": c["n_trials"], "n_decided_not_uncertain": dec, **rcols("asr_text", c["asr_text_k"], dec), **rcols("asr_aware", c["asr_aware_k"], dec),
                   "lift_points": (100 * (c["asr_aware_k"] - c["asr_text_k"]) / dec) if dec else None, **rcols("action_only", c["action_only_k"], dec), **rcols("asr_aware_bucket_excl", c["asr_aware_excl_k"], dec)})
    n = c["n_trials"]
    prim_v.append({**base, "n_trials": n, "pass": c["pass"], "fail": c["fail"], "vulnerable": c["vulnerable"], "uncertain": c["uncertain"], **rcols("uncertain_share", c["uncertain"], n),
                   "uncertain_tool_call_only": c["uncertain_tool_call_only"], "uncertain_with_text": c["uncertain_with_text"], "tool_call_only_all": c["tool_call_only"], "cap_hit": c["cap_hit_k"],
                   "action_unknown": c["action_unknown"], "missing_infrastructure": c["missing"]})
    sec.append({**base, "n_trials": n, **rcols("irreversible_incl", c["irr_incl"], c["n_known"]), **rcols("irreversible_excl", c["irr_excl"], c["n_known"]),
                **rcols("hidden_action", c["hidden_k"], c["n_text_safe"]), **rcols("hidden_action_bucket_excl", c["hidden_excl_k"], c["n_text_safe"]),
                **rcols("acted_without_answer", c["acted_wo_answer_k"], c["no_text_n"]), **rcols("cap_hit_rate", c["cap_hit_k"], n), **rcols("talk_only", c["talk_only_k"], c["n_text_unsafe"])})
    if gt in ("tier_all_frameworks", "tier_langchain_adk") or (gt == "model_all_frameworks"):
        key = f"{lab['tier']}.{lab['model']}.{lab['framework']}"
        cite(S, f"risky_excl.{key}", f"risky-action rate, bucket excluded as not risky (headline), {lab['tier']} {lab['model']} fw={lab['framework']}", c["risky_excl"], c["n_known"], None, SRC)
        cite(S, f"risky_incl.{key}", f"risky-action rate, bucket included (upper bound), {lab['tier']} {lab['model']} fw={lab['framework']}", c["risky_incl"], c["n_known"], None, SRC)
        cite(S, f"uncertain.{key}", f"UNCERTAIN share, {lab['tier']} {lab['model']} fw={lab['framework']}", c["uncertain"], n, None, SRC)
        cite(S, f"asr_text.{key}", f"text-only ASR (UNCERTAIN excluded), {lab['tier']} {lab['model']} fw={lab['framework']}", c["asr_text_k"], dec, None, SRC)
        cite(S, f"asr_aware.{key}", f"action-aware ASR (UNCERTAIN excluded), {lab['tier']} {lab['model']} fw={lab['framework']}", c["asr_aware_k"], dec, None, SRC)
    if gt == "cell":
        key = f"{lab['tier']}.{lab['model']}.{lab['framework']}"
        cite(S, f"risky_excl.cell.{key}", f"risky-action rate bucket excluded, cell {lab['framework']} x {lab['model']}", c["risky_excl"], c["n_known"], None, SRC)
        cite(S, f"risky_incl.cell.{key}", f"risky-action rate bucket included, cell {lab['framework']} x {lab['model']}", c["risky_incl"], c["n_known"], None, SRC)
write_csv(TABLES / "t1_primary_risky_action.csv", prim_r)
write_csv(TABLES / "t2_primary_asr.csv", prim_a)
write_csv(TABLES / "t3_primary_verdict_coverage.csv", prim_v)
write_csv(TABLES / "t4_secondary.csv", sec)
flush_citable(S)
for r in prim_r:
    if r["group"] in ("tier_all_frameworks", "tier_langchain_adk"):
        print(r["tier"], r["framework"], f"excl {r['risky_excl_pct']:.1f} incl {r['risky_incl_pct']:.1f} n_known {r['risky_excl_n']}")
