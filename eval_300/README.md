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

Public-release redaction: the operator's name is replaced by "the operator" in the files below. SHA-256 of each file before this redaction:
  - `./specs/SCORING_SPEC_ADDENDUM_4.md`: `7cadfb902863bed56089939295974f154e5180b0323a5bfb6f2e952e88d8abac`
  - `./specs/SCORING_SPEC_ADDENDUM_5.md`: `bcc8fe5131f3f69f8b6c78998169ff9f745c6647d047b4fb506b80fd376a4c3f`
  - `./specs/SCORING_SPEC_ADDENDUM_6.md`: `d1299aedd300554826af8506b7d2d772507b826a7d2c1f5ffd916328ac459e22`
  - `./specs/SCORING_SPEC_ADDENDUM_7.md`: `0bd25dcda86e7e474eaa3fd825c4bb833d9506b2b39a1a4680b48596ad06e398`
  - `./specs/SCORING_SPEC_ADDENDUM_7c.md`: `c41a1668cd52b616ef51f6dbb6b9f040d4fb3e20c20750776c7e46eb0178c133`
  - `./specs/SCORING_SPEC_ADDENDUM_7d.md`: `73610a59e4b786107704aeabadb220f508f929c0b50c3b0c00fa76615957488a`
  - `./specs/SCORING_SPEC_ADDENDUM_7e.md`: `7dd7199096d81b78d4dc624bbfc6c26cf2a3ee144f0b6e83908acdacc231bf3f`
  - `./specs/SCORING_SPEC_ADDENDUM_7e1.md`: `4fdf4cf7c921885025d3e5d73dc815e7f4b095149422d369788a3f61fc9bfb33`
  - `./specs/SCORING_SPEC_ADDENDUM_7e2.md`: `bd87cf79de8d5ff7594d6f6e4610c3e9c9e5d0688f4205d4d7f06b31e2a41478`
  - `./specs/SCORING_SPEC_ADDENDUM_7e4.md`: `1794b53efa261dc00db842cf6e015b96ce1b3c9bfd5a384a24f39a05c6672217`
  - `./specs/SCORING_SPEC_ADDENDUM_7e5.md`: `7ee0f893f9eed2b985fe5d302e5830836497bf9f775bf98ed4e3c6e5dbd61c97`
  - `./specs/SCORING_SPEC_ADDENDUM_7e6.md`: `3b107581b76efe46a716d0e194957a760f5bba53c29ded7276d0a7c5d80a4d6c`
