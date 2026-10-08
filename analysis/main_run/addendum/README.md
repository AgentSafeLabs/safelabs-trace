# 1b_main_analysis_addendum

Addendum to the 1B main-run analysis: a reproduction check of the committed ASR table, a descriptive lift table, the hashes of the run configurations, and deviation entry D12.

| file | what |
|---|---|
| `scripts/compute_lift.py` | the whole computation (gate, lift, bootstrap, hashes); prints the tables |
| `lift_table.csv`, `lift_table.md` | lift (action-aware ASR minus text-only ASR) per tier and per model, both bucket definitions, paired item-cluster bootstrap, descriptive and post hoc |
| `config_hashes.md` | sha256 of the six run configs and `price_table_main.yaml` |
| `DEVIATIONS_addendum.md` | entry D12 |
| `sha256.txt` | hashes of every file of this folder except itself |

Reads only committed files of `safelabs-trace`: `analysis/main_run/tables/trial_level.csv`, `analysis/main_run/tables/t2_primary_asr.csv`, `runner/configs/*.yaml`, `runner/price_table_main.yaml`. It does not read run folders, evidence, environment files or credentials, and it uses numpy from the safelabs-eval virtualenv plus the standard library.

## Re-run
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_main_analysis_addendum
../../safelabs-eval/.venv/bin/python -B scripts/compute_lift.py
```
This prints the gate result and the tables and writes nothing. With `--write` it creates the output files next to the scripts folder if they do not exist (existing files are kept). If the gate fails, it prints the differences, writes `repro_failure.md` with `--write`, and produces nothing else. Set `SAFELABS_TRACE` to use another checkout.

## Definitions (from `analysis/main_run/scripts/m.py` and `s03_primary_secondary.py`)
A trial is decided when its action is known and its text verdict is safe or unsafe (UNCERTAIN is excluded). Text-only ASR = unsafe / decided. Action-aware ASR = (unsafe or risky) / decided, with risky = the bucket-included flag (`risky`) or the bucket-excluded flag (`risky_excl`). Primary: bucket excluded; sensitivity: bucket included. Wilson intervals use z = 1.959964.
