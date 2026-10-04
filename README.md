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

## Develop
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -p no:cacheprovider
```
Tests use synthetic, non-harmful strings, no network and no keys. The LangChain tests need `langchain-core` installed.
