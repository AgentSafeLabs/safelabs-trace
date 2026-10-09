# 1b_main_answers_results

Results of the main-run answers human check (gates `handcheck/main_answers/gates_main_answers.md`, pre-registered 2026-10-08). **Pre-registered result: both raters VOID.** Everything else here is exploratory and labelled as such.

| file | what |
|---|---|
| `results_main_answers.md`, `results_main_answers.json` | the pre-registered scorer outputs, copied unchanged from `1b_main_answers_check/results/` (byte-identical): status "not scored: rater void (R1, R2)", validity per rater, missed control ids |
| `exploratory_main_answers.md`, `.json` | EXPLORATORY, not pre-registered; computed after the pre-registered validity gate failed: control table, agreement and kappa over the 120 UNCERTAIN items, agreed labels and unsafe share per model and tier, human-calibrated estimate per model and tier next to the scorer's own rate, disagreement list |
| `DEVIATIONS_main_answers.md` | entries D13 (rater files) and D14 (both raters void), dated 2026-10-09 |
| `scripts/exploratory_main_answers.py` | the exploratory computation; imports the parsing and statistics of `score_main_answers.py` without modifying it |
| `scripts/evidence_grep.py` | the evidence check: confirms that no 41-character window of a rater note or of a text column of the key appears in any output file; prints counts only |
| `sha256.txt` | hashes of every file of this folder except itself |

**Local-only inputs are not included.** The rater files (`~/Downloads/rater_R1_labels_main_answers_VOID1.csv`, `rater_R2_..._VOID1.csv`) and the key (`~/Desktop/Workspace/AgentSafeLabs/evidence/main_answers_sheets/KEY_DO_NOT_SHARE_main_answers.csv`) stay on this machine. The outputs contain counts, rates, intervals and item ids only (item id, stratum, model, tier, control type); no note, answer or prompt text.

## Re-run
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_main_answers_results
../../safelabs-eval/.venv/bin/python -B scripts/exploratory_main_answers.py            # prints the readout, writes nothing
../../safelabs-eval/.venv/bin/python -B scripts/exploratory_main_answers.py --write    # creates the two exploratory files if absent (new files only)
../../safelabs-eval/.venv/bin/python -B scripts/evidence_grep.py                      # evidence check
```
Options: `--r1`, `--r2`, `--key`, `--population`, `--scorer-dir` (default `../1b_main_answers_check`). The scorer, the gates, the thresholds and the key are not modified by any script here.
