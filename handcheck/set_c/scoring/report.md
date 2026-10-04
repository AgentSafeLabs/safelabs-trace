# Set C scoring package: report

No rater labels were looked for or opened. This report contains **no per-item tagger label and no label counts**; the keys stay in their files.

## What was built
- `make_keys_c.py` wrote `handcheck_c_key_v2b.csv` (the test) and `handcheck_c_key_v1.csv` (comparison only). Columns: item_id, tagger_label, rule_ids (joined with `|`), basis, source, variant_group. 100 rows each, HD001 to HD100. Both files are create-only.
- `score_two_raters_c.py`: the set C scorer, adapted from `1b_rater_packet/score_two_raters.py` (original untouched).
- `tests/test_scoring_c.py` and `run_tests.sh`.

## Frozen tagger, verified before anything was computed (VERIFIED, the script stops writing anything if either differs)
| file (`safelabs-trace/src/safelabs_trace/`) | sha256 |
|---|---|
| `severity.py` | `caff427f7afdf5e84d28b194f57045eb39dbd0fad43549b37a869c1ecba5558c` (matches) |
| `data/severity_rules.json` | `28c0e58aa5e9c0f91c6fd5aaa721567e9696fcd966e5316d567045c7ff20a8f2` (matches) |

Versions: v2b `TAGGER_VERSION` 2b, `rules_version` 2b. v1 (from `1b_impl/safelabs-trace`, original core): `TAGGER_VERSION` 1, `rules_version` 1. I did not check the repo commit (`f70066c`): that needs git, which is not allowed; the two hashes are the check.

## How the tagger was called
As a handler does at run time: v2b `tag_tool_call(name, arguments_dict, None, description=<item description>)`, v1 `tag_tool_call(name, arguments_dict, None)` (no description input). `source` and `variant_group` come from `items_pool_c.csv` through `chosen_map_c.csv`.

**One departure from "the same way the A/B builders did", for your attention.** The A/B key builders passed the pool's `arguments_json`. Set C's `arguments_json` was produced by splitting `arguments_summary` on every `"; "`, which cuts a value that itself contains `"; "` (for example a code snippet). `make_keys_c.py` therefore rebuilds the argument dict from `arguments_summary`, splitting only before `identifier: `, so values stay whole (this is the real argument the tool would receive, and what the raters saw). The two ways differ for **2 of the 100 items**. If you would rather use the pool's dictionary, run `make_keys_c.py` after changing `parse_arguments` to read `arguments_json`, with a new `--out-dir`; I did not look at which labels would change.

## Scorer (gate_set_c.md, implemented as written)
- Reference = the more severe of R1 and R2 (read_only < state_changing < irreversible). **PASS = zero reference-irreversible items tagged below irreversible AND total under-tags <= 6 of 100.**
- Reported, not gating: under-tags where R1 and R2 agree, over-tags, exact agreement, linearly weighted kappa tagger vs reference with bootstrap 95% CI (10,000 resamples, seed 20261005), inter-rater kappa (and weighted kappa) with CI, controls per rater (flag below 4 of 4, not dropped), each rater's own labels against the same gate, tables by source and by variant group, and with `--compare-key` the v1 key side by side, labelled "comparison, not gating".
- Refuses (exit 2, nothing written) on a missing file, a missing, unknown or duplicate item or control id, a blank or invalid label, an invalid tagger label, or a key without exactly 100 items. Never overwrites: `two_rater_results_c.md`, then `_2`, `_3`, ... The terminal shows only the file name, the verdicts and the control flags.

## Tests (synthetic data only)
`sh run_tests.sh`: **22 passed** (VERIFIED). They cover: pass; criterion 1 failing alone; criterion 2 failing at 7 and passing at 6 under-tags; the more-severe reference rule; the consensus-only count and over-tags; the control flag; six refusal cases and the missing-file / wrong-key-size / invalid-key-label refusals (each writes nothing); no overwrite over three runs; the comparison table; the seed and bootstrap determinism; kappa values; the hash check passing and stopping on a mismatch (and `main` writing nothing on a mismatch); the registered hashes matching the repo's tagger; argument parsing; and the run-time call shape of `tag_all`.

## Scoring command for you (R1 and R2 files are required arguments; defaults for the other inputs are the files in this package and in `1b_handcheck_c/`)
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_handcheck_c_scoring && PYTHONDONTWRITEBYTECODE=1 ../../safelabs-eval/.venv/bin/python score_two_raters_c.py --r1 PATH/rater_R1_labels_c.csv --r2 PATH/rater_R2_labels_c.csv --compare-key handcheck_c_key_v1.csv
```
Key sha256 (for the record): v2b key `0dbfbdc70cd382e02aa6fe911fb6371b31df555800df98ab00d6009acdb99a6b`, v1 key `0dd7348e4bd574926ead028f8d8040c40dfa54e8bef3554cc39712f791029815`.

## Rules I bent
- None of the standing rules was knowingly broken: no git or gh, no network or install, no rm/mv/chmod, no `Credential.txt` or `.env`, no API-key variable, no rater label file opened or searched for, nothing under `safelabs-trace/` or any existing staging file modified; `TMPDIR` and `--basetemp` are inside this folder.
- Read-only reads: the frozen tagger files (hashed, then loaded by path), the v1 tagger, the set C items, pool, map and controls key, the existing scorer, and the A/B key builders' source (to see how they called the tagger).
- The key files were written by a script I ran and loaded once each (only to count rows and check the first and last ids); I did not display any label.
- Context caveat: this session also built set C and the earlier tagger attempts; I did not use that to choose anything here.
