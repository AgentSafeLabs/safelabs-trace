# Frontier-tier models of AgentPort-Bench (and so of the 1B main run)

**VERIFY BEFORE RUN.** The ids below were found with certainty in the AgentPort-Bench paper source and the corrections tables, but they are model ids as named in that study, not a provider check made today (ids may have changed or been retired). Nothing here was verified against a provider (no network). The runner does not check ids at `--estimate` or `--dry-run`; the first real call does.

| model id (as in AgentPort-Bench) | provider | LiteLLM route the runner would use | status |
|---|---|---|---|
| `claude-opus-4-8` | Anthropic | `anthropic/claude-opus-4-8` | VERIFY BEFORE RUN |
| `gpt-5.5` | OpenAI | `openai/gpt-5.5` | VERIFY BEFORE RUN |
| `gemini-3.5-flash` | Google | `gemini/gemini-3.5-flash` | VERIFY BEFORE RUN |

Where found (read-only):
- `_release-staging/v2_ship/v5_sources/AgentPort-Bench/AgentPort-Bench_Merged.tex`, section "Experimental Matrix": "frontier tier: claude-opus-4-8, gpt-5.5, gemini-3.5-flash" (cheap tier: claude-haiku-4-5-20251001, gpt-5.4-nano, gemini-3.1-flash-lite, the three pilot models); the model cards are cited as `anthropic2026opus48`, `openai2026gpt55`, `deepmind2026gemini35flash` in `agentport_refs.bib`.
- `_release-staging/v2_ship/citable_numbers_v9.md`: the frontier-tier rows and the per-model tables use the same three ids (`claude-opus-4-8`, `gpt-5.5`, `gemini-3.5-flash`).

What is an inference, not a finding:
- **The routes.** The runner configs contain no frontier model, so the three routes follow the pattern of the three cheap models in `runner/configs/pilot.yaml` (`anthropic/<id>`, `openai/<id>`, `gemini/<id>`). The earlier AgentPort-Bench rounds ran in another harness (agentdojo-x, not readable here), so how that harness addressed the models, and whether it used the exact strings above as API ids, is not something I could confirm.
- **`est_output_tokens`** in `main_frontier*.yaml` (384, 286, 201) are stand-ins copied from the same provider's cheap model, for the budget stop's worst-case figure only.

Open question for Waqar: confirm the three ids against each provider's current model list before the frontier run (the RUNBOOK has a read-only list command per provider). If an id has been renamed, change it (and its price row) in `configs/main_frontier*.yaml` and `price_table_main.yaml` **before** the plan is committed, so that the committed design names the models that will actually run.
