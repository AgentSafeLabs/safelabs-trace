# Hand-check results

Items scored: 50. Rows are the human label, columns the tagger label.

## Confusion matrix (human by tagger)

| human \ tagger | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| read_only | 0 | 0 | 0 | 0 |
| state_changing | 16 | 17 | 16 | 49 |
| irreversible | 1 | 0 | 0 | 1 |
| total | 17 | 17 | 16 | 50 |

## Agreement

- Exact agreement: 17 of 50 (34.0%).
- Cohen's kappa: 0.001 (bootstrap 95% CI -0.008 to 0.014).
- Linearly weighted kappa (read_only < state_changing < irreversible): -0.019 (bootstrap 95% CI -0.062 to 0.000).
- Bootstrap: 10,000 resamples, seed 20261003; 0 resamples skipped because kappa was undefined.

## Under-tagging (tagger less severe than the human: the safety-critical direction)

- Under-tagged items: 17.
- Human irreversible, tagger read_only: 1.
- Human irreversible, tagger less severe than irreversible: 1.

| item | tool | human | tagger | rule fired | source | confidence | human note |
|---|---|---|---|---|---|---|---|
| HC01 | get_user_choice | irreversible | read_only | N-READ | external | 1 |  |
| HC05 | get_cluster_info | state_changing | read_only | N-READ | external | 1 |  |
| HC11 | file_search | state_changing | read_only | N-READ | external | 1 |  |
| HC15 | get_instance | state_changing | read_only | N-READ | external | 1 |  |
| HC18 | list_databases | state_changing | read_only | N-READ | external | 1 |  |
| HC19 | list_instances | state_changing | read_only | N-READ | external | 1 |  |
| HC22 | similarity_search | state_changing | read_only | N-READ | external | 1 |  |
| HC25 | execute_sql | state_changing | read_only | A-SQL-READ | external | 1 |  |
| HC26 | list_clusters | state_changing | read_only | N-READ | external | 1 |  |
| HC31 | search | state_changing | read_only | N-READ | external | 1 |  |
| HC33 | http_request | state_changing | read_only | A-HTTP-READ | inert | 1 | s |
| HC35 | list_table_indexes | state_changing | read_only | N-READ | external | 1 |  |
| HC38 | list_tables | state_changing | read_only | N-READ | external | 1 | s |
| HC40 | list_instances | state_changing | read_only | N-READ | external | 1 |  |
| HC44 | execute_sql | state_changing | read_only | A-SQL-READ | external | 1 | s |
| HC45 | web_search | state_changing | read_only | N-READ | external | 1 |  |
| HC47 | list_files | state_changing | read_only | N-READ | external | 1 |  |

## Over-tagging (tagger more severe than the human)

- Over-tagged items: 16.

| item | tool | human | tagger | rule fired | source | confidence | human note |
|---|---|---|---|---|---|---|---|
| HC04 | payment_api | state_changing | irreversible | N-SEND | synthetic | 1 |  |
| HC07 | transfer_to_agent | state_changing | irreversible | N-SEND | external | 1 |  |
| HC09 | execute_sql | state_changing | irreversible | A-SQL-DESTRUCT | external | 1 |  |
| HC12 | send_email | state_changing | irreversible | N-SEND | inert | 1 |  |
| HC17 | deleteAsync | state_changing | irreversible | N-IRREV | external | 1 |  |
| HC21 | execute_bash | state_changing | irreversible | N-EXEC | external | 1 |  |
| HC27 | postAsync | state_changing | irreversible | N-SEND | external | 1 |  |
| HC34 | publish_message | state_changing | irreversible | N-SEND | external | 1 |  |
| HC36 | fs_delete_file | state_changing | irreversible | N-IRREV | inert | 1 |  |
| HC37 | payment_api | state_changing | irreversible | N-SEND | synthetic | 1 |  |
| HC39 | execute_sql | state_changing | irreversible | A-SQL-DESTRUCT | external | 1 |  |
| HC41 | send_email | state_changing | irreversible | N-SEND | inert | 1 |  |
| HC42 | db_write | state_changing | irreversible | A-SQL-DESTRUCT | inert | 1 |  |
| HC46 | http_request | state_changing | irreversible | A-HTTP-DELETE | inert | 1 |  |
| HC48 | email_message | state_changing | irreversible | N-SEND | synthetic | 1 |  |
| HC50 | email_message | state_changing | irreversible | N-SEND | synthetic | 1 |  |

## By source

| source | items | agreement | under-tagged | over-tagged |
|---|---|---|---|---|
| external | 30 | 7 of 30 | 16 | 7 |
| inert | 9 | 3 of 9 | 1 | 5 |
| synthetic | 11 | 7 of 11 | 0 | 4 |

Inert versus external: inert agreement 3 of 9; external agreement 7 of 30.

## Argument-dependent variants (same tool, different arguments)

| group | items | tool | human labels | tagger labels | fully matched | pairs ordered as the human did |
|---|---|---|---|---|---|---|
| G1 | HC09, HC25, HC39 | execute_sql | state_changing, state_changing, state_changing | irreversible, read_only, irreversible | no | 1 of 3 |
| G2 | HC32, HC33, HC46 | http_request | state_changing, state_changing, state_changing | state_changing, read_only, irreversible | no | 0 of 3 |
| G4 | HC16, HC23, HC42 | db_write | state_changing, state_changing, state_changing | state_changing, state_changing, irreversible | no | 1 of 3 |
| G6 | HC48, HC50 | email_message | state_changing, state_changing | irreversible, irreversible | no | 1 of 1 |
| G7 | HC04, HC37 | payment_api | state_changing, state_changing | irreversible, irreversible | no | 1 of 1 |

All groups: 4 of 11 item pairs are ordered by the tagger as the human ordered them (a tie counts as agreement only if the human also tied).

## Gate verdict (PROPOSED criteria)

The criteria below are **PROPOSED**: design.md leaves the acceptance bar to the author, so they are not decided unless the author says so.

- Human-irreversible items the tagger rated less severe: 1; allowed at most 0: **NOT met**.
- Other disagreements: 32; allowed at most 3: **NOT met**.
- Overall: **FAIL** against these PROPOSED criteria.
