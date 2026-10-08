# 1b_main_answers_check: human check of the UNCERTAIN final answers of the main run

Pre-registered 2026-10-08 in `gates_main_answers.md` (written before the sheet was built). Contents of this folder (no evidence content anywhere in it):

| file | what |
|---|---|
| `gates_main_answers.md` | the gates: sample, validity, agreement, readout, pre-registered use (the human-calibrated text-unsafe estimate) |
| `score_main_answers.py` | applies exactly those gates (standard library only) |
| `build_main_answers_sheet.py` | builds the sheet from the local-only evidence (reuses the template of `safelabs-trace/runner/build_check_sheet.py`) |
| `check_main_answers_sheet.py`, `sheet_checks_4.md` | the post-build checks (PASS/FAIL, counts only); `sheet_checks.md` to `_3.md` are earlier runs of the same script: the first two flagged over-broad generic words ("rules" in the guide's heading, "model", "google" in answers) and one benchmark request that mentions a framework name; the check was then narrowed to identifying words (model, framework, scorer, tagger, verdict, severity names) with the rest listed as INFO. `_3` and `_4` are identical runs. The tightened check was written after seeing those results, and `sheet_checks_4.md` is the one to cite |
| `population_main_answers.json` | counts per model from the run folders (N, FAIL/VULNERABLE, eligible UNCERTAIN, tool-call-only, provider-blocked): digest-derived counts, no text |
| `tests/` | tests of the scorer and of the sampling on SYNTHETIC files only (`tests/synthetic/`, every name and model is marked SYNTHETIC) |

The rater form and the key are NOT here: they are in `~/Desktop/Workspace/AgentSafeLabs/evidence/main_answers_sheets/` (outside every git repository, folder mode 700, files 600). `SEND_TO_RATERS.md` is in that folder.

## Scoring command (after both raters have returned their files into ~/Downloads)
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_main_answers_check
python3 score_main_answers.py --r1 ~/Downloads/rater_R1_labels_main_answers.csv --r2 ~/Downloads/rater_R2_labels_main_answers.csv
```
Defaults: key `~/Desktop/Workspace/AgentSafeLabs/evidence/main_answers_sheets/KEY_DO_NOT_SHARE_main_answers.csv`, population `population_main_answers.json` (this folder), output `results/results_main_answers.md` and `.json` (this folder; never overwritten: `_2`, `_3`, ...). The terminal shows file names, validity (VALID / VOID), the status and kappa only. The results hold ids, labels, kinds, models and counts, no answer text.
- **A void file** is never deleted by the scorer: it prints the name to rename it to (`rater_R1_labels_main_answers_VOID1.csv`); rename it by hand, then score a new valid file.
- The scorer refuses (writes nothing) on a missing file, a missing / duplicate / unknown item id, a blank or invalid label, or the same file given twice.
- Do not open the key before scoring; do not adjudicate disagreements (the gates forbid it).

## Tests
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_main_answers_check/tests
../../../safelabs-eval/.venv/bin/python -B -m pytest -p no:cacheprovider --basetemp=./_pytest_tmp -q .
```
(`tests/_pytest_tmp/` holds the tests' scratch output, SYNTHETIC only; it can be ignored.)

## Rebuilding
`build_main_answers_sheet.py` is create-only: it refuses if the sheet folder or the population file already exist. The sheet was built once (seed 20261008); do not rebuild after raters have started, because the item ids and the key would change.
