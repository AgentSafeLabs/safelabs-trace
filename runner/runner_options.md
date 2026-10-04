# 1B traces-on runner: options memo (I stopped here; no runner was built)

**Why I stopped.** You told me to stop and write this memo if `design.md` does not fix which benchmark items, frameworks or models the traces-on rerun uses. It does not: `design.md` and `1b_design/report.md` fix the tool sandbox direction (inert recording tools), the severity-only first action verdict, the metrics and the handlers, but say the rerun's cost is "UNKNOWN until the subset is chosen" (`design.md`, E6 effort paragraph) and leave "which tool inventories" open (`report.md`, decision 6). Nothing else in `_release-staging` fixes them either. I have not guessed. Tags: VERIFIED (read from a file), INFERRED (my estimate), UNKNOWN.

## Facts that bear on the choice
| fact | value |
|---|---|
| AgentPort-Bench prompts | 30 prompts (3 per ASI category) with seeds 0 to 9; the stored v2 run has frameworks autogen, crewai, http, langchain, llamaindex, openai-agents (two more in the CFPS file) and six models (VERIFIED, `agentdojo-x/results/full_run_7020_v2.jsonl`) |
| SafeAgent-300 prompts | 300 prompts, 30 per category, one response per model per prompt, six models (VERIFIED, `safeagent-300/datasheet.md` and `safelabs-eval/results`); median prompt 224 characters, longest 390 |
| Existing benchmark agents | have no tools (`agent_factories.py`; the traces-on rerun needs the inert tools, decision 6) |
| Handlers that exist | LangChain, Google ADK, OpenAI Agents SDK (all with the mandatory export safeguards) |
| Model roster used before | claude-haiku-4-5, claude-opus-4-8, gpt-5.4-nano, gpt-5.5, gemini-3.1-flash-lite, gemini-3.5-flash |
| Typical response size (stored usage, SafeAgent-300, median completion tokens) | haiku 256, opus 552, nano 190, gpt-5.5 320, flash-lite 134, flash 126; median prompt about 65 to 95 tokens |
| Provider routes installed in the venv | `litellm` 1.91.1 (ADK `LiteLlm`, OpenAI Agents `LitellmModel`), `anthropic`, `openai`, `google-genai`. **Not installed:** `langchain-openai`, `langchain-anthropic`, `langchain-google-genai`, so a real LangChain run on any provider needs either those packages (an install I would not do without your say) or a LiteLLM-backed chat model |
| Reusable from safelabs-eval | retry profiles `default` and `benchmark` (`safelabs/agents/retry.py:26-28`), `missing_infrastructure` records and `--rerun-missing`, the manifest with `rerun_history` |

## Decisions I need
**D1. Items.** (a) SafeAgent-300, 5 prompts per category, 50 in all, drawn with a fixed seed; (b) SafeAgent-300, five categories you choose, all 30 prompts each (150); (c) AgentPort-Bench's 30 prompts with 3 seeds (90 per cell); (d) a mix. I recommend (a) for a first run: it covers every category, and the stored responses give a text-only baseline for the same prompts.
**D2. Frameworks.** LangChain + ADK (your earlier "first two"), or all three. OpenAI Agents adds the strict export safeguards and a 'no failure_error_function' rule but works with the handler already tested. I recommend LangChain + ADK first.
**D3. Models.** One cheap model per provider (haiku, nano, flash-lite), the frontier trio, or all six. I recommend the three cheap models for the pilot.
**D4. Provider routing.** How non-native providers reach each framework: LiteLLM for everything non-native (nothing new to install), or you approve installing the three LangChain provider packages. This also fixes the keys I need (below).
**D5. Trials.** 1, 3 (the frontier-tier design used 3) or 10 seeds per item. I recommend 1 for the pilot, then 3.
**D6. Tool set and loop.** All 12 inert tools attached to every agent (recommended), at most 4 model calls per trial, deterministic fake results, no per-category tool subsets. Say if you want fewer tools or a different system prompt.
**D7. Budget.** A cap, and the price table (I never invent prices; `--estimate` will refuse without it).

## Size and precision (INFERRED token model: 12 tool schemas about 1,500 tokens per model call, at most two calls, output 1.5 times the stored median)
| configuration | trials | input tokens | output tokens |
|---|---|---|---|
| C1 pilot: 50 items, 2 frameworks, 3 cheap models, 1 seed | 300 | 0.9 M | 0.09 M |
| C2: 50 items, 3 frameworks, 3 cheap models, 3 seeds | 1,350 | 4.2 M | 0.39 M |
| C3: 150 items (five categories), 2 frameworks, 3 cheap models, 1 seed | 900 | 2.8 M | 0.26 M |
| C4: AgentPort-Bench 30 prompts, 3 frameworks, 3 cheap models, 3 seeds | 810 | 2.5 M | 0.23 M |
| C5: 50 items, 3 frameworks, all 6 models, 3 seeds | 2,700 | 8.5 M | 1.07 M |
Multiply by your price table for cost. Precision of the hidden-action rate (Wilson 95% half-width, percentage points, at 50% / at 10%) by number of safe-text trials in a cell: 30: 17 / 11; 50: 13 / 8.5; 100: 10 / 6; 150: 8 / 5; 300: 5.6 / 3.4. A cell of 30 trials will only show large effects; the pilot is for plumbing and for seeing whether the models call tools at all.

## What a real run will need from you
The choices above; the keys in the environment at run time only (one per provider you pick: Anthropic, OpenAI, Google; the runner will read them from the environment and never log or store them); the price table; permission to install packages only if you choose that route in D4.

## What happens next
Reply with D1 to D7 (or "use the recommendations"), or tell me to build the runner now with config placeholders for items, frameworks and models. It is config-driven, so building it does not depend on these choices, but you asked me not to guess and I have not started it.

## Read and not read
Read: `1b_design/design.md` and `report.md`; the AgentPort and SafeAgent result files (counts and stored token usage only); the retry profile source; the list of installed packages. Not read in this pass, because the stop rule applied: the `safelabs-trace` README and handlers beyond what earlier tasks built, `run_eval` details, the manifest code. No hand-check key, result, void or labelled file was opened.

## Rules bent
Read-only scripts used the system `python3`. Nothing was written except this file; no git or gh command, no network, no install, no key or `.env` read.
