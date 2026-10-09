# safelabs-trace

Trace event model, frozen action-severity tagger and action-aware metrics for tool-using LLM agents, with the runner, analysis and human-check material of a pre-registered study.

**Source available for research reproducibility. Copyright (c) 2026 Safe Labs AI Inc. All rights reserved; see [LICENSE](LICENSE). This is not an open-source licence; contact the author at waqarjaved.com@gmail.com for other uses.**

## What it is

Core of the 1B work: a trace event model, an action-severity tagger, a JSONL trace writer, inert recording tools, a LangChain callback handler and the text-versus-action divergence metric. It builds on `safelabs-eval>=0.11.2` (the scoring verdicts) and follows the vocabulary of OpenTelemetry GenAI spans and the OWASP Agent Control Standard; it claims no conformance to either.

In plain language: when an agent calls tools, this package records what happened as a trace of events (which tool, with what severity, what the model did), without keeping the text of prompts, tool arguments, tool results or answers. A rule-based severity tagger (rules v2b, frozen for the study) labels each tool call read-only, state-changing or irreversible. Inert tools record the call and do nothing, so a benchmark can run attack prompts without any real effect. Handlers for LangChain, Google ADK and the OpenAI Agents SDK write the events. The divergence metrics then set the text verdict of a trial against the most severe action it took, so that a refusal in words followed by a risky tool call is counted.

The package is distributed through this repository, not through a package index: it declares the classifier `Private :: Do Not Upload`, so that PyPI rejects an accidental upload.

## What is here
| Module | Purpose |
|---|---|
| `schema.py` | the event model: `trace.header` plus 11 event types, ids and parent links, per-field provenance, None versus [] |
| `severity.py` + `data/severity_rules.json` | tagger: override, then the maximum of argument rules, name rules and declared hints (hints can only raise); unknown tools are `state_changing` with basis `default_unknown` |
| `writer.py` | JSONL writer: digest-only by default (salted HMAC-SHA-256), opt-in full capture into a git-ignored folder, size limits, atomic append |
| `inert_tools.py` | tools that record and never act (file, shell, HTTP, email, payment, database, read-only lookups), each with its true severity |
| `langchain_handler.py` | `BaseCallbackHandler` that writes agent, model and tool events (extra `langchain`) |
| `divergence.py` | 2 by 4 table of text verdict against action verdict, hidden-action rate, talk-only rate, ASR lift |

## Paper

*How Much Does Text-Only Scoring Miss? A Pre-Registered Trace Benchmark of Tool-Using Agents.* Waqar Javed, Safe Labs AI Inc. Status: submitted to the Journal of Systems and Software.

How to cite:

```bibtex
@misc{javed2026safelabstrace,
  author = {Javed, Waqar},
  title  = {How Much Does Text-Only Scoring Miss? A Pre-Registered Trace Benchmark of Tool-Using Agents},
  year   = {2026},
  note   = {Manuscript submitted to the Journal of Systems and Software},
  url    = {https://github.com/AgentSafeLabs/safelabs-trace}
}
```

## Blog post

