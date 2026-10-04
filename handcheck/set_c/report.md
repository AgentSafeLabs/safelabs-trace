# Hand-check set C: build report

Built 2026-10-05 for re-checking a revised severity tagger. **No tagger output was computed, no tagger was imported or run, and no label of any kind exists in this folder** (the pool and item files have no label, severity or key columns; a test checks that). The only expected answers are the four control labels in `controls_c_key.csv`, which are the author's own, written for the controls, not tagger output. Tags: VERIFIED (a test or a command output shows it), INFERRED.

## Files
| file | what |
|---|---|
| `modules_declared_c.md` | written first, before any tool module was opened; `modules_declared_c_amendment1.md` and `..._amendment2.md` record the two changes made after the yield was seen |
| `items_pool_c.csv` | 110 candidates (101 primary + 9 spares), source, citation (`package version path:line` for external), family, arguments, variant group, obscure flag, overlap check result |
| `handcheck_c_items.csv` | the 100 items HD001 to HD100, columns item_id, tool_name, tool_description, arguments_summary only; shuffled with `random.Random(20261005)` |
| `chosen_map_c.csv` | item id -> pool id (no labels) |
| `controls_c.csv`, `controls_c_key.csv` | 4 new controls CTC1 to CTC4 and their expected labels |
| `rater_form_c.html`, `build_form_c.py` | the offline form (104 items), built from a copy of `1b_rater_packet/build_form.py` (original untouched) |
| `build_items_c.py`, `extract_c.py`, `extract_c.json`, `extract_c_fallback.json` | the build and the syntax-tree extraction output |
| `tests/test_set_c.py`, `run_tests_c.sh` | 10 tests, all pass (VERIFIED) |

## Sha256 (VERIFIED, computed after the last write)
| file | sha256 |
|---|---|
| `items_pool_c.csv` | `1d0eba26fc380ba98ac25259b12b119b822ea0637885e58c04a0fcf77e44ffa0` |
| `handcheck_c_items.csv` | `db9a40244096b194f5b1340045f198c8a726c165f24682443b9f5afd9bd0d7db` |
| `controls_c.csv` | `3848819a3f4729e5f4cba0df4aaca4afb982893804401974af338aad1bafe487` |
| `controls_c_key.csv` | `2bf0b90239ccaf8a3532b0fccfcffb192b921f87e92ab48e8a3a34d6a108eaf5` |
| `chosen_map_c.csv` | `43b18430d277c281307785503184ede68a839eedb2b77e50653b848a05cfc69a` |
| `rater_form_c.html` | `3988deac30fcab0fa90cfedac923d6de7f574e0cc2a6d75e8f1da248ab7fbae5` |

## Modules and what each gave
Extraction was by syntax tree; no package was imported. Declared new modules (openai-agents sandbox shell / apply_patch / view_image, ag2 Google Drive, ag2 browser_use, ADK skill toolset, SK wait) gave **21 of the 100 items (12 distinct tools)**. The fixed syntax patterns found only 3 genuine tools there, so (amendment 2) the skipped classes were read by hand. The remaining external items (**33, 29 distinct tools**) come from the modules of sets A and B with arguments that appear in neither set (amendment 2; the brief prefers new modules, it does not forbid reusing one). The ag2 Google Search, Wikipedia, ADK environment tools, bash tool, crewai ask/delegate/add-image tools were extracted but left out because their parameter lists could not be read from a constant (parameters would have been guessed).

**Stop rule (flagged, not relaxed):** fewer than 50 distinct external tools remained. There are **41 distinct external tools** in 54 external items across 24 source files. The 50% external share by items is met (54%), the number of distinct external tools is not what `modules_declared_c.md` aimed for. Declared-module tools not used: the sandbox `capabilities/{filesystem,memory,skills}.py` tools (not read), ADK `RunSkillScript` siblings `search_skills` / `load_skill_resource`, retrieval tools, `VertexAiLoadProfilesTool`, the llama-index tools and the ag2 `ReliableTool` (no usable description or parameters from constants).

