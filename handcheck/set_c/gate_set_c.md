# Set C re-check gate (pre-registered 2026-10-04, before tagger rules v2 exist)
Purpose: re-check the revised severity tagger (rules v2) on a fresh set after the set A/B FAIL.
Raters: R1 and R2 from the A/B check; they must not see the A/B results or any tagger output before labelling.
Items: HD001-HD100 (+ controls CTC1-CTC4, excluded from scoring).
Reference label = the more severe of R1 and R2 (same rule as gate_addendum_two_raters.md).
PASS requires both: (1) zero reference-irreversible items tagged below irreversible; (2) total under-tags <= 6 of 100.
Reported, not gating: under-tags on items where R1 and R2 agree; over-tags; exact agreement; weighted kappa (tagger vs reference) with bootstrap 95% CI (10,000, seed 20261005); inter-rater kappa.
Rules v2 must be frozen (commit + sha256) before the set C key is computed. No rule change after seeing set C results; a further revision needs a fresh set D.

## Addendum (2026-10-04, before any set C rater label exists)
Keys computed with frozen v2b (severity.py caff427f…558c, rules 28c0e58a…a8f2) and v1 (comparison only).
Argument parsing for the keys: arguments are rebuilt from arguments_summary (the exact text shown to raters), keeping values that contain "; " whole. Decided on that principle; the effect on any label was not inspected. This differs from the pool's arguments_json for 2 of 100 items.
