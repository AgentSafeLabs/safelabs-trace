# Config validation (offline, the runner's own loader, --estimate and --dry-run on temporary copies)

| config | items | frameworks | models | trials per cell | trials in total | cap USD | --estimate | dry run of a cut-down copy |
|---|---|---|---|---|---|---|---|---|
| smoke_openai_agents | 20 | openai_agents | 3 (cheap) | 1 | 60 | 2 | expected USD 0.19, worst case USD 0.86 | rc 0, 90 trials, evidence lines 90, verify: manifest OK |
| smoke_frontier | 20 | langchain+adk | 3 (frontier) | 1 | 120 | 8 | expected USD 2.97, worst case USD 13.34 | rc 0, 90 trials, evidence lines 90, verify: manifest OK |
| main_cheap | 300 | langchain+adk | 3 (cheap) | 3 | 5400 | 30 | expected USD 16.94, worst case USD 77.00 | rc 0, 90 trials, evidence lines 90, verify: manifest OK |
| main_cheap_with_oa | 300 | langchain+adk+openai_agents | 3 (cheap) | 3 | 8100 | 30 | expected USD 25.40, worst case USD 115.49 | rc 0, 90 trials, evidence lines 90, verify: manifest OK |
| main_frontier | 300 | langchain+adk | 3 (frontier) | 1 | 1800 | 60 | expected USD 44.49, worst case USD 200.14 | rc 0, 90 trials, evidence lines 90, verify: manifest OK |
| main_frontier_with_oa | 300 | langchain+adk+openai_agents | 3 (frontier) | 1 | 2700 | 60 | expected USD 66.74, worst case USD 300.21 | rc 0, 90 trials, evidence lines 90, verify: manifest OK |

## Totals against the USD 100 total budget (caps and the runner's INFERRED expected / worst-case estimates)

| sequence | trials | sum of caps | sum of expected | sum of worst case |
|---|---|---|---|---|
| langchain+adk only | 7,380 | 100.00 | 64.59 | 291.34 |
| with openai_agents in the main runs | 10,980 | 100.00 | 95.30 | 429.90 |
