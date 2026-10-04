# Set B: modules declared before any tool in them was looked at

Declared 2026-10-04, before `build_items_b.py` was run and before any tool definition in these modules was opened. Whole modules; every public tool they define is included, and none is dropped or chosen because of what the severity tagger says. Paths are relative to the venv's `site-packages`. Modules used by set A (spanner, bigtable, pubsub, exit_loop, get_user_choice, load_web_page, transfer_to_agent, bash, the semantic-kernel http, math, text, time, web-search, text-memory and sessions-python plugins, the openai-agents hosted tools) are not used again.

1. google-adk 2.9.0, function-style tools (public top-level functions with a docstring): `google/adk/tools/bigquery/query_tool.py`, `bigquery/metadata_tool.py`, `bigquery/search_tool.py`, `bigquery/data_insights_tool.py`, `google/adk/tools/load_memory_tool.py`, `google/adk/tools/load_artifacts_tool.py`, `google/adk/tools/data_agent/data_agent_tool.py`.
2. google-adk 2.9.0, class-style tools (name and description given in the class body or its constructor call): `google/adk/tools/environment/_read_file_tool.py`, `_write_file_tool.py`, `_edit_file_tool.py`, `_execute_tool.py`.
3. ag2 0.14.0 (the `autogen` package), class-style tools in every Python file under `autogen/tools/experimental/` for: `messageplatform`, `shell`, `apply_patch`, `duckduckgo`, `tavily`, `wikipedia`, `perplexity`, `deep_research`, `quick_research`, `google_search`, `tinyfish`, `crawl4ai`.
4. crewai 1.15.2, class-style tools: `crewai/tools/agent_tools/ask_question_tool.py`, `delegate_work_tool.py`, `read_file_tool.py`, `add_image_tool.py`, `crewai/tools/memory_tools.py`, `crewai/tools/cache_tools/cache_tools.py`.
5. semantic-kernel 1.44.1, kernel functions: `semantic_kernel/core_plugins/conversation_summary_plugin.py`, `semantic_kernel/core_plugins/crew_ai/crew_ai_enterprise.py`.
6. Inert catalogue: `safelabs_trace/inert_tools.py` (the `InertToolKit`), with new argument sets only.
7. Synthetic (written for this check): new argument-dependent variant groups and new obscure-name tools.

Extraction is by syntax tree, never by importing the packages, with three patterns fixed in advance: public functions with docstrings; `kernel_function` methods; classes whose `name` and `description` are string constants in the class body or in a call inside the class. A tool whose name or description is not a string constant is skipped and counted.
Stop rule: if fewer than 25 external items remain after excluding set A's pairs, the build stops and says so; the quotas are not relaxed.
