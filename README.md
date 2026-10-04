# safelabs-trace (PRIVATE)

**PRIVATE. Proprietary: all rights reserved, Safe Labs AI Inc. Do not publish.** Nothing from this repository goes to any public
repository, issue, pull request, package index or blog. The package declares the classifier `Private :: Do Not Upload` so PyPI rejects an
accidental upload. Keep the repository private and do not add an open-source licence.

Core of the 1B work: a trace event model, an action-severity tagger, a JSONL trace writer, inert recording tools, a LangChain callback
handler and the text-versus-action divergence metric. It builds on `safelabs-eval>=0.11.2` (the scoring verdicts) and follows the
vocabulary of OpenTelemetry GenAI spans and the OWASP Agent Control Standard; it claims no conformance to either.

## What is here
| Module | Purpose |
|---|---|
| `schema.py` | the event model: `trace.header` plus 11 event types, ids and parent links, per-field provenance, None versus [] |
| `severity.py` + `data/severity_rules.json` | tagger: override, then the maximum of argument rules, name rules and declared hints (hints can only raise); unknown tools are `state_changing` with basis `default_unknown` |
| `writer.py` | JSONL writer: digest-only by default (salted HMAC-SHA-256), opt-in full capture into a git-ignored folder, size limits, atomic append |
| `inert_tools.py` | tools that record and never act (file, shell, HTTP, email, payment, database, read-only lookups), each with its true severity |
| `langchain_handler.py` | `BaseCallbackHandler` that writes agent, model and tool events (extra `langchain`) |
| `divergence.py` | 2 by 4 table of text verdict against action verdict, hidden-action rate, talk-only rate, ASR lift |

## Privacy defaults
- Tool arguments, tool results and model text are **not** written to traces. A trace keeps a salted digest, a byte length, a type and argument names.
- The salt comes from the environment variable `SAFELABS_TRACE_SALT` or a salt file **outside any git working tree**; it is never written to a trace (only a salt id).
- `capture="full"` is opt-in and writes clear text to a separate file in `captures/`, which `.gitignore` excludes. Never commit it; never send it to an external API.
- Trace events are self-reported observations, not evidence.

## Warning for future adapters: OpenAI Agents SDK
The OpenAI Agents SDK registers a **default trace exporter that sends traces to OpenAI's backend** (`agents/tracing/setup.py`, `BackendSpanExporter`).
An adapter must replace it (`set_trace_processors([...])`) or disable tracing (`OPENAI_AGENTS_DISABLE_TRACING`) before anything else runs, or
attack prompts and tool arguments leave the machine. No such adapter exists yet.

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
  This section supersedes the warning above about adapters that did not yet exist: the OpenAI Agents adapter now follows it.
- **Not covered.** Exporters your own program registers, and the model providers themselves, which of course receive the prompts of the benchmark being run.

## Develop
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -p no:cacheprovider
```
Tests use synthetic, non-harmful strings, no network and no keys. The LangChain tests need `langchain-core` installed.
