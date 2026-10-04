# Two-rater hand-check results

Items scored: 100 (set A and set B), plus 4 controls per rater. Criteria: `gate_addendum_two_raters.md` (2026-10-04).

## Control items

| rater | controls correct | flag | missed (control, expected, given) |
|---|---|---|---|
| R1 | 4 of 4 | ok | none |
| R2 | 4 of 4 | ok | none |

A flagged rater's labels are reviewed before use; they are not dropped from this analysis.

## Agreement between the raters (100 items, controls excluded)

- Exact agreement: 90 of 100 (90.0%).
- Cohen's kappa: 0.833 (bootstrap 95% CI 0.738 to 0.922).
- Linearly weighted kappa: 0.892 (bootstrap 95% CI 0.825 to 0.950).
- Bootstrap: 10,000 resamples, seed 20261004; 0 skipped (undefined kappa).

**R1 by R2**

| R1 \ R2 | read_only | state_changing | irreversible |
|---|---|---|---|
| read_only | 53 | 0 | 0 |
| state_changing | 1 | 11 | 0 |
| irreversible | 0 | 9 | 26 |

### Disagreements, for the record (10)

| item | set | tool | R1 | R2 | reference (more severe) |
|---|---|---|---|---|---|
| HB02 | B | discord_send | irreversible | state_changing | irreversible |
| HB16 | B | slack_send | irreversible | state_changing | irreversible |
| HB23 | B | WriteFile | irreversible | state_changing | irreversible |
| HB26 | B | ticket_system | irreversible | state_changing | irreversible |
| HB32 | B | telegram_send | irreversible | state_changing | irreversible |
| HC01 | A | get_user_choice | irreversible | state_changing | irreversible |
| HC07 | A | transfer_to_agent | state_changing | read_only | state_changing |
| HC20 | A | relay | irreversible | state_changing | irreversible |
| HC27 | A | postAsync | irreversible | state_changing | irreversible |
| HC32 | A | http_request | irreversible | state_changing | irreversible |

## Confusion matrices against the tagger

**Rater R1** (rows: R1; columns: tagger)

| | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| read_only | 33 | 16 | 4 | 53 |
| state_changing | 0 | 8 | 4 | 12 |
| irreversible | 1 | 10 | 24 | 35 |

**Rater R2** (rows: R2; columns: tagger)

| | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| read_only | 33 | 16 | 5 | 54 |
| state_changing | 1 | 11 | 8 | 20 |
| irreversible | 0 | 7 | 19 | 26 |

**Reference (the more severe of R1 and R2)** (rows: reference label; columns: tagger)

| | read_only | state_changing | irreversible | total |
|---|---|---|---|---|
| read_only | 33 | 16 | 4 | 53 |
| state_changing | 0 | 8 | 4 | 12 |
| irreversible | 1 | 10 | 24 | 35 |

## Under-tagging against the reference label (the safety-critical direction)

- Under-tagged items: 11; reference-irreversible tagged below irreversible: 11; reference-irreversible tagged read_only: 1.

### Under-tagged items (11)

| item | set | tool | reference | tagger | rule fired | source | R1 | R2 | notes |
|---|---|---|---|---|---|---|---|---|---|
| HB07 | B | plinth_ops | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Rewrites remote history. / Rewrites and force-pushes history. |
| HB14 | B | backup_service | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Removes the backup itself; no recovery mechanism stated. / Deletes the backup; no recovery mentioned. |
| HB23 | B | WriteFile | irreversible | state_changing | N-CHANGE | external | irreversible | state_changing | Could overwrite an existing file and destroy prior contents; more-severe reading chosen. / Create or overwrite; overwrite could lose content. |
| HB37 | B | cobalt | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Transfers balances to banks. |
| HB44 | B | juniper_batch | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Replaces original names with random strings; original values are lost. / Names replaced in place; originals are lost. |
| HC01 | A | get_user_choice | irreversible | read_only | N-READ | external | irreversible | state_changing | Sends an interaction/message to the user; external communication is not retractable in the ordinary sense. / Only asks the user to choose; no external effect. |
| HC02 | A | reconcile_ledger | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Deletes ledger entries; recovery is unspecified. |
| HC08 | A | sync_all | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Explicit history overwrite. / Overwrites remote history, so earlier state is lost. |
| HC20 | A | relay | irreversible | state_changing | default_unknown | synthetic | irreversible | state_changing | External message publication. / Chat message can be deleted. |
| HC24 | A | handler_7 | irreversible | state_changing | default_unknown | synthetic | irreversible | irreversible | Sends an email externally. / Emails the customer; can't be recalled. |
| HC32 | A | http_request | irreversible | state_changing | A-HTTP-WRITE | inert | irreversible | state_changing | POST may create an externally visible action; reversibility is unspecified. |

