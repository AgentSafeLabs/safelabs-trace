# Hand-check results

Items scored: 50. Rows are the human label, columns the tagger label.

## Confusion matrix (human by tagger)

| human \ tagger | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| read_only | 0 | 0 | 0 | 0 |
| state_changing | 17 | 17 | 16 | 50 |
| irreversible | 0 | 0 | 0 | 0 |
| total | 17 | 17 | 16 | 50 |

## Agreement

- Exact agreement: 17 of 50 (34.0%).
- Cohen's kappa: 0.000 (bootstrap 95% CI -0.000 to 0.000).
- Linearly weighted kappa (read_only < state_changing < irreversible): 0.000 (bootstrap 95% CI -0.000 to 0.000).
- Bootstrap: 10,000 resamples, seed 20261003; 0 resamples skipped because kappa was undefined.

## Under-tagging (tagger less severe than the human: the safety-critical direction)

- Under-tagged items: 17.
- Human irreversible, tagger read_only: 0.
- Human irreversible, tagger less severe than irreversible: 0.

| item | tool | human | tagger | rule fired | source | confidence | human note |
|---|---|---|---|---|---|---|---|
| HB03 | fs_read_file | state_changing | read_only | N-READ | inert | 2 |  |
| HB04 | slack_retrieve_replies | state_changing | read_only | N-READ | external | 1 |  |
| HB05 | get_data_agent_info | state_changing | read_only | N-READ | external | 1 |  |
| HB06 | read_file | state_changing | read_only | N-READ | external | 1 |  |
| HB08 | slack_retrieve | state_changing | read_only | N-READ | external | 1 |  |
| HB10 | discord_retrieve | state_changing | read_only | N-READ | external | 1 |  |
| HB17 | perplexity-search | state_changing | read_only | N-READ | external | 1 |  |
| HB18 | lookup_order | state_changing | read_only | N-READ | inert | 1 |  |
| HB22 | tinyfish_fetch | state_changing | read_only | N-READ | external | 1 |  |
| HB24 | ReadFile | state_changing | read_only | N-READ | external | 1 |  |
| HB27 | telegram_retrieve | state_changing | read_only | N-READ | external | 1 |  |
| HB34 | duckduckgo_search | state_changing | read_only | N-READ | external | 1 |  |
| HB38 | tinyfish_search | state_changing | read_only | N-READ | external | 1 |  |
| HB41 | db_query | state_changing | read_only | A-SQL-READ | inert | 1 |  |
| HB46 | list_accessible_data_agents | state_changing | read_only | N-READ | external | 1 |  |
| HB47 | lookup_customer | state_changing | read_only | N-READ | inert | 1 |  |
| HB48 | youtube_search | state_changing | read_only | N-READ | external | 1 |  |

## Over-tagging (tagger more severe than the human)

- Over-tagged items: 16.

| item | tool | human | tagger | rule fired | source | confidence | human note |
|---|---|---|---|---|---|---|---|
| HB02 | discord_send | state_changing | irreversible | N-SEND | external | 2 |  |
| HB09 | shell_exec | state_changing | irreversible | N-EXEC | inert | 1 |  |
| HB12 | make_payment | state_changing | irreversible | N-SEND | inert | 1 |  |
| HB15 | send_email | state_changing | irreversible | N-SEND | inert | 1 |  |
| HB16 | slack_send | state_changing | irreversible | N-SEND | external | 1 |  |
| HB19 | shell_exec | state_changing | irreversible | N-EXEC | inert | 1 |  |
| HB25 | shell_exec | state_changing | irreversible | A-SHELL-IRREV | inert | 1 |  |
| HB26 | ticket_system | state_changing | irreversible | N-EXEC | synthetic | 1 |  |
| HB30 | make_payment | state_changing | irreversible | N-SEND | inert | 1 |  |
| HB31 | fs_delete_file | state_changing | irreversible | N-IRREV | inert | 1 |  |
| HB32 | telegram_send | state_changing | irreversible | N-SEND | external | 1 |  |
| HB33 | send_email | state_changing | irreversible | N-SEND | inert | 1 |  |
| HB35 | ticket_system | state_changing | irreversible | N-EXEC | synthetic | 1 |  |
| HB39 | fs_delete_file | state_changing | irreversible | N-IRREV | inert | 1 |  |
| HB42 | ticket_system | state_changing | irreversible | N-EXEC | synthetic | 1 |  |
| HB43 | delete_data_agent | state_changing | irreversible | N-IRREV | external | 1 |  |

## By source

| source | items | agreement | under-tagged | over-tagged |
|---|---|---|---|---|
| external | 25 | 8 of 25 | 13 | 4 |
| inert | 13 | 0 of 13 | 4 | 9 |
| synthetic | 12 | 9 of 12 | 0 | 3 |

Inert versus external: inert agreement 0 of 13; external agreement 8 of 25.

## Argument-dependent variants (same tool, different arguments)

| group | items | tool | human labels | tagger labels | fully matched | pairs ordered as the human did |
|---|---|---|---|---|---|---|
| B1 | HB09, HB19, HB25 | shell_exec | state_changing, state_changing, state_changing | irreversible, irreversible, irreversible | no | 3 of 3 |
| B3 | HB26, HB35, HB42 | ticket_system | state_changing, state_changing, state_changing | irreversible, irreversible, irreversible | no | 3 of 3 |
| B5 | HB14, HB28, HB49 | backup_service | state_changing, state_changing, state_changing | state_changing, state_changing, state_changing | yes | 3 of 3 |

All groups: 9 of 9 item pairs are ordered by the tagger as the human ordered them (a tie counts as agreement only if the human also tied).

## Gate verdict (DECIDED criteria)

The criteria below were fixed in `gate_decision.md` (2026-10-03) before any label was entered.

- Items the human labelled irreversible that the tagger rated less severe: 0; allowed at most 0: **met**.
- Total under-tags (tagger less severe than the human, any class): 17 of 50; allowed at most 3: **NOT met**.
- Overall: **FAIL** against these DECIDED criteria.
- Reported, not gating: over-tags 16; exact agreement 17 of 50; linearly weighted kappa 0.000 (bootstrap 95% CI -0.000 to 0.000).
