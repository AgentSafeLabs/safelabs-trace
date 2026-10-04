# 1B hand-check kit: blind 50-action check of the severity tagger

PRIVATE. Everything is in `_release-staging/1b_handcheck/`. I did not label anything and did not write any label into any file. The labelling files carry no tagger output. Tags: VERIFIED (file:line or a test result), INFERRED, UNKNOWN.

**Before you label:** read only the sections down to "How you label". The last section is a spoiler (aggregate tagger counts); skip it until you are done.

## Order of work (the pool was built before the tagger saw it)
1. `python build_items.py pool` built `items_pool.csv` (128 candidates) without importing the tagger: sha256 `aeaf1152b1c8c67bbd647cdc8708cadaa592916b8d591653d15a17a729225c02`.
2. Only then `python build_items.py select` imported `safelabs_trace.severity`, tagged the pool, selected the 50 and wrote `handcheck_items.csv` and `handcheck_key.csv` (files are opened in create-only mode, so nothing could be overwritten). The tagger is `1b_impl/safelabs-trace/src/safelabs_trace/severity.py` with `data/severity_rules.json`.
3. External tools were not chosen by what the tagger matches: the modules were fixed in advance (`EXTERNAL_MODULES` list in the script) and every public tool function in them was included, then the 50 were drawn by quota. The pool file holds no tagger output.

## Pool (128 items; deterministic, seed 20261003)
| source | items | where it comes from |
|---|---|---|
| external | 77 | tool definitions shipped in the venv: google-adk 2.9.0 (Spanner, Bigtable, Pub/Sub, bash, exit_loop, get_user_choice, load_web_page, transfer_to_agent), semantic-kernel 1.44.1 core plugins (HTTP, math, text, time, web search, text memory, sessions Python), openai-agents 0.18.0 hosted tools (`agents/tool.py`). Each row's `source_citation` names package, file and line from the module's syntax tree (for example `google/adk/tools/spanner/query_tool.py:32`). Descriptions are the tools' own docstring or decorator text, cut to the first paragraph, with any sentence holding a URL dropped |
| inert | 27 | the `InertToolKit` catalogue (`safelabs_trace/inert_tools.py`), two argument sets per tool, descriptions without the trailing "(inert)" |
| synthetic | 24 | 10 argument-dependent variants of four invented tools and 14 obscure-name tools, written for this check; marked in `source_citation` |
Argument-dependent variant items in the pool: 23 in 8 groups (same tool name and description, different arguments). Obscure-name items: 14 (names with no clear verb; the description carries the meaning). All arguments are synthetic: `example.com` only, no credentials, no real people or addresses (a check in the script fails the build otherwise).
Limitations: for a few ADK admin tools (for example `create_instance`) the argument summary lists only the first positional parameters (keyword-only parameters were not read); the Spanner `execute_sql` description says "Read-Only", which contradicts the update and delete variants, so the guide tells you to follow the arguments when they disagree with the description.

## The 50 (quotas met)
- Source quotas: inert 9 of 50 (limit 40%), external 30 of 50 (at least 50%), synthetic the rest.
- At least 8 argument-dependent items: 13. At least 5 obscure names: 7. At most 4 items from any one source file or tool family: 4.
- Design draw rule (`design.md` section E6, protocol item 2): at least 10 items where the tagger's basis is `default_unknown` or `name_rule`: met (40).
- Class targets (about 17 / 17 / 16) were reached exactly, and no class is below 12.
- Ids HC01 to HC50 were assigned after a shuffle with seed 20261003. `handcheck_items.csv` has only `item_id`, `tool_name`, `tool_description`, `arguments_summary`, `human_label`, `confidence`, `note`.
- Argument-dependent items, by item id (groups are the same tool with different arguments): {HC09, HC25, HC39}, {HC32, HC33, HC46}, {HC16, HC23, HC42}, {HC48, HC50}, {HC04, HC37}.
- Obscure-name items, by item id: HC02, HC08, HC13, HC14, HC20, HC24, HC29.

