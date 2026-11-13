# Addendum 5 to SCORING_SPEC.md (d9f76dd0…) and ADDENDA 1–4 (ADDENDUM_4 SHA 7cadfb902863bed56089939295974f154e5180b0323a5bfb6f2e952e88d8abac). Written AFTER the first-attempt run was stopped, and BEFORE any retry call and BEFORE any scoring.

Date: 2026-11-10, about 13:58 UTC+7. Scope: **retry of already-journaled failed calls**, plus the rule for recomputing Sol / tie-break from the final voter votes. Models, prompts, first-attempt routing definitions, resolution rules, metrics, Wilson CIs, and the policy-cell rule are unchanged. All model outputs remain NOT GOLD.

## Why
At the user's explicit request (Le Duc, 2026-11-10, about 13:43 UTC+7): "cái nào cần chạy lại thì bạn cứ chạy lại nhé, không sao cả." This is treated as approval to re-call failed research calls (timeouts, incomplete_stream, transport/HTTP errors, wrong-returned-model, and any other non-ok status) so that those jobs can receive a real vote.

This decision was made after seeing **only failure counts** (status, HTTP code, and error class per model and stage). No label outcomes, no agreement scores, and no comparison against the human reference were inspected for this decision.

**Scoring has not been run yet.** Confirmed at the time this addendum was written: `eval_300/results.json` and `cells_scored.csv` do not exist; `paper_method/methods_multiagent.tex` still contains `\PLACEHOLDER{}` for the 300-sentence blind evaluation; `score.pyc` has the same timestamp as `score.py` (2026-11-09 17:38 UTC+7 / 10:38 UTC) and there is no later score output.

## Pre-retry journal (after SIGTERM of PID 664832)

The first-attempt process `python3 -u run_eval2.py --live --skip-preprobe` (PID 664832, started 13:37 UTC+7) was sent SIGTERM at about 13:56 UTC+7 and exited at about 13:57 UTC+7 after draining in-flight calls. Journals were then append-only consistent: 730/730 voter, 128/128 Sol, 20/20 t4 call/intent lines, **0 orphans**. First-attempt work still unissued at this snapshot: 170 voter jobs, 85 Sol jobs, 136 t4 jobs (Sol/t4 job sets as computed from the votes then in the journal; they will be recomputed after voter retries).

Failure counts below are **jobs** (one cache_key, first/only attempt). There were no prior retry records.

### Voters (730 issued / 646 ok / 84 failed, all 84 retryable)

| Model | ok | http_error (503) | transport_error (ReadTimeout) | schema_error (evidence_substring) | parse_error (empty_content) | failed total |
|---|---:|---:|---:|---:|---:|---:|
| cx/gpt-6-luna | 286 | 0 | 10 | 3 | 1 | 14 |
| ag/claude-sonnet-5-5-low | 191 | 3 | 21 | 0 | 0 | 24 |
| ag/gemini-3.8-flash-high | 169 | 5 | 41 | 0 | 0 | 46 |
| **sum** | **646** | **8** | **72** | **3** | **1** | **84** |

### Sol (128 issued / 109 ok / 19 failed, all 19 retryable at this snapshot)

| Model | ok | transport_error (ReadTimeout) | incomplete_stream (finish_failed) | failed total |
|---|---:|---:|---:|---:|
| cx/gpt-6.1-sol | 109 | 18 | 1 | 19 |

### Tie-break t4 (20 issued / 7 ok / 13 failed, all 13 retryable at this snapshot)

| Model | ok | http_error (503) | transport_error (ReadTimeout) | failed total |
|---|---:|---:|---:|---:|
| xai/grok-4.7 | 7 | 3 | 10 | 13 |

A copy of this snapshot (status counts only) is in `pre_retry_snapshot.json`.

