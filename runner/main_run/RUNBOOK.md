# 1B main run: runbook for Waqar (commands in order)

Everything below is for you to run in your own terminal. Nothing in this folder was run against a real model. Order of the runs (plan section 8): OpenAI Agents smoke (cap USD 2), frontier smoke (cap USD 8), main_cheap (cap USD 30), main_frontier (cap USD 60 or less); total cap USD 100. Run folders go under `~/Desktop/Workspace/AgentSafeLabs/runs/`, evidence folders under `~/Desktop/Workspace/AgentSafeLabs/evidence/` (both outside every git repository; the runner refuses an evidence folder inside a git tree). Never commit, upload or print anything from `evidence/`. Read `MAIN_RUN_PLAN.md` first: it fixes the design, the smoke gate and the analysis before any data exists.

Shorthand used below:
```bash
export R=~/Desktop/Workspace/AgentSafeLabs
export M=$R/_release-staging/1b_main_run          # this folder
export PY=$R/safelabs-eval/.venv/bin/python
cd $R/safelabs-trace/runner
export PYTHONPATH="$PWD:$PWD/../src:$PWD/../../safelabs-eval"
```
Keys and the salt: load `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` and `SAFELABS_TRACE_SALT` in your own shell as you did for the pilot (`run_pilot.sh` only checks that they are non-empty and never prints them). Use the **same** `SAFELABS_TRACE_SALT` for every run of this series and for resume and rerun passes (identical arguments then get identical digests across runs; the manifest records the salt id).

## 0. Before anything
```bash
sh run_tests.sh                       # expect: all tests pass (87 passed when this was written) 
git status                            # your own check: the repo should hold no stray changes you do not expect
```
Make sure the Mac will not sleep during the long runs: put `caffeinate -i` in front of the run commands (below).

## 1. Put the design on record (before any data)
```bash
cp $M/MAIN_RUN_PLAN.md $M/RUNBOOK.md $M/FRONTIER_MODELS.md $R/safelabs-trace/runner/
cp $M/configs/*.yaml configs/
cp $M/price_table_main.yaml .
```
Commit these files yourself **before the smoke run** (the plan says so). If you change a model id or a cap, change it in the plan and the config first, then commit.

## 2. Verify the model ids with each provider (read-only list calls; the keys stay in your shell; only the matching lines are printed)
Cheap ids ran in the pilot; check them again anyway. Frontier ids come from the AgentPort-Bench paper (`FRONTIER_MODELS.md`): VERIFY BEFORE RUN.
```bash
curl -s https://api.anthropic.com/v1/models?limit=100 -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" | tr ',' '\n' | grep -o '"id":"[^"]*"' | grep -E 'claude-haiku-4-5|claude-opus-4-8'
curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY" | tr ',' '\n' | grep -o '"id": *"[^"]*"' | grep -E 'gpt-5\.4-nano|gpt-5\.5'
curl -s "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200" -H "x-goog-api-key: $GEMINI_API_KEY" | tr ',' '\n' | grep -o '"name": *"[^"]*"' | grep -E 'gemini-3\.1-flash-lite|gemini-3\.5-flash'
```
Each id must appear. If an id is missing or renamed, stop: fix `configs/main_frontier*.yaml` and the price row, update `FRONTIER_MODELS.md` and `MAIN_RUN_PLAN.md`, and commit before going on.