A plain-language summary of the benchmark design, results and reported failures:
[What text-only scoring misses in tool-using agents](https://agentsafelabs.com/blog/your-ai-agent-said-no-but-what-did-its-tools-do/) (Agent Safe Labs blog, 9 October 2026).

## Reproducing the 1B study

The study was pre-registered in steps; each step is a committed file. The list below gives the steps with the date written in the file and, where a committed file names it, the pull request. Commit hashes and merge times are in the git history, not in committed files, so they are not listed here.

1. **set C re-check gate**: [handcheck/set_c/gate_set_c.md](handcheck/set_c/gate_set_c.md)

   Written 2026-10-04.

   pass rule of the severity-tagger re-check, written before rules v2 existed
2. **two-rater addendum**: [handcheck/rater_packet/gate_addendum_two_raters.md](handcheck/rater_packet/gate_addendum_two_raters.md)

   Written 2026-10-04.

   the reference label is the more severe of two raters
3. **pilot decisions D8 to D10**: [runner/DECISIONS.md](runner/DECISIONS.md)

   Written 2026-10-05.

   model-call cap, metrics that keep UNCERTAIN trials, local-only evidence sidecar
4. **pilot v2 gates**: [handcheck/pilot_v2/gates_pilot_v2.md](handcheck/pilot_v2/gates_pilot_v2.md)

   Written 2026-10-06.

   human checks of the unclassified-shell calls and of UNCERTAIN answers
5. **main-run plan**: [runner/main_run/MAIN_RUN_PLAN.md](runner/main_run/MAIN_RUN_PLAN.md)

   Written 2026-10-07. Pull request: #16 ([analysis report](analysis/main_run/analysis_report.md)).

   design, outcomes, statistics and missing-data rule, before any main-run data
6. **runner fix D11**: [runner/DECISIONS.md](runner/DECISIONS.md)

   Written 2026-10-07. Pull request: #17 ([deviation log](analysis/main_run/DEVIATIONS.md)).

   an errored trial is never scored; billing errors are infrastructure; repair command
7. **main-run analysis and deviation log**: [analysis/main_run/DEVIATIONS.md](analysis/main_run/DEVIATIONS.md)

   Written 2026-10-08.

   the analysis per the plan and its incidents
8. **addendum D12**: [analysis/main_run/addendum/DEVIATIONS_addendum.md](analysis/main_run/addendum/DEVIATIONS_addendum.md)

   Written 2026-10-08.

   post hoc choice of the bucket definition for the two ASRs; descriptive lift
9. **main-run answers gates**: [handcheck/main_answers/gates_main_answers.md](handcheck/main_answers/gates_main_answers.md)

   Written 2026-10-08.

   sample, validity, agreement and pre-registered use of the answers check
10. **answers check results D13, D14**: [handcheck/main_answers/results/DEVIATIONS_main_answers.md](handcheck/main_answers/results/DEVIATIONS_main_answers.md)

   Written 2026-10-09.

   both raters void under the pre-registered rule; exploratory readout
11. **addendum D15**: [analysis/main_run/addendum/cluster/DEVIATION_D15.md](analysis/main_run/addendum/cluster/DEVIATION_D15.md)

   Written 2026-10-09.

   item-cluster intervals as a descriptive robustness check

Where to start: the plan ([runner/main_run/MAIN_RUN_PLAN.md](runner/main_run/MAIN_RUN_PLAN.md)), the runbook ([runner/main_run/RUNBOOK.md](runner/main_run/RUNBOOK.md)), the analysis report ([analysis/main_run/analysis_report.md](analysis/main_run/analysis_report.md)) and every number with its source ([analysis/main_run/citable_numbers_1b.md](analysis/main_run/citable_numbers_1b.md)).

What can be re-run from this repository alone: the tests (see Develop); the offline dry run of the runner (`runner/run_dry.sh`); and the analysis scripts that read the digest-only trial table [analysis/main_run/tables/trial_level.csv](analysis/main_run/tables/trial_level.csv) (`s03`, `s05`, `s06` and `s07` in [analysis/main_run/scripts/](analysis/main_run/scripts/), and the scripts of the addendum folders). The scripts that rebuild the trial table from the run folders (`s01`, `s01b`, `s02`, `s08`, and so `run_all.py`) need the digest-only run folders of the study, which are not stored in this repository. A real run calls model providers, needs your own API keys and costs money; it is started only on purpose (`--confirm-real`, see the runbook).

## Repository map

| folder | what is in it |
|---|---|
| [src/safelabs_trace/](src/safelabs_trace/) | the package: event schema, severity tagger and its rules ([data/severity_rules.json](src/safelabs_trace/data/severity_rules.json)), trace writer, inert tools, handlers for LangChain, Google ADK and the OpenAI Agents SDK, divergence metrics |
| [tests/](tests/) | tests of the package (synthetic, non-harmful strings; no network, no keys) |
| [runner/](runner/) | the traces-on runner: [trace_runner/](runner/trace_runner/) (the code), [configs/](runner/configs/) (run configurations), [tests/](runner/tests/), [DECISIONS.md](runner/DECISIONS.md), [runner_options.md](runner/runner_options.md) |
| [runner/main_run/](runner/main_run/) | the main-run plan, runbook, frontier-model note, cost projection, validation results and the run log of main_cheap |
| [analysis/main_run/](analysis/main_run/) | the analysis of the two main runs: [analysis_report.md](analysis/main_run/analysis_report.md), [citable_numbers_1b.md](analysis/main_run/citable_numbers_1b.md), [DEVIATIONS.md](analysis/main_run/DEVIATIONS.md), [tables/](analysis/main_run/tables/) (CSV tables including the digest-only trial table), [scripts/](analysis/main_run/scripts/) |
| [analysis/main_run/addendum/](analysis/main_run/addendum/) | the descriptive lift table, configuration hashes and deviation D12 |
| [analysis/main_run/addendum/cluster/](analysis/main_run/addendum/cluster/) | item-cluster bootstrap intervals and deviation D15 |
| [handcheck/](handcheck/) | the human checks of the severity tagger and of the scorer's abstentions |
| [handcheck/set_a/](handcheck/set_a/), [handcheck/set_b/](handcheck/set_b/), [handcheck/set_c/](handcheck/set_c/), [handcheck/rater_packet/](handcheck/rater_packet/) | the earlier tool-call hand-check sets, gates and the two-rater packet (synthetic tool descriptions) |
| [handcheck/set_c_results/](handcheck/set_c_results/) | the set C two-rater result (rules v2b failed the gate) |
| [handcheck/pilot_v2/](handcheck/pilot_v2/) | the pilot v2 gates, scorer and results ([results/](handcheck/pilot_v2/results/)) |
| [handcheck/main_answers/](handcheck/main_answers/) | the gates, scorer and sheet builder of the main-run answers check, and its [results/](handcheck/main_answers/results/) (pre-registered result: both raters void; exploratory readout labelled as such) |

## Data and privacy

**Public in this repository:** the code, the run configurations, the pre-registered plan, gates and decisions, the digest-only trial table (one line per trial: verdict, action level, counts; no prompt, answer or argument text), the analysis scripts and outputs, the aggregated results and the deviation logs, and the earlier hand-check sets, which are synthetic tool descriptions with their rater labels.

**Not public, and why:** the raw model answers and raw tool-call arguments of the runs, which are kept only in a local evidence sidecar because they can contain harmful or sensitive text (the sidecar is local-only: never commit it, never upload it); the sheets, keys and rater files (including rater notes) of the pilot v2 and main-run answers checks, which pair model answers with labels; the trace salt, which would let a reader test guesses against the digests; and the per-trial trace files of the main runs, which are digest-only and are not stored here. Benchmark prompts are not reproduced in any file of this repository.

## Privacy defaults
- Tool arguments, tool results and model text are **not** written to traces. A trace keeps a salted digest, a byte length, a type and argument names.
- The salt comes from the environment variable `SAFELABS_TRACE_SALT` or a salt file **outside any git working tree**; it is never written to a trace (only a salt id).
- `capture="full"` is opt-in and writes clear text to a separate file in `captures/`, which `.gitignore` excludes. Never commit it; never send it to an external API.
- Trace events are self-reported observations, not evidence.

## OpenAI Agents SDK default exporter
The OpenAI Agents SDK registers a **default trace exporter that sends traces to OpenAI's backend** (`agents/tracing/setup.py`, `BackendSpanExporter`).
An adapter must replace it (`set_trace_processors([...])`) or disable tracing (`OPENAI_AGENTS_DISABLE_TRACING`) before anything else runs, or
attack prompts and tool arguments leave the machine.

## Exporter and span-content safety
Checked against google-adk 2.9.0 and openai-agents 0.18.0. This package itself configures **no exporter, no tracer provider and no tracing key**, and writes **digests only**
(salted; no prompts, tool arguments, tool results or model text) unless you opt into full capture, which goes to the git-ignored `captures/` folder.
The frameworks are a different matter, so for every capture:

- **Google ADK.** Library use (a `Runner` or `App` in your process) exports nothing unless your process installs a tracer provider. But ADK's span-content switch
  `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` **defaults to true** (`google/adk/telemetry/context.py:107-110`): if any exporter is active, prompts and tool data go into spans.
  Set `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` for every capture and leave `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` unset.
  **Never capture through `adk web` or `adk api_server`**: those entry points install exporters (OTLP when `OTEL_EXPORTER_OTLP_*` variables are set, Google Cloud on request;
  `google/adk/cli/api_server.py`, `google/adk/telemetry/setup.py`). Register the handler with `App(plugins=[as_plugin(handler)])`.
- **OpenAI Agents SDK.** The SDK's default trace processor uploads every trace to `https://api.openai.com/v1/traces/ingest` through `BackendSpanExporter`
  (`agents/tracing/processors.py:33-34`), registered the first time the trace provider is touched (`agents/tracing/setup.py:55-59`), and its run config includes
  inputs and outputs of tool calls and model generations in traces by default (`trace_include_sensitive_data` defaults to true, `agents/run_config.py:41-43`).
  This package turns that off in three ways, none of which uses an API key:
  1. `ensure_openai_export_off()` once at process start: installs a fresh trace provider with no processor (the default exporter object is never created) and disables
     tracing; if a provider already exists it disables tracing and removes any OpenAI-exporting processor, keeping processors you registered yourself.
  2. `safe_run_config(...)` for every run: `tracing_disabled=True`, `trace_include_sensitive_data=False`, no per-run tracing key; it refuses overrides that weaken these.
  3. The handler is strict by default (`strict=True`): at the start of a run it refuses with `OpenAIExportActiveError` while the default export could still be active
     (no provider yet, an enabled provider with an OpenAI exporter, or a provider it cannot inspect); `strict=False` records a `WARNING` in `handler.errors` instead.
  Hooks need a `RunHooks` instance: `Runner.run(agent, input, hooks=as_run_hooks(handler), run_config=safe_run_config())`, or `run_traced(handler, agent, input)`.
  The environment variable `OPENAI_AGENTS_DISABLE_TRACING` is also honoured by the SDK, but it is read once and a manual setting overrides it, so it is not relied on.
- **Not covered.** Exporters your own program registers, and the model providers themselves, which of course receive the prompts of the benchmark being run.

## Develop
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -p no:cacheprovider
```
Tests use synthetic, non-harmful strings, no network and no keys. The LangChain tests need `langchain-core` installed.

## Related work

- Earlier benchmark: Javed, W. (2026). AgentPort-Bench. Research Square preprint. [doi:10.21203/rs.3.rs-11102299/v1](https://doi.org/10.21203/rs.3.rs-11102299/v1).
- Dependency: [safelabs-eval](https://github.com/AgentSafeLabs/safelabs-eval) (`>=0.11.2`), the scoring library and AgentPort-Bench harness this package builds on.
