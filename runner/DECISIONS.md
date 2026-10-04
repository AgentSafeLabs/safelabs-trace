# Traces-on runner: pilot decisions (2026-10-04)
D1 SafeAgent-300, 50 items, 5/category, seed 20261004 (ids in configs/pilot.yaml)
D2 runner supports langchain/adk/openai_agents; pilot runs langchain + adk
D3 three small models (ids verified at first real run)
D4 LiteLLM routing; no new installs
D5 1 trial/item; D6 12 inert tools, <=4 model calls/trial
D7 hard cap USD 20 + filled price_table.yaml required; provider spend limits as second guard
Text verdicts (pilot): safelabs-eval heuristic scorer. Report UNCERTAIN share; primary rates exclude UNCERTAIN; sensitivity bounds with UNCERTAIN as refusal and as compliance. Swap to JudgeCal once validated.
Severity: reported as pending validation until the two-rater gate (handcheck/rater_packet) is scored.
