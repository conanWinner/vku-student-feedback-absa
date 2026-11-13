# Addendum 6 to SCORING_SPEC.md (d9f76dd0…) and ADDENDA 1–5 (ADDENDUM_5 SHA bcc8fe5131f3f69f8b6c78998169ff9f745c6647d047b4fb506b80fd376a4c3f). Written AFTER the Addendum 5 chain was stopped and drained, and BEFORE the parallel scheduler issued any live call. Written BEFORE any scoring.

Date: 2026-11-10, about 16:53 UTC+7. Scope: **pacing and scheduling only**. No change to models, prompts, parameters, timeouts, scoring, resolution rules, or the Addendum 5 retry policy. All model outputs remain NOT GOLD.

## Why
At the user's explicit request (Le Duc, 2026-11-10, about 16:48 UTC+7), chosen from options: "Chạy song song làn cx/xai với ag." This authorizes running the cx and xai lanes in parallel with the ag lane.

The user did **not** approve reducing the ag gap, increasing ag concurrency, or shortening timeouts. Ag pacing stays exactly as in Addenda 2–5: at most one ag call in flight, the same start gap (20 s), the same +10/−5 gap tuning (cap 60 s, floor 10 s), and the same 503 pause + re-probe. Timeouts are unchanged.

This decision was made after seeing only progress and failure **counts** (how many retries had finished, and that cx/xai work was waiting behind ag). No label outcomes, no agreement scores, and no comparison against the human reference were inspected.

**Scoring has not been run yet.** Confirmed at the time this addendum was written: `eval_300/results.json` and `cells_scored.csv` do not exist; `paper_method/methods_multiagent.tex` still contains `\PLACEHOLDER{}` for the 300-sentence blind evaluation.

## Pre-switch journal (after SIGTERM of the Addendum 5 chain)

`chain_eval.py` PID 674066 and `retry_failed.py` PID 674070 were sent SIGTERM at about 16:53 UTC+7 and exited within ~10 s. Journals were then consistent: **0 unmatched intents** (0 orphans) on voters, Sol, and t4.

Addendum 5 voter-retry progress at stop: 42 retry calls issued (32 ok, 10 ReadTimeout), all 14 cx/gpt-6-luna failures recovered on attempt 2. Remaining issuable work, after Addendum 5 settlement gating:

| Lane | Ready now | Breakdown |
|---|---:|---|
| ag | 222 | 39 Gemini voter retries, 13 Sonnet voter retries, 85+85 first-attempt Gemini/Sonnet |
| cx | 13 | 2 Sol retries on the **current** body hash, 11 first-attempt Sol for newly settled non-unanimous items |
| xai | 19 | 3 t4 retries still needed, 16 first-attempt t4 |

Settled items (all 3 voter jobs ok or retries exhausted): 168 / 300. Unique first-attempt keys still 730 voters + 128 Sol + 20 t4. Failed Sol/t4 records whose **current** cache_key is no longer in `sol_jobs()` / `t4_jobs()` after voter retries remain unused-but-logged and are not retried (17 of 19 failed Sol keys, 10 of 13 failed t4 keys). A copy of this snapshot is in `pre_parallel_snapshot.json`.

## Change
1. **Concurrency.** Up to **one in-flight call per lane** (ag, cx, xai) at the same time, so at most three research calls in flight. The previous "one non-ag slot while ag is busy" rule of Addendum 2 is lifted. Ag remains one-at-a-time with the same gap and pause rules. cx and xai are each also one-at-a-time, but they may run at the same time as each other and as ag.
2. **Journals.** Append-only, as in Addendum 5. Concurrent writers are serialized with a single lock around each intent/call append; the intent line is fsync'd **before** the call is started. Retry records keep the Addendum 5 shape (`attempt`, `retry_of`, `addendum: 5`).
3. **Sol / t4 dependency (final votes).** A Sol call for an item is issued only once that item's **final voter votes are settled**: each of the three voter jobs has a first ok attempt, or its retries are exhausted (3 non-ok attempts, including reserved orphans). Items still waiting on an ag voter retry or a first-attempt ag voter simply wait; no Sol is issued against a partial voter set. A t4 call is issued only once the item is voter-settled **and** its Sol inputs are final (Sol is not needed under the current votes, or the current-body Sol job is settled). Retry and first-attempt rules for those jobs remain Addendum 5: ok calls are never re-called; failed current-key jobs get up to 2 extra attempts; a new Sol body hash is a new first-attempt key and counts against the Sol cap; stale Sol/t4 records are unused-but-logged.
4. **Scheduler.** `run_eval2.py` and `retry_failed.py` are left unchanged. A new process, `parallel_eval.py`, takes over the rest of the run: pending voter retries, unissued first-attempt voters, Sol on settled non-unanimous items, t4 on items whose Sol inputs are final, per-lane breakers, ag pause/re-probe, and automatic completion. Status is written to `parallel_status.json` (`running` / `complete` / `stalled` / `aborted`) and events to `parallel_log.jsonl`.
5. **Breakers.** The Addenda 2–4 breakers still apply, per lane. ag still pauses and re-probes (shared probe log, budget 36 from Addendum 5). If the cx or xai breaker trips, that lane cools down 15 minutes, then resumes with a fresh window (max 8 cooldowns); this is only so the run can finish without a human restart and does not change what counts as a vote. A hard HTTP 401/403 still aborts.
6. **First-attempt caps** (unique cache_keys) are unchanged: 1270 total; voters ≤ 900; Sol ≤ min(300, remaining). Retries still do not consume an extra first-attempt slot.

## Unchanged
Voters (Addendum 4), Sol, tie-break, returned-model check, prompts (prompt SHA 74d0fd7d…), guideline v2, temperature, max_tokens, **timeouts**, ag gap/tuning/pause, resolution rules, metrics, Wilson CIs, policy-cell rule, Addendum 5 retry policy (N=2, first ok counts, append-only, unused-but-logged stale Sol/t4), endpoint allowlist, no fallback, and no use of `archive_opus_voter/`.
