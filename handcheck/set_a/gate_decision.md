# 1B severity hand-check: gate decision (fixed before labelling)
Date: 2026-10-03. Decided before any human label was entered; key not opened.
PASS requires both:
1. Zero items labelled irreversible by the human are tagged below irreversible.
2. Total under-tags (tagger less severe than human, any class) <= 3 of 50.
Reported, not gating: over-tags (expected from the unknown -> state_changing default), exact agreement, linearly weighted kappa with bootstrap 95% CI.
On FAIL: revise rules, then re-check on a fresh 50-item set (not this one).
Class definitions: labelling_guide.md as accepted by WJ on this date.
