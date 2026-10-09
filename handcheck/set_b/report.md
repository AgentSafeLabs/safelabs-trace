# 1B hand-check set B: a fresh blind 50-item set

Everything is in `_release-staging/1b_handcheck_b/`. I labelled nothing. The items file has no source and no tagger output. Set A's key, results, labelled files and void files were not opened (I did not open `attempt1_void_note.md`: its name matches `*_void*`). Tags: VERIFIED, INFERRED, UNKNOWN.

**Before you label:** read down to "How you label". The last section is sealed (aggregate tagger counts); do not read it until you have labelled all 50.

## Order of work
1. **Modules declared first.** `modules_declared.md` (sha256 `9d8a4742b3e556c3c0bbbd6ab700d1a7716a282cd56f382d26ebd1debfe17d5f`) was written before the builder was run and before any tool definition in those modules was opened. Its content is reproduced below.
2. **Pool built, tagger not imported.** `python build_items_b.py pool` wrote `items_pool_b.csv` (79 items), sha256 `c08ed3bc2866e874cf9ad2a4669c0a9eb6ccc10c27a5358f0b36eb0071fa8b13`.
3. **Then the tagger.** `python build_items_b.py select` imported `safelabs_trace.severity` (from `1b_impl/safelabs-trace/src`), tagged the pool, selected the 50 (seed 20261004) and wrote `handcheck_b_items.csv` and `handcheck_b_key.csv` (create-only mode; nothing can be overwritten).

## Modules chosen (pre-declared; whole modules; every public tool; none picked or dropped by tagger output)
Relative to site-packages. Set A's modules (Spanner, Bigtable, Pub/Sub, bash, exit_loop, get_user_choice, load_web_page, transfer_to_agent, the semantic-kernel http, math, text, time, web-search, text-memory and sessions-python plugins, the openai-agents hosted tools) are not used again.
1. google-adk 2.9.0, function-style: `google/adk/tools/bigquery/{query_tool,metadata_tool,search_tool,data_insights_tool}.py`, `google/adk/tools/load_memory_tool.py`, `google/adk/tools/load_artifacts_tool.py`, `google/adk/tools/data_agent/data_agent_tool.py`.
2. google-adk 2.9.0, class-style: `google/adk/tools/environment/{_read_file_tool,_write_file_tool,_edit_file_tool,_execute_tool}.py`.
3. ag2 0.14.0, class-style, every file under `autogen/tools/experimental/` for messageplatform (Discord, Slack, Telegram), shell, apply_patch, duckduckgo, tavily, wikipedia, perplexity, deep_research, quick_research, google_search, tinyfish, crawl4ai.
4. crewai 1.15.2, class-style: `crewai/tools/agent_tools/{ask_question_tool,delegate_work_tool,read_file_tool,add_image_tool}.py`, `crewai/tools/memory_tools.py`, `crewai/tools/cache_tools/cache_tools.py`.
5. semantic-kernel 1.44.1, kernel functions: `semantic_kernel/core_plugins/conversation_summary_plugin.py`, `semantic_kernel/core_plugins/crew_ai/crew_ai_enterprise.py`.
6. The inert catalogue (`safelabs_trace/inert_tools.py`), new argument sets only. 7. Synthetic variant groups and obscure names, all newly written (example.com only, no credentials, no real people).
Extraction is by syntax tree (nothing was imported), with three patterns fixed in advance. Each external row's `source_citation` names package, file and line. langchain_community is not installed, so it was not used.

