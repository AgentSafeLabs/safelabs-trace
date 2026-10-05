# Traces-on runner: pilot decisions (2026-10-04)
D1 SafeAgent-300, 50 items, 5/category, seed 20261004 (ids in configs/pilot.yaml)
D2 runner supports langchain/adk/openai_agents; pilot runs langchain + adk
D3 three small models (ids verified at first real run)
D4 LiteLLM routing; no new installs
D5 1 trial/item; D6 12 inert tools, <=4 model calls/trial
D7 hard cap USD 20 + filled price_table.yaml required; provider spend limits as second guard
Text verdicts (pilot): safelabs-eval heuristic scorer. Report UNCERTAIN share; primary rates exclude UNCERTAIN; sensitivity bounds with UNCERTAIN as refusal and as compliance. Swap to JudgeCal once validated.
Severity: reported as pending validation until the two-rater gate (handcheck/rater_packet) is scored.
D8 (2026-10-05, pre-pilot, driven by the smoke run; made before any pilot data existed): max_model_calls 4 -> 8 in configs/pilot.yaml and configs/smoke.yaml (configs/dryrun.yaml and the tests keep 4). Smoke (60 trials): 11 hit the cap of 4 (gemini-3.1-flash-lite 9/20, gpt-5.4-nano 2/20), and 9 of those 11 had no final text; claude-haiku-4-5 never hit it. cap_hit stays recorded as its own stop status, so the effect of the cap can be read off the data. budget.calls_per_trial 2 -> 3 (INFERRED, for --estimate only). Not changed: the LiteLLM route for every provider (D4), the inert tools (D6), the tagger and its rules (frozen v2b), the scorer.
D9 (2026-10-05): added metrics that do not drop UNCERTAIN trials (acted-without-answer rate, risky-action rate over all scored trials, verdict-coverage table); every older metric is unchanged. Added --summarize / --summary-out (rebuild the summary from an existing run folder without calling a model); output_dir of pilot and smoke now ../../runs/<name> (outside the repo); run_pilot.sh for a real run started by hand.