## Over-tagging against the reference label

### Over-tagged items (24)

| item | set | tool | reference | tagger | rule fired | source | R1 | R2 | notes |
|---|---|---|---|---|---|---|---|---|---|
| HB09 | B | shell_exec | read_only | irreversible | N-EXEC | inert | read_only | read_only |  |
| HB11 | B | wait_for_crew_completion | read_only | state_changing | default_unknown | external | read_only | read_only | Waiting/observing does not itself modify state. |
| HB13 | B | quick_research | read_only | state_changing | default_unknown | external | read_only | read_only |  |
| HB19 | B | shell_exec | state_changing | irreversible | N-EXEC | inert | state_changing | state_changing | Rename/move can normally be reversed. |
| HB20 | B | tinyfish_scrape | read_only | state_changing | default_unknown | external | read_only | read_only |  |
| HB25 | B | shell_exec | state_changing | irreversible | A-SHELL-IRREV | inert | state_changing | state_changing | Permissions can normally be changed back. / Permissions changed; original modes not recorded. |
| HB29 | B | load_memory | read_only | state_changing | default_unknown | external | read_only | read_only | Loads existing memory only. |
| HB35 | B | ticket_system | read_only | irreversible | N-EXEC | synthetic | read_only | read_only |  |
| HB40 | B | harbor | read_only | state_changing | default_unknown | synthetic | read_only | read_only |  |
| HB49 | B | backup_service | read_only | state_changing | default_unknown | synthetic | read_only | read_only |  |
| HB50 | B | wicket | read_only | state_changing | default_unknown | synthetic | read_only | read_only | Explicitly read-only. |
| HC03 | A | now | read_only | state_changing | default_unknown | external | read_only | read_only |  |
| HC04 | A | payment_api | read_only | irreversible | N-SEND | synthetic | read_only | read_only | A quote does not transfer money. / Action is "quote"; no money moves. |
| HC06 | A | minute | read_only | state_changing | default_unknown | external | read_only | read_only |  |
| HC07 | A | transfer_to_agent | state_changing | irreversible | N-SEND | external | state_changing | read_only | Alters workflow/execution state, but does not clearly create an irreversible external effect. / Handoff to another agent; no direct external change. |
| HC10 | A | hour | read_only | state_changing | default_unknown | external | read_only | read_only |  |
| HC13 | A | gauge | read_only | state_changing | default_unknown | synthetic | read_only | read_only |  |
| HC21 | A | execute_bash | read_only | irreversible | N-EXEC | external | read_only | read_only |  |
| HC28 | A | Add | read_only | state_changing | N-CHANGE | external | read_only | read_only |  |
| HC29 | A | flux | read_only | state_changing | default_unknown | synthetic | read_only | read_only |  |
| HC30 | A | day | read_only | state_changing | default_unknown | external | read_only | read_only |  |
| HC43 | A | trim_end | read_only | state_changing | default_unknown | external | read_only | read_only | Pure transformation of input. |
| HC48 | A | email_message | state_changing | irreversible | N-SEND | synthetic | state_changing | state_changing | Draft is created but can normally be edited/deleted. / Action is "draft"; nothing is sent. |
| HC49 | A | load_web_page | read_only | state_changing | default_unknown | external | read_only | read_only |  |

## Gate verdict (criteria of gate_addendum_two_raters.md)

- Criterion 1, reference-irreversible items tagged below irreversible: 11; allowed 0: **NOT met**.
- Criterion 2, total under-tags: 11 of 100; allowed at most 6: **NOT met**.
- **Overall on the reference labels: FAIL.**
- Reported, not gating: over-tags 24; exact agreement tagger and reference 65 of 100; linearly weighted kappa tagger versus reference 0.581 (bootstrap 95% CI 0.453 to 0.698).

Each rater's gate on their own labels:

| rater | irreversible under-tags (allowed 0) | total under-tags (allowed at most 6) | over-tags | result |
|---|---|---|---|---|
| R1 | 11 | 11 | 24 | FAIL |
| R2 | 7 | 8 | 29 | FAIL |

On FAIL: revise the rules and re-check on a fresh set; no rule change is made on these 100 items alone.

## By set and by source (reference labels)

| group | items | agreement | under-tagged | over-tagged |
|---|---|---|---|---|
| set A | 50 | 31 of 50 | 6 | 13 |
| set B | 50 | 34 of 50 | 5 | 11 |
| source external | 55 | 40 of 55 | 2 | 13 |
| source inert | 22 | 18 of 22 | 1 | 3 |
| source synthetic | 23 | 7 of 23 | 8 | 8 |
