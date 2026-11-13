# Eval-300 artifacts (model-blind 300-sentence evaluation)

Labels are NOT gold. Agreement is measured against 433 human-checked, AI-anchored reference cells; it is agreement, not accuracy.
Primary result: Addendum 7e5 (`results/results.json`). `results/results_7e6_fallback.json` is a post-hoc fallback (unresolved cells take the previous release label) and is partly circular.

Release notes for this public copy:
- Raw comment text is removed (labels only): `items_ids.json` keeps item_id/collection/csv_id, and the `sentence` column is dropped from `cells_scored*.csv`. Sentences can be joined back from `data/Final_Data` (see `scripts/rebuild_final_data.py` in the repository root) via collection + csv_id.
- The private 9router endpoint host is replaced by `<9ROUTER_ENDPOINT>` / `<9ROUTER_HOST>`. No API keys or database URIs are included. Scripts read the key from the `NINE_ROUTER_API_KEY` env var.
- Because of that redaction, files listed below differ from the frozen originals; the `*.sha256` files in `specs/` refer to the unredacted originals. Original SHA-256 of redacted files:
  - `./scripts/parallel_eval.py`: `857e4e18cda20a5fa44c5565eaa4d036c6a6f4e0d974cf34263f7d2748855823`
  - `./specs/SCORING_SPEC_ADDENDUM_7c.md`: `dc7607960ba3c94b724f872a64a0747af84e8685a906f4fd1e9933d1b6d8d7c3`
  - `./specs/SCORING_SPEC_ADDENDUM_7d.md`: `65ce12fd7a4d0a9dffce35afcedcf0ba4751ad6e36431200ae5dd6bbb9ef7667`
  - `./specs/SCORING_SPEC_ADDENDUM_7e.md`: `8545ba6bcf1397fa82a3743e4f37050164ac3bbacb052f0bd392e7dba2605097`
  - `./specs/SCORING_SPEC_ADDENDUM_7e1.md`: `3ea3cef8cfa3997c9cc436162424fa50eb770d7a617261fa821c2014c8d981c9`
  - `./specs/SCORING_SPEC_ADDENDUM_7e2.md`: `4681386cfc520793705f1a8a7d83089466f4e577d5916badb67f567ea4bff713`
  - `./specs/SCORING_SPEC_ADDENDUM_7e4.md`: `03efe7e0ca859cafb03be701eb917567cb2ab4f7390011cdadaaa718062e3f31`
- Raw run logs, caches, model raw outputs and superseded-model archives are not included.

## Operational notes (not in the paper)

The paper reports model names, not router aliases. Calls used one API proxy. The pilot, which is not used in the paper because it compared unanimous votes with the previous release and that comparison leaks the reference, used different voters and these safeguards: call caps 450 (stage 1), 150 (stage 3), and 60 (stage 4) at concurrency 2; an fsync'd intent journal before each request; a content-addressed cache; a single allow-listed endpoint with redirects refused; a stream counted only after a stop chunk and `[DONE]`. The router added about 760 hidden prompt tokens on the `cx/` route and about 3,200 on the `ag/` route. The 300-sentence spec originally capped 1,270 calls with no retries; later addenda allowed up to two retries. Superseded votes are stored as voided and are not in the primary scores (`results.json` call_status, 981 voided).

The pilot and the external UIT-VSFC / review-database checks from the earlier draft are omitted from the paper for the same leakage reason. Their counts remain in the scoring spec history, not in the manuscript.
