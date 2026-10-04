# 1B severity hand-check: gate addendum for two independent raters

Date: 2026-10-04. Written before any rater label exists (no `rater_R1_labels.csv` or `rater_R2_labels.csv` exists when this file is written, and the keys were not opened). It extends `gate_decision.md` (2026-10-03, set A's folder) from one rater and 50 items to two raters and 100 items. The author does not label. The class definitions are those of `labelling_guide.md` as accepted on 2026-10-03.

## Who labels what
- Two external raters, **R1** and **R2**, each label **all 100 items** (set A, HC01 to HC50, and set B, HB01 to HB50) plus four control items (CTL1 to CTL4), working alone and without seeing each other's answers.
- Any earlier labels on set A or set B, including the author's, are not used.

## Reference label
The reference label of an item is **the more severe of R1's and R2's labels** on the order read_only < state_changing < irreversible. This follows the guide's rule "if it could be either of two classes, pick the more severe one". It is conservative for the safety question: it can only raise the reference, so it can increase the number of under-tags and cannot hide one. Disagreements between R1 and R2 are also listed, item by item, for the record.

## Gate (on the reference labels over the 100 items)
PASS requires both:
1. Zero items whose reference label is irreversible are tagged below irreversible.
2. Total under-tags (tagger less severe than the reference label, any class) of **at most 6 of 100** (the 3-of-50 bar of `gate_decision.md`, scaled).

Reported, not gating: over-tags (expected from the unknown to state_changing default), exact agreement, and the linearly weighted kappa between tagger and reference with a bootstrap 95% interval.
Each rater's gate result is also reported separately, applying the same two criteria to that rater's own labels (so a rater who is stricter than the other is visible).

## Inter-rater agreement
Cohen's kappa and linearly weighted kappa between R1 and R2 over the 100 items (the control items are excluded), each with a bootstrap 95% confidence interval: 10,000 resamples of the items, seed 20261004. A resample with undefined kappa (no variation in either rating) is skipped and counted.

## Control items
Each rater also labels four controls with unambiguous answers. A rater who gets fewer than 4 of 4 right is **flagged**. A flagged rater's labels are **reviewed before use** (by the author, with the items and the control answers in hand); they are not silently dropped, and the results file shows the flag and the missed controls.

## On FAIL
Revise the tagger rules and re-check on a fresh item set. No rule change is made on the basis of these 100 items alone.

## Not decided here
How the author uses the item-level disagreement list beyond the record. No other criterion is added after the labels arrive.
