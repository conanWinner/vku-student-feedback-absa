# Addendum 7e to SCORING_SPEC.md and ADDENDA 1–7d (ADDENDUM_7d SHA 65ce12fd7a4d0a9dffce35afcedcf0ba4751ad6e36431200ae5dd6bbb9ef7667). Written after scheduler PID 735447 drained (0 orphans), BEFORE any DeepSeek scoring call, BEFORE the supersede records below were appended, and BEFORE any scoring.

Date: 2026-11-10, about 21:10 UTC+7 (Asia/Saigon). All model outputs remain NOT GOLD. **Scoring has not been run; human labels have not been loaded.**

## Decision

User decision (Le Duc, 2026-11-10 21:06 UTC+7): the Gemini voter (`ag/gemini-3.8-flash-high`) is **replaced entirely** by `oc/deepseek-v4.1-flash-free` on 9router, and all 300 sentences are rerun for the voter-3 slot. Reason: the Gemini 9router lane is slow and unreliable (repeated ReadTimeouts and 503s). At the 21:08 drain, 104 Gemini jobs were still queued after the agy route was abandoned (Addendum 7c). Gemini is **no longer a voter in the main result**. A dummy ping at about 21:04 UTC+7 returned HTTP 200, model `deepseek-v4.1-flash-free`, content OK (not a vote).

Main-result voters from this addendum on: `cx/gpt-6-luna`, `ag/claude-sonnet-5-5-low` (Claude Code on the user machine, imported; Addendum 7/7b/7c), and `oc/deepseek-v4.1-flash-free`.

## DeepSeek voter call

- Endpoint exactly `<9ROUTER_ENDPOINT>` (chat/completions). The voter system prompt (SHA `74d0fd7d…`, guideline v2), user input (sentence only), temperature 0 and max_tokens 2000 are identical to the other 9router voters. It uses the same `run_eval.voter_call` → `review_pilot.client.post_once` path, with **no reasoning-effort parameter**.
- Same parse and validity rules (`interpret`). Returned-model check: a vote counts only if the returned model is exactly `deepseek-v4.1-flash-free`; otherwise `model_mismatch`, non-vote.
- Timeout 120 s, the same as the Gemini voter (not shorter).
- Job identity `cache_key(sentence, "oc/deepseek-v4.1-flash-free", prompt_sha)`: new keys.
- Pacing: runs on the box **ag lane** in place of Gemini, unchanged:
  - one call in flight, start gap 20 s with the +10/−5 tuning, cap 60 s, floor 10 s
  - 503 pause, per-lane breaker
  - re-probe through `probe3.py` with the shared probe log/budget, now probing only `oc/deepseek-v4.1-flash-free`
- Retries (Addendum 5): at most 3 non-voided attempts per job; the first ok attempt counts. A job with 3 failed non-voided attempts is a non-vote.
- **Unavailability:** if DeepSeek is persistently unavailable (e.g. >30 min of only errors on that lane, or the breaker and re-probe budget are exhausted), the lane is stopped and reported. **No switch to another model** without a new addendum.

## Gemini voter records (superseded)

All Gemini voter call records are kept. One key-level supersede record per key is appended to `cache/voters_calls.jsonl`: 215 keys, 264 call records, including the 7b/7c voided agy attempts. Each has `status=voided`, `voided=true`, `superseded=true`, `void_scope=key` and `void_reason=voter3_replaced_by_deepseek_user_decision_2026-11-10`. Gemini keys are not in the voter job list any more, so scoring ignores them for the main result. No Gemini sensitivity analysis is run; it may be added later only as an explicitly labelled secondary analysis.

## Downstream recomputation (all 300 items)

- luna (300/300 ok) and Claude (271 ok, 29 pending on the remote runner) voter records are unchanged and reused.
- Unanimity, Sol stage 2 and stage 3 are recomputed for all 300 items from the new voter set (same rules: unanimous = 3 valid votes and all 11 aspects agree; Sol for the rest; t4 for cells still open after Sol).
- **Sol stage 2:** every existing Sol record (155 keys, 162 call records) used input that included the Gemini slot. All of them are superseded with key-level supersede records in `cache/sol_calls.jsonl`, using the same reason. To make sure a new Sol job can never collide with a superseded key, the Sol cache key now also hashes the tag `voter_set: "7e"`. That tag is part of the key only; the request body sent to Sol is unchanged in format, prompt and parameters. Sol (cx/gpt-6.1-sol, high, 240 s) reruns on the new disagreements.
- **Stage 3 (t4, cx/gpt-6.1-sol high, Addendum 7d):** the t4 call is blind (voter prompt + sentence only) and its input does not depend on the voters, so its key is `cache_key(sentence, T4, prompt_sha)`. **Reuse rule:** an existing ok 7d t4 record (29 ok so far) is reused if and only if that item still has an open cell after the recomputed stage 2. Otherwise it is unused and not scored. No t4 record is superseded. The xai t4 voids of 7d stay.
- Decision rule unchanged (5 pooled votes; top ≥3, unique, usable, supported by Sol or the 4th model). The 7d limitation (4th model = Sol) still applies.

## Call budget (hard guard, not a scoring rule)

Caps count **active unique jobs (keys)**. A key whose call records are all voided or superseded and that has no un-voided orphan intent is excluded. Retries do not add keys; they are bounded by the 3-attempt rule, so calls ≤ 3 × keys.

- New caps: **VOTER_CAP 900** (3 voters × 300), **SOL_CAP 300**, **TOTAL_CAP 1500** (900 + 300 sol + 300 t4).
- Active at 21:08: voters 571 (luna 300 + Claude 271), Sol 0, t4 29.
- Expected:
  - DeepSeek +300 (up to 900 calls with retries)
  - Claude +29
  - Sol about 240 keys (stage 2 was needed for about 80% of items before)
  - t4 about 60–80 keys
  - total ≈ 1200 active keys, under 1500

The first-attempt reservation logic is unchanged.

## Unchanged

Prompts, guideline v2, parse and validity rules, resolution rules, metrics, Wilson CIs, policy-cell rule, Addendum 5 retry policy with voided-attempt exceptions, timeouts, ag/cx pacing, no fallback between routes, no `xai` and no `agy`, no original-data changes, and no push. `NINE_ROUTER_API_KEY` stays in env and is never logged. The scheduler refuses `xai/*`, `agy` and `ag/gemini-3.8-flash-high` as voter 3.

## Implementation

`run_eval.py`: VOTERS[2], EXPECT, the caps, and the Sol key tag. `parallel_eval.py`: the `oc/` prefix is placed on the ag lane, the voter-3 constant changes, the re-probe model changes, active-key cap counting, and refusals. `probe3.py`: EXPECT includes DeepSeek. Old versions are in `archive_pre_7e/`, SHAs in `addendum7e_code.sha256`. Logs `run13_7e_*`.
