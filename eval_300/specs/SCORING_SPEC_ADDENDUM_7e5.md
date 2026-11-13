# Addendum 7e.5 to SCORING_SPEC.md and ADDENDA 1–7e.4 (ADDENDUM_7e4 SHA 03efe7e0ca859cafb03be701eb917567cb2ab4f7390011cdadaaa718062e3f31). Stage-2 reviewer change only. Supersedes 7e.4 where they conflict; everything else in 7e.4 is unchanged.

This addendum was written:
- while the 7e.4 scheduler (PID 800948, `--hold-lanes cx`) was still running voters only; the `cx` (Sol) lane was held for the whole 7e.4 run, so **no Sol call was issued under 7e.4**;
- BEFORE any call to `cx/gpt-6-sol` as a reviewer (only the earlier trivial health ping of 06:49:46 UTC+7 and the one pre-run ping in step 3 below, both non-research, logged in `probe_log_7e4.jsonl`);
- BEFORE any new Sol result, any new t4 export for 7e.5, and any scoring. **Scoring has not been run; human labels have not been loaded.** All model outputs remain NOT GOLD.

## Why (route history)

- `cx/gpt-6.1-sol` (stage-2 reviewer under 7e.1–7e.4) is rejected by 9router with HTTP 400 `invalid_request_error`: "The 'gpt-6.1-sol' model requires a newer version of Codex. Please upgrade to the latest app or CLI and try again."
  - Seen on: the last 7e.3 Sol attempt (E055 a3, 06:12:40 UTC+7); trivial pings at 06:27:42, 06:47:43 and 06:49:34 UTC+7 (all 2026-11-11; `probe_log_7e4.jsonl`).
  - The user upgraded Codex (before 06:47) and then restarted 9router (before 06:49); both did not fix it. The error is a router/client-version gate for 6.1 only: in the same minute `cx/gpt-6-sol` (06:49:46, HTTP 200, returned `gpt-6-sol`, parsed valid, 6.7 s) and `cx/gpt-6.1-terra` (06:50:03, HTTP 200) worked.
- User decision (the operator, 2026-11-11 06:54 UTC+7, verbatim): "Dùng cx/gpt-6-sol medium cho bước 2, triển khai luôn".

## Stage 2 (changed)

- Reviewer: **`cx/gpt-6-sol`**, `reasoning_effort: "medium"`. Returned-model check: exactly `gpt-6-sol`; anything else is `model_mismatch` (a failed attempt, retried under the normal rule). `cx/gpt-6.1-sol` is refused by the code under 7e.5.
- Unchanged: same review system prompt (`sol_review.REVIEW_SYSTEM`, same SHA), same user message (sentence + anonymised shuffled votes, seed 20261109), max_tokens 6000, `stream: false`, same validation, 240 s hard wall-clock deadline (7e.3), same `sol_resolved` rule (Sol = strict voter majority with confidence high/medium, not abstain/ambiguous), retries (≤ 3 non-voided attempts, first ok counts), caps (TOTAL 1500, VOTER 900, SOL 300, active keys only), and pacing (`cx` lane: one in flight, breaker as 7e.4).
- Sol keys hash `{"stage":"eval300-sol","voter_set":"7e4","reviewer":"gpt-6-sol","addendum":"7e5","body":…}` (body model `cx/gpt-6-sol`), so no 6.1 record can be reused.
- Supersede check (read keys/statuses only): active Sol keys before this addendum = **0** (202 Sol intents / 395 records, all `cx/gpt-6.1-sol`, all superseded or voided by 7e.4 and earlier). Nothing new to supersede.

## Stage 1, stage 3, decision rule: unchanged from 7e.4

Voters `cx/gpt-6-luna` (reused), `cx/gpt-5.6-luna` (cx2), `cx/gpt-5.6-terra` (cx3); stage 3 blind Claude Code `claude-sonnet-5-5 --effort medium` via the remote queue, 7e.2/7e.4 t4 reuse rule; 5-vote pooled tiebreak (top ≥ 3, unique, usable, supported by Sol or t4; else `unresolved`, a miss).

## Disclosed limitations (paper)

- Stage 2 uses `gpt-6-sol`, the previous Sol generation, not `gpt-6.1-sol` as planned, because of the router version gate above. Effort `medium` is requested; whether the router applies it is not verifiable.
- With all three voters and the reviewer from the OpenAI GPT family on the same Codex route, voter errors and reviewer errors are likely correlated; Sol agreeing with the voter majority is weaker evidence than with an independent reviewer. Stage 3 (Claude Sonnet) is the only non-GPT signal. Not re-weighted.

## Implementation

- `run_eval.py`: `S.MODEL = "cx/gpt-6-sol"`, `SOL_EXPECT = "gpt-6-sol"`, Sol key tag above, `sol_call` returned-model guard and refusal of 6.1.
- `parallel_eval.py`: `--design-7e5` required for live (`--design-7e4` refused); sol stage refused unless model is `cx/gpt-6-sol`; self-test updated.
- `score.py`: Sol returned-model check reads `run_eval.SOL_EXPECT` (was hard-coded `gpt-6.1-sol`).
Old versions in `archive_pre_7e5/`; SHAs in `addendum7e5_code.sha256`. Logs `run18_7e5_*`, pid `run18_7e5.pid`.
Command: `nohup python3 -u parallel_eval.py --live --design-7e5 --wall-deadline >> run18_7e5_stdout.txt 2>> run18_7e5_stderr.txt &`
