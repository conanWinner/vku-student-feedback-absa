# Addendum 7d to SCORING_SPEC.md and ADDENDA 1–7c.1 (ADDENDUM_7c SHA dc7607960ba3c94b724f872a64a0747af84e8685a906f4fd1e9933d1b6d8d7c3, ADDENDUM_7c1 SHA c89be304afc40ea109eb9cc5083919d523909cfda60bfcf4a2b1b41f1f1c605e). Written BEFORE any stage-3 call with the new model, BEFORE the void records below were appended, and BEFORE any scoring.

Date: 2026-11-10, about 21:00 UTC+7 (Asia/Saigon). Scope: **stage-3 (t4, blind 4th-model tie-break) route/model only.** All model outputs remain NOT GOLD. **Scoring has not been run; human labels have not been loaded.**

## Decision

User decision (the operator, 2026-11-10, about 20:45 and 20:55 UTC+7): Grok is no longer used; the stage-3 4th model is `cx/gpt-6.1-sol` with **high** reasoning effort, over 9router.

Reason for dropping `xai/grok-4.7`: it is not available on 9router. `/v1/models` lists no `xai` model, and calls return HTTP 404 `No active credentials for provider: xai` (E120 t4 attempts 1–3; health check in `probe_log_7c_xai.jsonl`). A 9router ping of 88 chat models (2026-11-10, about 20:45 UTC+7, dummy text, non-vote, file `/workspace/ping_9router_20261110.json`) found 39/88 working, including `cx/gpt-6.1-sol`.

## Stage-3 call (from this addendum on)

- Model `cx/gpt-6.1-sol`, endpoint exactly `<9ROUTER_ENDPOINT>` (chat/completions), called **fresh and blind**.
- **Same stage-3 prompt and inputs as the xai call**. The existing t4 call was a plain voter call: the voter system prompt (SHA `74d0fd7d…`, guideline v2) plus the sentence only, with the same temperature/max_tokens as the voters. It had no Sol stage-2 output and no other votes. This is preserved unchanged. The only changes are the model/route, and adding `reasoning_effort: "high"` to the body. That is the same mechanism and value the stage-2 Sol calls use (`sol_review.REASONING_EFFORT`). As for Sol, whether the router actually applies it is not verified.
- Request timeout: the Sol call timeout (`sol_review.TIMEOUT` = 240 s) instead of the voter 120 s, because the call now runs at high effort like Sol. This only lengthens; no timeout is shortened.
- Returned-model check (Addendum 4/5 style): a t4 vote counts only if the returned model is exactly `gpt-6.1-sol`; otherwise `model_mismatch`, non-vote.
- Job identity: `cache_key(sentence, "cx/gpt-6.1-sol", prompt_sha)`. These are new keys, so no xai record can be counted for them.
- Lane: t4 now runs on the **cx lane** (the scheduler assigns lanes by model prefix), so it shares the single in-flight cx slot with luna voter retries and stage-2 Sol. Concurrency to the cx provider is unchanged (one call in flight); the separate xai lane issues nothing. cx breaker and cooldown pacing are unchanged. Records are tagged `route=9router`, `stage=t4`, `t4_model=cx/gpt-6.1-sol`, `reasoning_effort_requested=high`, `addendum=7d`.
- Ordering is unchanged: t4 is only issued for items whose voters are settled and whose Sol (if needed) is settled. It is issued only when open cells remain after stage 2, per `open_cells()`.

## Decision rule (unchanged)

The 5 votes are pooled (3 voters + Sol stage 2 + 4th model). A cell is `tiebreak_resolved` if the top label has ≥3 votes, is unique, is a usable label, and is supported by Sol or the 4th model. Otherwise it is `unresolved`, with no fallback.

## Disclosed limitation (must be reported)

The 4th voter is now the **same model as the stage-2 reviewer** (`cx/gpt-6.1-sol`). Stage 3 is therefore **not an independent model**. "Supported by Sol or the 4th model" can be the same model twice (it gets the voter prompt blind in stage 3, and it reviews the anonymised votes in stage 2). The model family also overlaps with the cx voter `cx/gpt-6-luna`. The paper/report must state this. It must also report per-stage counts, so that `tiebreak_resolved` cells can be read separately.

## xai t4 records (void rule)

All existing xai t4 call records get append-only void records in `cache/t4_calls.jsonl`. There are 49 records over 28 cache keys: 17 ok, 26 transport_error, 3 HTTP 503 and 3 HTTP 404, the 404s being E120 a1–a3. Each void record has `status=voided`, `voided=true`, `void_attempt=<attempt>` and `void_reason=grok_dropped_user_decision_2026-11-10`. No record is deleted. Grok is dropped as a model, so its ok votes are not used either. This decision was made before any of their annotation content was inspected; only status/error fields and counts were seen. Voided attempts neither count as votes nor consume the retry cap. In any case they live under the xai cache keys, which the new t4 jobs do not use.

## Retry policy and caps (unchanged)

Retries are capped at 3 non-voided attempts per t4 job (Addendum 5), and the first ok counts. TOTAL_CAP 1270, VOTER_CAP 900, SOL_CAP 300 and the existing first-attempt reservation logic are unchanged. Note: the 28 unique xai t4 keys stay counted in the unique-call total (no cap change). At about 21:00 UTC+7 the journal had voters 786, sol 153, t4 28 (total 967), with voter-first reserve 114 and sol reserve 147. That leaves about 42 new unique t4 jobs before the first-attempt guard stops t4 first attempts. If more items need t4, the excess stays `unresolved` unless a later addendum, written before any such result is seen, changes the cap.

## Unchanged

The voters (cx/gpt-6-luna; Claude via the user-machine Claude Code runner only; Gemini over 9router on the box ag lane), Sol stage 2, prompts, guideline v2, resolution rules, metrics, Wilson CIs, policy-cell rule, ag pacing, timeouts (except t4 lengthened as above), no fallback between routes, no `agy`, no `xai` calls, no original-data changes, and no push. `NINE_ROUTER_API_KEY` stays in env and is never logged.

## Implementation

`run_eval.py`: `T4 = "cx/gpt-6.1-sol"`, `EXPECT[T4] = "gpt-6.1-sol"`, `t4_call` adds `reasoning_effort` high and the 240 s timeout through a session wrapper, plus the tags. `parallel_eval.py`: the scheduler refuses to issue any `xai/` model, its self-test expects t4 on the cx lane, and the status shows addendum 7d. Old versions are in `archive_pre_7d/`, SHAs in `addendum7d_code.sha256`. Restart without `--hold-lanes xai`; logs `run12_7d_*`.
