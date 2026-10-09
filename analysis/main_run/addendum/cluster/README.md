# 1b_cluster_intervals

Item-cluster bootstrap intervals for the primary rates of the 1B main run, next to the pre-registered Wilson intervals (deviation D15).

| file | what |
|---|---|
| `cluster_intervals.csv`, `cluster_intervals.md` | one row per model (all frameworks) and tier and metric: point estimate, Wilson interval copied from the committed tables (with its source file, row and columns), item-cluster bootstrap interval, width ratio |
| `DEVIATION_D15.md` | the deviation entry, dated 2026-10-09 |
| `scripts/cluster_intervals.py` | the whole computation: reproduction gate, bootstrap, tables |
| `sha256.txt` | hashes of every file of this folder except itself |

Reads only committed files of `safelabs-trace/analysis/main_run/tables/` (`trial_level.csv`, `t1_primary_risky_action.csv`, `t2_primary_asr.csv`, `t3_primary_verdict_coverage.csv`). It does not read run folders, evidence, environment files or credentials; it uses numpy from the safelabs-eval virtualenv and the standard library.

## Re-run
```bash
cd ~/Desktop/Workspace/AgentSafeLabs/_release-staging/1b_cluster_intervals
../../safelabs-eval/.venv/bin/python -B scripts/cluster_intervals.py            # prints the gate result and the tables, writes nothing
../../safelabs-eval/.venv/bin/python -B scripts/cluster_intervals.py --write    # creates the output files if absent (an existing file is kept)
```
If the reproduction gate fails, the script prints the differences, writes `repro_failure.md` with `--write`, and produces nothing else. Set `SAFELABS_TRACE` to use another checkout.

## Method
Metrics: risky-action rate with the bucket excluded (headline) and included (upper bound) over trials with a known action; text-only ASR; action-aware flag rate with the bucket excluded; UNCERTAIN share over all trials. ASR-type rates use decided trials (UNCERTAIN excluded). Cluster bootstrap: the 300 items are resampled with replacement, every trial of a sampled item is kept, the rate is recomputed as a ratio of sums, 10,000 resamples, seed 20261009 (a fresh generator per group, shared by the five metrics of that group), percentile 95% interval. Width ratio = cluster width / Wilson width.