## Pool (79 items) and exclusions
| source | items |
|---|---|
| external | 32 (from the modules above; 12 tool classes were skipped because their name or description is not a string constant) |
| inert | 21 (nine tools with two new argument sets each, plus one three-variant `shell_exec` group) |
| synthetic | 26 (twelve items in four new argument-dependent groups, fourteen new obscure-name tools) |
Argument-dependent variant items in the pool: 15 (five groups); obscure-name items: 14.
Exclusions against set A (read from set A's `items_pool.csv` and `handcheck_items.csv` only): every (tool_name, arguments_summary) pair in set A's pool or selected 50, and the tool names of the variant groups set A used. The modules are disjoint from set A's, so the exclusion removed nothing, and a test checks that no set B pool or item pair appears in set A's pool or items and that no set B variant group uses a set A group tool.
The external pool is small: all 32 external items are in the pool and 25 were needed, so the draw among external items is nearly a census. Nothing was relaxed; the stop rule (fewer than 25 external items) was not triggered.

## Quotas (met)
- External at least 50%: met (exactly the minimum). Inert at most 40%: met (26%). At most 4 items from any one family: met.
- At least 8 argument-dependent items: 9 (three complete groups of three). At least 5 obscure names: 6.
- Design draw rule (at least 10 items with basis `default_unknown` or `name_rule`): met.
- The stratification targets set in set A's design (about 17 / 17 / 16 by tagger class, none below 12) were reached (counts are in the sealed section).
- Ids HB01 to HB50 after a shuffle with seed 20261004. The items file has only `item_id`, `tool_name`, `tool_description`, `arguments_summary`, `human_label`, `confidence`, `note`.
- Argument-dependent items by item id: {HB09, HB19, HB25}, {HB26, HB35, HB42}, {HB14, HB28, HB49}. Obscure-name items by item id: HB01, HB07, HB37, HB40, HB44, HB50.

Quality notes you should know before labelling: for several class-style external tools the argument summary is generic (`example-value`) or `(no arguments)` because the parameters could not be read from the syntax tree; label those from the name and description (the guide's rule for ambiguity applies). Parameters named like credentials carry placeholder values only.

## Files
- `labelling_guide.md`: set A's guide unchanged, with one new first line, `Set B` (a test checks this). Its text still names set A's files (`handcheck_items.csv`, HC ids, `handcheck_key.csv`); for set B read them as `handcheck_b_items.csv`, HB ids and `handcheck_b_key.csv`.
- `score.py`: a copy of set A's scorer. Changes: (a) the gate follows the decided `gate_decision.md` (in set A's folder; fixed 2026-10-03 before labelling): PASS needs zero human-irreversible items tagged below irreversible, and at most 3 total under-tags of 50; over-tags, exact agreement and weighted kappa with its bootstrap interval are reported but do not gate; (b) result files are named `handcheck_b_results.md` (then `_2`, `_3`); (c) options are `--max-irreversible-under` (default 0) and `--max-under-tags` (default 3), and the status label defaults to DECIDED. Change (a) is more than a default or a path: set A's scorer counted "other disagreements", which is not what the decided gate says, so leaving it would have produced a wrong verdict. Everything else (confusion matrix, kappas, bootstrap, under- and over-tag tables, by-source and variant-group tables, refusal and no-overwrite behaviour) is unchanged.
- `label.py`: the terminal labeller (below). `build_items_b.py`, `modules_declared.md`, `items_pool_b.csv`, `handcheck_b_key.csv`, `tests/`.

## Tests
`tests/` has **27 tests, all passed** (`PYTHONDONTWRITEBYTECODE=1 <venv python> -m pytest -p no:cacheprovider -q --basetemp=_tmp_tests/run2 tests`; temp files in `_tmp_tests/`): 15 for the scorer (set A's tests adapted to set B names and to the decided gate: perfect agreement, all under-tagging, a mixed case against hand-computed kappa 0.636 and weighted kappa 5/7, over-tags do not gate, exactly three under-tags still pass, four fail unless the limit is raised, bootstrap determinism, by-source and variant-group tables, blank, whitespace-only and invalid labels refused with nothing written, mismatched ids refused, case-insensitive labels, results never overwritten, `--out-dir`); 5 for `label.py` on a synthetic three-item file (saves after every item, resumes at the first unlabelled item, b redoes the previous item and cannot go before the first, invalid entries are asked again, writes only the labelled file); 7 on the real set B files (blind columns and blank answers, no tagger or source text in the items file, no item or pool pair duplicates set A, no set A variant-group tool reused, `label.py` never references the key file, the guide equals set A's plus the first line, the pool file has no tagger columns). A smoke run of `score.py` on the unlabelled real files refused with "50 blank human_label" and wrote nothing; `label.py` started on the real items, showed item 1 and, with no answers, wrote no file.

## How you label
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_handcheck_b
PYTHONDONTWRITEBYTECODE=1 ~/Desktop/Workspace/AgentSafeLabs/safelabs-eval/.venv/bin/python label.py
```
It shows "Item k of 50" and "Back: type b to redo the previous item", then asks for the label (`r` = read_only, `s` = state_changing, `i` = irreversible), the confidence (`1`, `2`, `3`) and an optional note, and saves to `handcheck_b_items_labelled.csv` after every item. Stop any time with Ctrl-C; run it again to resume at the first unlabelled item. `b` works at the label prompt only (a note may legitimately be "b"). It reads only `handcheck_b_items.csv` and the labelled file; it never opens the key. Read `labelling_guide.md` first. Do not open `handcheck_b_key.csv` until all 50 are labelled.
Score when finished:
```bash
PYTHONDONTWRITEBYTECODE=1 ~/Desktop/Workspace/AgentSafeLabs/safelabs-eval/.venv/bin/python score.py handcheck_b_items_labelled.csv handcheck_b_key.csv
```

## Rules I bent
- I listed set A's folder (file names only, which include the void files) and read only the allowed files: `gate_decision.md`, `score.py`, `labelling_guide.md`, `items_pool.csv`, `handcheck_items.csv` (the last two also inside the tests). I did not read set A's `build_items.py` or `label.py` this time (I wrote the builder logic again from the earlier work), and did not open its key, results, labelled or void files.
- I saw set B's items (names, descriptions, arguments) and aggregate key statistics; I did not read key rows and wrote nothing from the key into any labelling file.
- `label.py` replaces its own labelled file atomically through a `.part` file when you run it (an `os.replace` at run time, not something I ran on real answers).
- Read-only inspection one-liners and the generation of `score.py` and the guide copy used the system `python3`; the builder, the scorer, the labeller and all tests used the venv python. `sha256sum` was used for the module-declaration hash.
- No `rm`, `rmdir`, `mv`, `unlink` or `chmod`; no git or gh command; no network; no install; no `.env` or `Credential.txt`; no API-key variable read or changed; nothing written outside `_release-staging/1b_handcheck_b/` and nothing in the repo.

---

## SPOILER: read only after you have labelled all 50
Final 50 by source and tagger class (aggregate counts; no item-level labels):
| source | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| inert | 4 | 0 | 9 | 13 |
| external | 13 | 8 | 4 | 25 |
| synthetic | 0 | 9 | 3 | 12 |
| total | 17 | 17 | 16 | 50 |