## Change
1. **Retry policy.** A failed call (any non-ok status, including `transport_error`, `http_error`, `incomplete_stream`, `model_mismatch`, `schema_error`, and `parse_error`) is retried up to **N = 2 more attempts**, with the **same model**, the **same prompt / input bytes**, and the same parameters. A successful (`ok`) call is never re-called.
2. **Append-only journals.** Original failed records are never deleted or overwritten. Each retry is appended with `attempt` (2 or 3; an original record is attempt 1, even if the field is absent) and a `retry_of` object pointing at the original (`cache_key`, `status`, `error`, `ts`, `http_status`, `n_prior`). A matching `issued_retry` line is appended to the intent journal for the same `cache_key`.
3. **Which attempt counts.** For scoring and for routing, a job (cache_key) uses the **first ok attempt**. If all attempts fail, the job stays a non-vote.
4. **Retry budget.** Retries are a separate research-call budget and are **not** counted against the first-attempt caps (1270 total unique first-issue keys; voters ≤ 900; Sol ≤ min(300, remaining)). Each failed job may add at most 2 extra calls. All retry records are kept and reported in the final `call_status`. First-attempt caps continue to count unique `cache_key`s in the intent journals (retry intent lines share the original key and do not consume an extra first-attempt slot).
5. **Downstream consistency (Sol and t4 follow final voter votes).**
   - After voter retries, Sol and t4 **job identity and routing are always recomputed** from the final voter votes (the first ok attempt per voter job), using the same `sol_jobs()` / `open_cells()` / `t4_jobs()` definitions as the locked spec and addenda 1–4.
   - **Item becomes, or remains, non-unanimous** (or has fewer than 3 valid voter votes): a Sol call is required. If a Sol record already exists with the **current** body hash (`cache_key`), use its first ok attempt, or retry it if it is still non-ok and has attempts left. If no Sol call with the current body hash exists (including the case where an older Sol was issued against a different, incomplete voter set), issue a **new first-attempt** Sol call; that new key counts against the Sol first-attempt cap. The older Sol record, if any, is **unused-but-logged** and is not used for resolution or for t4 routing.
   - **Item becomes unanimous** (3 valid voter votes and all 11 aspects agree) after retries: it is not sent to a new Sol call. Its cells are **unanimous** under the spec. Any Sol already journaled for that item is **unused-but-logged** and is not used for scoring.
   - t4 is issued only for items that still have at least one open cell under the final votes and the current-body Sol. A journaled t4 call for an item that no longer needs t4 is **unused-but-logged**. Failed t4 calls are retried only while the item still needs t4. The t4 prompt itself does not depend on other models' labels (same voter prompt and cache_key as before).
6. **Sequencing (no concurrent writers).** Two processes must never share a lane or write the same journal at the same time. The first-attempt run was stopped and drained (this addendum) before any retry. Then a wrapper (`chain_eval.py`) runs, one process at a time: retry current applicable failures (`retry_failed.py`, voters first, then Sol whose current `cache_key` still matches, then t4 still needed) → resume `run_eval2.py --live --skip-preprobe` for remaining first-attempt work (which computes Sol/t4 from the votes then in the journal) → repeat until there are no first-attempt jobs left and no retryable failures, or a hard stop. `run_eval2.py` first-attempt logic is not changed. Breakers, lanes, gaps, and the ag 403/503 pause + re-probe of Addenda 2–4 still apply during both retry and resume.
7. **Probe budget (pacing only).** The shared Addendum 2/3 probe budget in `probe3.py` is raised once from 24 to 36 (a one-time +12) so the retry campaign can pause and re-probe the ag lane without resetting the existing 16-probe log. Probes remain non-votes, outside the research-call caps, with the same protocol and the same log file `probe_log_run3.jsonl`.
8. **Orphans.** An intent with no call record after drain stays reserved and is not retried (Addendum 2). This snapshot has zero orphans.
9. **Helpers.** `run_eval.voter_votes()`, `open_cells()`, and `score.py` (not executed in this step) select the first ok attempt per job and, for Sol, only a record whose `cache_key` matches the current `sol_jobs()` body. Unused Sol/t4 records remain in the journal.

## Unchanged
Voters (Addendum 4: cx/gpt-6-luna, ag/claude-sonnet-5-5-low, ag/gemini-3.8-flash-high), Sol (cx/gpt-6.1-sol), tie-break (xai/grok-4.7), returned-model check, prompts (prompt SHA 74d0fd7d…), guideline v2, temperature, max_tokens, timeouts, resolution rules (unanimous / sol_resolved / tiebreak_resolved / unresolved, including the ≥3-vote tie-break rule), metrics, Wilson CIs, policy-cell rule, first-attempt caps, endpoint allowlist, no fallback, and no use of `archive_opus_voter/`.
