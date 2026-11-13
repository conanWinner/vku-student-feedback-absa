# Addendum 7e.6 to SCORING_SPEC.md and ADDENDA 1–7e.5 (ADDENDUM_7e5 SHA 7ee0f893f9eed2b985fe5d302e5830836497bf9f775bf98ed4e3c6e5dbd61c97). POST-HOC fallback for unresolved cells. Secondary analysis only.

Written 2026-11-11, about 10:45 UTC+7, **AFTER** the 7e.5 results (`results.json`, `cells_scored.csv`, `consensus_agreement.json`, written about 10:29 UTC+7) were computed and viewed by the operator and the user. This rule is therefore **post hoc**, not pre-registered. No model call is made for it. All labels remain NOT GOLD.

## User decision

the operator, 2026-11-11 about 10:39 UTC+7 (verbatim): "cái nào chưa chốt thì nên lấy nhãn cũ" — for cells that are still unresolved, use the old label.

## Rule (7e.6 fallback)

- Every cell whose 7e.5 final source is `unresolved` (72 of 3,300 cells) gets the **old label** as its final label, with source `fallback_old_label`.
- All other cells keep their 7e.5 label and source unchanged (unanimous, sol_resolved, tiebreak_resolved).
- Old label = the released label for that (sentence, aspect) in the previous release of the dataset, mapped exactly as in the pilot (`review_pilot.schema.old_label_decision`): a listed polarity (positive/negative/neutral) is used as is; an aspect not listed for that sentence is `absent`.
- If a sentence cannot be found in the old release with identical text (by collection and `id`), its unresolved cells stay `unresolved` (counted as misses) and are reported.

## Source of old labels (read-only)

- Repository `conanWinner/VKU_LAB_SENTIMENT`, branch `dev`, folder `Final/data/Final_Data/` (`train1.csv` … `train6.csv`, `validation.csv`, `test.csv`), columns `id`, `text`, `sentiment`, `aspect`. Fetched read-only over raw.githubusercontent.com (no clone, no push) into `eval_300/old_labels_7e6/Final_Data/`.
- The 8-file dataset hash (`review_pilot.corpus.dataset_hash`) is `c13e760bb2d47295b5dea3ddda4e3d1e65f15846d2afece54ec9531db69643f1`, identical to `dataset_sha256` in the pilot bundle manifest (`relabel_pilot_bundle_v3/frozen/manifest.json`). So these are exactly the "previous release" labels used in the pilot.
- Mapping: eval item `collection` `train_K_final` → `trainK.csv`, `validation_final` → `validation.csv`; `csv_id` → CSV `id`. Text must match the eval sentence exactly.

## Known bias (must be reported)

SCORING_SPEC.md already states that, for this sample, the previous release equals the human-verified reference labels (they were derived from the same review database). Filling unresolved cells with old labels therefore copies the reference into exactly the cells the pipeline could not decide, and **mechanically inflates** agreement with the human-verified labels on those cells. The 7e.6 numbers are an upper-bound style, post-hoc view of a "release with fallback" dataset, not an independent estimate.

## Reporting

- The pre-registered 7e.5 results (unresolved = no label = miss) remain the **primary** result and are always reported.
- 7e.6 results are reported next to them, clearly labelled post hoc, with the same metrics and Wilson 95% CIs, with and without policy (de_xuat suggestion) cells, plus the number of fallback cells, how many had an explicit old polarity vs implicit `absent`, and their label distribution.
- Scoring rules for 7e.5 (`score.py`), the journals, the original data, and `results.json` are not changed.

## Implementation

`apply_fallback_7e6.py` (new) imports `score.py` read-only, recomputes the 7e.5 final labels with the same code path, applies the rule above, and writes `results_7e6_fallback.json`, `cells_scored_7e6.csv`, and `final_labels_7e6.jsonl` (all 3,300 cells). Code SHA in `addendum7e6_code.sha256`.
