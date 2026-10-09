# Item-cluster bootstrap intervals for the primary rates

Descriptive robustness check added after the analysis (deviation D15); point estimates are those of the committed tables, and the pre-registered Wilson intervals (copied from the committed tables) remain the reported intervals. Cluster interval: the 300 items are resampled with replacement and every trial of a sampled item (all frameworks and repeats of the group) is kept; the rate is recomputed as a ratio of sums; 10,000 resamples, seed 20261009, percentile 95% interval. ASR-type rates use decided trials (UNCERTAIN excluded) as in the committed definitions. Ratio = cluster width / Wilson width.

| metric | scope | tier | model | trials | denominator | point % | Wilson 95% (committed) | cluster 95% | width ratio |
|---|---|---|---|---|---|---|---|---|---|
| risky_action_rate_bucket_excluded (headline) | model | cheap | claude-haiku-4-5-20251001 | 2700 | 2700 | 2.15 | 1.67 to 2.77 | 0.78 to 3.78 | 2.72 |
| risky_action_rate_bucket_included (upper bound) | model | cheap | claude-haiku-4-5-20251001 | 2700 | 2700 | 2.56 | 2.02 to 3.22 | 1.11 to 4.22 | 2.60 |
| text_only_asr | model | cheap | claude-haiku-4-5-20251001 | 2700 | 1826 | 2.63 | 1.99 to 3.47 | 1.12 to 4.45 | 2.25 |
| action_aware_flag_rate_bucket_excluded | model | cheap | claude-haiku-4-5-20251001 | 2700 | 1826 | 2.63 | 1.99 to 3.47 | 1.12 to 4.45 | 2.25 |
| uncertain_share | model | cheap | claude-haiku-4-5-20251001 | 2700 | 2700 | 32.37 | 30.63 to 34.16 | 28.33 to 36.44 | 2.30 |
| risky_action_rate_bucket_excluded (headline) | model | cheap | gpt-5.4-nano | 2700 | 2700 | 5.59 | 4.79 to 6.52 | 3.52 to 7.85 | 2.50 |
| risky_action_rate_bucket_included (upper bound) | model | cheap | gpt-5.4-nano | 2700 | 2700 | 7.44 | 6.51 to 8.50 | 5.07 to 10.04 | 2.50 |
| text_only_asr | model | cheap | gpt-5.4-nano | 2700 | 1953 | 3.74 | 2.98 to 4.67 | 1.74 to 6.10 | 2.58 |
| action_aware_flag_rate_bucket_excluded | model | cheap | gpt-5.4-nano | 2700 | 1953 | 6.09 | 5.12 to 7.24 | 3.71 to 8.76 | 2.37 |
| uncertain_share | model | cheap | gpt-5.4-nano | 2700 | 2700 | 27.67 | 26.01 to 29.38 | 23.56 to 31.96 | 2.49 |
| risky_action_rate_bucket_excluded (headline) | model | cheap | gemini-3.1-flash-lite | 2700 | 2700 | 15.00 | 13.70 to 16.40 | 11.96 to 18.11 | 2.28 |
| risky_action_rate_bucket_included (upper bound) | model | cheap | gemini-3.1-flash-lite | 2700 | 2700 | 29.37 | 27.68 to 31.12 | 25.26 to 33.59 | 2.43 |
| text_only_asr | model | cheap | gemini-3.1-flash-lite | 2700 | 822 | 4.87 | 3.59 to 6.56 | 2.01 to 8.62 | 2.23 |
| action_aware_flag_rate_bucket_excluded | model | cheap | gemini-3.1-flash-lite | 2700 | 822 | 5.84 | 4.43 to 7.66 | 2.84 to 9.65 | 2.11 |
| uncertain_share | model | cheap | gemini-3.1-flash-lite | 2700 | 2700 | 69.56 | 67.79 to 71.26 | 64.74 to 74.00 | 2.67 |
| risky_action_rate_bucket_excluded (headline) | tier | cheap | ALL | 8100 | 8100 | 7.58 | 7.02 to 8.18 | 5.91 to 9.32 | 2.95 |
| risky_action_rate_bucket_included (upper bound) | tier | cheap | ALL | 8100 | 8100 | 13.12 | 12.41 to 13.88 | 11.12 to 15.22 | 2.79 |
| text_only_asr | tier | cheap | ALL | 8100 | 4601 | 3.50 | 3.01 to 4.07 | 1.81 to 5.47 | 3.44 |
| action_aware_flag_rate_bucket_excluded | tier | cheap | ALL | 8100 | 4601 | 4.67 | 4.10 to 5.32 | 2.93 to 6.71 | 3.10 |
| uncertain_share | tier | cheap | ALL | 8100 | 8100 | 43.20 | 42.12 to 44.28 | 39.85 to 46.52 | 3.09 |
| risky_action_rate_bucket_excluded (headline) | model | frontier | claude-opus-4-8 | 600 | 600 | 3.67 | 2.43 to 5.49 | 1.83 to 5.67 | 1.25 |
| risky_action_rate_bucket_included (upper bound) | model | frontier | claude-opus-4-8 | 600 | 600 | 4.50 | 3.11 to 6.47 | 2.50 to 6.67 | 1.24 |
| text_only_asr | model | frontier | claude-opus-4-8 | 600 | 382 | 2.09 | 1.06 to 4.08 | 0.74 to 3.89 | 1.05 |
| action_aware_flag_rate_bucket_excluded | model | frontier | claude-opus-4-8 | 600 | 382 | 3.66 | 2.20 to 6.06 | 1.71 to 5.99 | 1.11 |
| uncertain_share | model | frontier | claude-opus-4-8 | 600 | 600 | 36.33 | 32.58 to 40.26 | 31.83 to 41.00 | 1.19 |
| risky_action_rate_bucket_excluded (headline) | model | frontier | gpt-5.5 | 600 | 600 | 1.00 | 0.46 to 2.16 | 0.17 to 2.00 | 1.08 |
| risky_action_rate_bucket_included (upper bound) | model | frontier | gpt-5.5 | 600 | 600 | 1.67 | 0.91 to 3.04 | 0.50 to 3.00 | 1.17 |
| text_only_asr | model | frontier | gpt-5.5 | 600 | 465 | 0.86 | 0.34 to 2.19 | 0.00 to 2.03 | 1.09 |
| action_aware_flag_rate_bucket_excluded | model | frontier | gpt-5.5 | 600 | 465 | 1.51 | 0.73 to 3.07 | 0.39 to 3.02 | 1.12 |
| uncertain_share | model | frontier | gpt-5.5 | 600 | 600 | 22.50 | 19.34 to 26.01 | 18.17 to 26.83 | 1.30 |
| risky_action_rate_bucket_excluded (headline) | model | frontier | gemini-3.5-flash | 600 | 600 | 4.33 | 2.97 to 6.27 | 2.50 to 6.33 | 1.16 |
| risky_action_rate_bucket_included (upper bound) | model | frontier | gemini-3.5-flash | 600 | 600 | 5.83 | 4.22 to 8.00 | 3.67 to 8.17 | 1.19 |
| text_only_asr | model | frontier | gemini-3.5-flash | 600 | 394 | 5.58 | 3.72 to 8.31 | 2.94 to 8.63 | 1.24 |
| action_aware_flag_rate_bucket_excluded | model | frontier | gemini-3.5-flash | 600 | 394 | 6.35 | 4.33 to 9.20 | 3.61 to 9.54 | 1.22 |
| uncertain_share | model | frontier | gemini-3.5-flash | 600 | 600 | 34.33 | 30.64 to 38.22 | 29.67 to 39.17 | 1.25 |
| risky_action_rate_bucket_excluded (headline) | tier | frontier | ALL | 1800 | 1800 | 3.00 | 2.31 to 3.89 | 2.06 to 4.06 | 1.26 |
| risky_action_rate_bucket_included (upper bound) | tier | frontier | ALL | 1800 | 1800 | 4.00 | 3.19 to 5.01 | 2.89 to 5.17 | 1.25 |
| text_only_asr | tier | frontier | ALL | 1800 | 1241 | 2.74 | 1.97 to 3.80 | 1.50 to 4.17 | 1.45 |
| action_aware_flag_rate_bucket_excluded | tier | frontier | ALL | 1800 | 1241 | 3.71 | 2.79 to 4.91 | 2.35 to 5.30 | 1.39 |
| uncertain_share | tier | frontier | ALL | 1800 | 1800 | 31.06 | 28.96 to 33.23 | 27.78 to 34.39 | 1.55 |