## 3. Confirm the prices (they are filled; confirm them on each provider's page)
`price_table_main.yaml` already holds the frontier list prices as of 2026-10-07 (standard tier, USD per million tokens): claude-opus-4-8 5.00 in / 25.00 out; gpt-5.5 5.00 in / 30.00 out; gemini-3.5-flash 1.50 in / 9.00 out. **Confirm each on the provider's page before running**; if one differs, edit it here and in `MAIN_RUN_PLAN.md`, and commit before the smoke. Reasoning tokens are charged as output. Then:
```bash
for c in smoke_openai_agents smoke_frontier main_cheap main_cheap_with_oa main_frontier main_frontier_with_oa; do echo "== $c"; $PY -m trace_runner --config configs/$c.yaml --estimate; done
```
Expected (written 2026-10-07; expected / worst case, the runner's INFERRED model): smoke_openai_agents 0.19 / 0.86; smoke_frontier 2.97 / 13.34; main_cheap 16.94 / 77.00; main_cheap_with_oa 25.40 / 115.49; main_frontier 44.49 / 200.14; main_frontier_with_oa 66.74 / 300.21. The worst-case figures are bounds under that model, far above the caps; the runner stops cleanly at the cap from actual usage.

## 4. OpenAI Agents smoke (60 trials)
```bash
caffeinate -i sh run_pilot.sh configs/smoke_openai_agents.yaml $R/runs/smoke_openai_agents $R/evidence/smoke_openai_agents 2>&1 | tee $R/runs/smoke_openai_agents_console.txt
```
`run_pilot.sh` prints the estimate and waits for Enter, then runs (about 4 minutes at the pilot's 3.3 s per trial; the console text holds no keys). If some trials are `missing_infrastructure`, rerun at most two passes:
```bash
$PY -m trace_runner --config configs/smoke_openai_agents.yaml --confirm-real --out $R/runs/smoke_openai_agents --evidence-dir $R/evidence/smoke_openai_agents --rerun-missing
```
(a second pass only if some are still missing). Then the gate:
```bash
$PY $M/scripts/check_smoke_gate.py --run $R/runs/smoke_openai_agents --evidence $R/evidence/smoke_openai_agents
python3 $M/scripts/budget_check.py $R/runs/smoke_openai_agents
```
`GATE PASSED`: use the `_with_oa` configs below. `GATE FAILED`: use the plain configs, and write down which items failed (the plan says openai_agents is then reported as excluded with that reason). Do not re-run the smoke to get a pass.

## 4b. Frontier smoke (120 trials; cost and plumbing only; its data are not part of the main-run results)
Run it after the OpenAI Agents smoke (so that its cost does not depend on that result). 20 items (the same as the OpenAI Agents smoke) x langchain+adk x the 3 frontier models; cap USD 8; about 7 minutes at the pilot's pace (frontier models may be slower).
```bash
caffeinate -i sh run_pilot.sh configs/smoke_frontier.yaml $R/runs/smoke_frontier $R/evidence/smoke_frontier 2>&1 | tee $R/runs/smoke_frontier_console.txt
# missing_infrastructure trials: at most two passes
$PY -m trace_runner --config configs/smoke_frontier.yaml --confirm-real --out $R/runs/smoke_frontier --evidence-dir $R/evidence/smoke_frontier --rerun-missing
$PY $M/scripts/check_smoke_gate.py --gate frontier --run $R/runs/smoke_frontier --evidence $R/evidence/smoke_frontier
python3 $M/scripts/budget_check.py $R/runs/smoke_openai_agents $R/runs/smoke_frontier
```
The only checks are `manifest OK` and `missing_infrastructure` at most 5% (at most 6 of 120); if either fails, main_frontier does not start until the cause is understood (you decide).

### 4c. Project main_frontier from the frontier smoke's real usage
```bash
python3 $M/scripts/budget_check.py $R/runs/smoke_openai_agents $R/runs/smoke_frontier        # actual spend so far (add main_cheap after section 5)
$PY $M/scripts/frontier_projection.py --run $R/runs/smoke_frontier --spent-before <SPEND_SO_FAR_IN_USD> --write $R/runs/main_frontier_projection.txt
```
`frontier_projection.py` reads only the smoke's `results.jsonl` token counts and the price table, prints the real cost per trial for each model and framework, the projection for main_frontier (langchain+adk) and main_frontier_with_oa (openai_agents' cells are the mean of its langchain and adk cells, INFERRED) against the cap (the smaller of 60 and 100 minus the spend so far, unless you pass `--cap`), and the plan's decision: openai_agents in main_frontier only if it fits; langchain+adk only if only that fits; if even langchain+adk exceeds the cap the plan does not decide (write a dated addendum first). Run it again with the cheap run's spend added (section 6) before you start main_frontier. `budget_check.py` only sums actual spend; the projection is `frontier_projection.py`.

## 5. Main run, cheap tier (cap USD 30; 5,400 trials, or 8,100 with openai_agents; about 5 h or 7.5 h at the pilot's pace)
```bash
# gate passed: CFG=main_cheap_with_oa    gate failed: CFG=main_cheap
CFG=main_cheap
caffeinate -i sh run_pilot.sh configs/$CFG.yaml $R/runs/main_cheap $R/evidence/main_cheap 2>&1 | tee $R/runs/main_cheap_console.txt
```
If the run is interrupted (it keeps every finished trial), continue with the same config, folder and salt:
```bash
caffeinate -i $PY -m trace_runner --config configs/$CFG.yaml --confirm-real --out $R/runs/main_cheap --evidence-dir $R/evidence/main_cheap --resume
```
Then the missing-data passes (at most two; the plan excludes whatever is still missing, never scores it as UNCERTAIN):
```bash
$PY -m trace_runner --config configs/$CFG.yaml --confirm-real --out $R/runs/main_cheap --evidence-dir $R/evidence/main_cheap --rerun-missing
$PY -m trace_runner --config configs/$CFG.yaml --out $R/runs/main_cheap --verify
python3 $M/scripts/budget_check.py $R/runs/smoke_openai_agents $R/runs/smoke_frontier $R/runs/main_cheap
```
If the run stopped for its cap (`stopped for budget: True` in the budget check), do NOT raise the cap or re-run with a bigger one: report the not-run trials per cell.

## 6. Main run, frontier tier (1,800 trials, or 2,700 with openai_agents; about 1.7 h or 2.5 h at the pilot's pace, which a frontier model may not match)
Apply the plan's cap rule and the cost rule first:
```bash
python3 $M/scripts/budget_check.py $R/runs/smoke_openai_agents $R/runs/smoke_frontier $R/runs/main_cheap     # actual spend so far
$PY $M/scripts/frontier_projection.py --run $R/runs/smoke_frontier --spent-before <SPEND_SO_FAR_IN_USD>        # prints the cap used and the DECISION line
```
The cap is the smaller of USD 60 and (100 minus the spend so far). If it is below 60, edit `cap_usd` in a copy of the config (`cp configs/main_frontier.yaml configs/main_frontier_run.yaml`), keep the copy and use it. The DECISION line tells you which config: `main_frontier_with_oa` only if the smoke gate passed AND the projection fits the cap; otherwise `main_frontier` (langchain+adk).
```bash
CFG=main_frontier        # or main_frontier_with_oa, or your lowered-cap copy, as the DECISION line says
$PY -m trace_runner --config configs/$CFG.yaml --estimate
caffeinate -i sh run_pilot.sh configs/$CFG.yaml $R/runs/main_frontier $R/evidence/main_frontier 2>&1 | tee $R/runs/main_frontier_console.txt
# interruption: the --resume command of section 5 with main_frontier; missing trials: up to two --rerun-missing passes as in section 5
$PY -m trace_runner --config configs/$CFG.yaml --out $R/runs/main_frontier --verify
python3 $M/scripts/budget_check.py $R/runs/smoke_openai_agents $R/runs/smoke_frontier $R/runs/main_cheap $R/runs/main_frontier
```
`budget_check.py` exits 1 and says so if the total spent exceeds USD 100.

## 7. Archive (as for the pilot; the evidence is never archived)
```bash
cd $R/runs
for n in smoke_openai_agents smoke_frontier main_cheap main_frontier; do
  tar -czf ${n}_$(date +%F).tar.gz $n
  find $n -type f | sort | xargs shasum -a 256 > ${n}_sha256.txt
done
ls -l *.tar.gz *_sha256.txt
```
Each run folder is digest-only (results, manifests, summaries, traces). Keep `evidence/` on this Mac only. Re-summarise any time without a model call: `python -m trace_runner --config configs/CFG.yaml --summarize --out RUN_DIR --summary-out SOME_NEW_FOLDER`.

## 8. Analysis
Exactly as written in `MAIN_RUN_PLAN.md` sections 3 to 7: the headline risky-action rate excludes the unclassified-shell bucket as not risky and the including rate is the upper bound; the permutation tests use 100,000 sign flips, seed 20261007; no rule change from this data.

## Cost projection (full tables: `cost_projection.md`)
Pilot_v2 spent USD 0.4835 for 300 trials. Cheap-tier figures are projections from the real pilot_v2 usage x prices. **Frontier figures are INDICATIONS** (INFERRED): no frontier model has run, so they use the same provider's cheap model's pilot tokens as a stand-in times the frontier list price; the frontier smoke's real usage replaces them (section 4c).

| run | trials | projection (USD) | runner `--estimate` expected / worst case | cap (USD) |
|---|---|---|---|---|
| smoke_openai_agents | 60 | 0.10 | 0.19 / 0.86 | 2 |
| smoke_frontier | 120 | 1.35 (indication) | 2.97 / 13.34 | 8 |
| main_cheap | 5,400 | 8.70 (haiku 5.42, nano 0.76, gemini 2.53) | 16.94 / 77.00 | 30 |
| main_cheap_with_oa | 8,100 | 13.05 | 25.40 / 115.49 | 30 |
| main_frontier | 1,800 | 20.24 (indication; opus 9.03, gpt-5.5 6.16, gemini-3.5 5.05) | 44.49 / 200.14 | 60 |
| main_frontier_with_oa | 2,700 | 30.36 (indication) | 66.74 / 300.21 (above the cap of 60) | 60 |

Whole series by projection (frontier = indication): USD 30.39 without openai_agents in the main runs, USD 44.86 with it, against the total of USD 100 (the four caps add to exactly USD 100). Totals under the runner's own estimate: expected USD 64.59 / 95.30, worst case USD 291.34 / 429.90 (without / with openai_agents); those worst cases are bounds under an INFERRED model, not forecasts: the caps are what limit spending, and a run that hits its cap records the trials it could not start as `not_run_budget`. The projections for the cheap tier are about half of the runner's expected figure because the real pilot_v2 trials used fewer prompt tokens than that model assumes.

## If something goes wrong
- A run refuses to start: read the message (it names the cause: missing key variable names, a git-tree evidence folder, a null price, rows already in the folder). Nothing is spent when it refuses.
- Unexpected error spike (`rate_limit_or_quota`, `provider_unavailable`): stop with Ctrl-C (finished trials are kept), wait, then `--resume`.
- Never delete or edit anything inside a run folder; the manifest hashes it. A void or failed attempt is renamed and kept.