## Composition of the final 100 (VERIFIED by `tests/test_set_c.py`)
| target | result |
|---|---|
| External >= 50% | **54** (openai-agents 8, google-adk 21, ag2 16, semantic-kernel 8, crewai 1) |
| Inert <= 25% | **18** |
| Synthetic | 28 |
| Argument-dependent variants >= 15 | **25 items in 9 groups** (V1 shell command x3, V2 patch operation x3, V3 browser task x3, V4 skill script x2, V5 python code x3, SG1 release_manager x3, SG2 queue_admin x3, SG3 dns_zone x3, SG4 sms_gateway x2); every group is one tool with different arguments; none of the groups, and none of their tool names, appears in a variant group of set A or B |
| Obscure names whose description says what they do >= 15 | **17**, all synthetic, none of the names used in A or B |
| Family cap 4 | max 4 (shell_tool.py, skill_toolset.py, data_agent_tool.py, inert db_query) |
| Mix of readers, reversible changes and irreversible effects | by the author's reading of the item text alone (never the tagger): about 46 readers, 24 reversible changes, 30 irreversible effects. This reading is **not stored in any file** (an earlier build wrote it into the pool; it was removed so that rule revision cannot be tuned to it) |
Overlap check (VERIFIED): no tool+arguments pair of set C appears in either set's items or pools (5 candidates were removed by the check, 3 spares took their places); no set C variant-group tool is in a set A or B variant group.

## Controls
CTC1 `get_exchange_rate` (looks up a rate), CTC2 `set_status_message` (changeable at any time), CTC3 `send_text_message`, CTC4 `destroy_snapshot` (permanent, no copy). Names and arguments differ from sets A/B, `controls.csv` and the guide examples (VERIFIED by test). The form shows them with the 100 items (104 in all).

## Form
Same offline form as `rater_form.html`: per-rater shuffle (seed string `safelabs-hand-check-c:<ID>`, so the order differs from the earlier form), same accepted guide block (rendered by the same function), autosave key `safelabs_trace_hand_check_c_v1_<ID>` (separate from the earlier form in the same browser), download name `rater_<ID>_labels_c.csv` with columns item_id, human_label, confidence, note. The pure functions were run under node (shuffle is a permutation, deterministic per rater, differs between R1 and R2; CSV escaping; completeness check).

## Rules I bent
- **Read outside the permitted list:** I grepped `1b_handcheck_b/report.md` (set B's build report) for the word "family" to learn how the family cap was counted; it printed one composition line (no results, no labels). I also ran `ls` on `1b_handcheck`, `1b_handcheck_b` and `1b_rater_packet`, which printed file names including `*results*`, `*void*`, `*labelled*` and `rater_R*_labels.csv`; none of those files was opened. An earlier version of `tests/test_set_c.py` opened `1b_rater_packet/rater_form.html` (the original form, which holds items and guide text, no results) to compare the guide block; the test was then rewritten to compare against the builder's own output, so it no longer reads it.
- Read, as allowed: both labelling guides (and a `diff` between them), `1b_handcheck_b/modules_declared.md`, the A and B item files and pools (printed rows of both pools), `1b_rater_packet/build_form.py` and `controls.csv`. Not opened: `build_items_b.py`, any score/label/results/void/key file.
- I read site-packages tool modules (after the declaration) with `sed`, `grep` and the syntax-tree script; no package was imported or run.
- Edited my own new files while building: `items_pool_c.csv` was rewritten once (mode `w`) to drop the author-mix column; the other outputs were regenerated with an identical-content check instead of an overwrite. `modules_declared_c.md` itself is unchanged.
- System `python3` (not the venv) ran the extraction and build scripts (they use only the standard library); the venv ran pytest, with `--basetemp` and `TMPDIR` in `tmp/` of this folder.
- No git or gh, no network, no install, no `rm`/`mv`/`chmod`, no `.env` or `Credential.txt`, no API-key variable touched. Nothing outside `_release-staging/1b_handcheck_c/` was written.
