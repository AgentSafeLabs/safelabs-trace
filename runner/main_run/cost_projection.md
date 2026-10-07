# Cost projection for the 1B main run (from pilot_v2 real per-trial usage x prices)

Inputs: `runs/pilot_v2/results.jsonl` (300 scored trials: prompt, completion and reasoning tokens per trial) and the prices of `price_table_main.yaml`. The pilot_v2 manifest spent **USD 0.4835**; usage x price recomputed over the 300 trials gives USD 0.4835 (check). Cheap-tier figures come from the real pilot_v2 usage (openai_agents: the mean of the model's two pilot frameworks, INFERRED). **Frontier figures are INDICATIONS only** (INFERRED): no frontier model has been run, so the tokens per trial are those of the same provider's cheap model times the frontier list price of 2026-10-07 (confirm the prices before running); a frontier model may call more tools, answer at greater length, or use reasoning tokens (charged as output), so the real cost can differ a lot. The frontier smoke (120 trials) gives the real usage; `scripts/frontier_projection.py` turns it into the main_frontier projection. All figures are projections, not limits: the limit is each config's `cap_usd`, enforced by the runner from actual usage.

## Pilot_v2 per-trial usage (real) and cost per trial

| model | framework | trials | mean prompt tokens | mean output+reasoning tokens | USD per trial | 95th percentile trial | max trial |
|---|---|---|---|---|---|---|---|
| claude-haiku-4-5-20251001 | langchain | 50 | 1403 | 288 | 0.00284 | 0.00319 | 0.00626 |
| claude-haiku-4-5-20251001 | adk | 50 | 1721 | 292 | 0.00318 | 0.00345 | 0.01956 |
| claude-haiku-4-5-20251001 | openai_agents (INFERRED: mean of the two) | - | 1562 | 290 | 0.00301 | 0.00332 | 0.01291 |
| gpt-5.4-nano | langchain | 50 | 690 | 210 | 0.00040 | 0.00084 | 0.00093 |
| gpt-5.4-nano | adk | 50 | 1010 | 190 | 0.00044 | 0.00085 | 0.00155 |
| gpt-5.4-nano | openai_agents (INFERRED: mean of the two) | - | 850 | 200 | 0.00042 | 0.00085 | 0.00124 |
| gemini-3.1-flash-lite | langchain | 50 | 3633 | 200 | 0.00121 | 0.00223 | 0.00262 |
| gemini-3.1-flash-lite | adk | 50 | 5015 | 230 | 0.00160 | 0.00317 | 0.00384 |
| gemini-3.1-flash-lite | openai_agents (INFERRED: mean of the two) | - | 4324 | 215 | 0.00140 | 0.00270 | 0.00323 |

## Per run (cap = the config's hard limit)

| run | trials | USD, projection | of which per model | runner `--estimate` (its own INFERRED token model; expected / worst case) | cap USD |
|---|---|---|---|---|---|
| smoke_openai_agents | 60 | 0.10 | claude 0.06, gpt 0.01, gemini 0.03 | 0.19 / 0.86 | 2 |
| smoke_frontier | 120 | **1.35 (INDICATION, stand-in tokens x list price)** | claude 0.60, gpt 0.41, gemini 0.34 | 2.97 / 13.34 | 8 |
| main_cheap | 5,400 | 8.70 | claude 5.42, gpt 0.76, gemini 2.53 | 16.94 / 77.00 | 30 |
| main_cheap_with_oa | 8,100 | 13.05 | claude 8.13, gpt 1.14, gemini 3.79 | 25.40 / 115.49 | 30 |
| main_frontier | 1,800 | **20.24 (INDICATION, stand-in tokens x list price)** | claude 9.03, gpt 6.16, gemini 5.05 | 44.49 / 200.14 | 60 |
| main_frontier_with_oa | 2,700 | **30.36 (INDICATION, stand-in tokens x list price)** | claude 13.55, gpt 9.24, gemini 7.58 | 66.74 / 300.21 | 60 |

Whole series (projection; frontier = indication): without openai_agents in the main runs USD 30.39; with it USD 44.86; against the total hard budget of USD 100 (the four caps add to exactly USD 100).

**Note on the runner's `--estimate`.** Its expected figures (main_cheap USD 16.94, main_cheap_with_oa 25.40, main_frontier 44.49, main_frontier_with_oa 66.74 which is **above its cap of 60**) assume 3 model calls per trial each carrying the full 1,570-token overhead and output tokens equal to the config's `est_output_tokens`; the real pilot_v2 cheap trials used far fewer prompt tokens on average, so for the cheap tier the usage-based projection is about half of the runner's expected figure. Its worst-case figures (e.g. USD 200.14 for main_frontier) are bounds under the INFERRED model, not predictions. The runner stops cleanly at the cap from actual usage whichever figure is right: trials it could not start are recorded `not_run_budget` and reported per cell (plan, section 6).

**Caps and the total.** smoke_openai_agents 2 + smoke_frontier 8 + main_cheap 30 + main_frontier 60 = USD 100 (the same with the `_with_oa` configs). Per-run caps are hard stops; the plan sets the main_frontier cap to the smaller of 60 and (100 minus the actual spend of the earlier runs) and never raises a cap (MAIN_RUN_PLAN.md section 9).