## Gate criteria
**Not decided.** `design.md` section E6, protocol item 4: "The acceptance bar is set by the author before the run (decision 8)", and no numbers are in `design.md`. The only text is a suggestion in `1b_design/report.md` decision 8: "no irreversible action under-tagged, at most 3 other disagreements; yours to set before the run". `score.py` therefore uses these as **PROPOSED criteria**: (1) at most 0 human-irreversible items rated less severe by the tagger; (2) at most 3 other disagreements. Both are options (`--max-irreversible-under`, `--max-other-disagreements`), the result file labels them PROPOSED, and you should set the bar before you label if you want a different one. Also from the design protocol: a second rater should label at least 20 items; this kit has no second-rater file (copy 20 rows from `handcheck_items.csv` for that if you want one).

## Tests
`tests/test_score.py`: **14 passed** (`PYTHONDONTWRITEBYTECODE=1 <venv python> -m pytest -p no:cacheprovider -q --basetemp=_tmp_tests/run1 tests/test_score.py`; temp files went to `_tmp_tests/` inside this folder). Covered: perfect agreement, all under-tagging, a mixed case checked against hand-computed kappa (0.636) and weighted kappa (5/7), over-tagging with the gate options, bootstrap determinism and undefined resamples, by-source and variant-group tables, blank label refused (nothing written), whitespace-only label refused, invalid label refused, mismatched ids refused, case-insensitive labels accepted, results files never overwritten (`handcheck_results.md`, then `_2`, `_3`), `--out-dir`. All data in the tests is synthetic; no filled copy of the real items file exists. A smoke run of `score.py` on the unlabelled real files refused with "50 blank human_label" (exit code 2) and wrote nothing.

## How you label
1. Read `labelling_guide.md` (one page; definitions are PROPOSED wording because neither `design.md` nor the docstrings of `severity.py` give prose definitions).
2. Open `handcheck_items.csv` in a spreadsheet, fill `human_label` (`read_only`, `state_changing` or `irreversible`), `confidence` (1 to 3) and `note` for all 50 rows, and save as a new file `handcheck_items_labelled.csv` in this folder. Do not open `handcheck_key.csv` before you finish.
3. Score:
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_handcheck
PYTHONDONTWRITEBYTECODE=1 ~/Desktop/Workspace/AgentSafeLabs/safelabs-eval/.venv/bin/python score.py handcheck_items_labelled.csv handcheck_key.csv
```
It prints the results and writes `handcheck_results.md` (or `handcheck_results_2.md` and so on; it never overwrites). The 3 by 3 confusion matrix, exact agreement, Cohen's and linearly weighted kappa with bootstrap 95% intervals, the under-tagging list (and the count of human-irreversible items rated read_only), over-tagging, results by source, the argument-dependent groups, and the gate verdict against the PROPOSED criteria are in that file.

## Rules I bent
- The brief asks for the final 50 by source and tagger class in this report and also says not to print tagger labels in it. I included only the aggregate counts, in the spoiler section below, and no per-item label, rule or the key. Skip that section until you have labelled.
- I looked at the 50 items (names, descriptions, arguments) and at aggregate statistics from the key (class by source counts, rule-kind counts, group membership by item id). I did not read key rows, and nothing from the key is in the labelling files.
- A stray command `cp tests/test_score.py /dev/null` ran once (a no-op, nothing written).
- Read-only inspection one-liners (syntax-tree listings of the installed packages, CSV summaries) used the system `python3`; the builder, the scorer and the tests used the venv python. No bytecode or cache directory was left in this folder.
- No `rm`, `rmdir`, `mv` or `unlink`; no git or gh command; no network; no install; no `.env` or `Credential.txt` opened; no API-key variable read or changed; nothing written outside `_release-staging/1b_handcheck/`.

---

## SPOILER: read only after you have labelled all 50
Final 50 by source and tagger class (aggregate counts; no item-level labels):
| source | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| inert | 1 | 3 | 5 | 9 |
| external | 16 | 7 | 7 | 30 |
| synthetic | 0 | 7 | 4 | 11 |
| total | 17 | 17 | 16 | 50 |
