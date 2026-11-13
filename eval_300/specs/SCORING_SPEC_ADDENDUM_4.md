# Addendum 4 to SCORING_SPEC.md (d9f76dd0…) and ADDENDA 1–3. Written BEFORE resuming with the new voter.

Date: 2026-11-09, about 22:35 UTC+7. Scope: **the Claude voter only**. Nothing else changes: the other two voters
(cx/gpt-6-luna, ag/gemini-3.8-flash-high), prompts (prompt SHA 74d0fd7d…), guideline v2, routing, Sol review (GPT-6.1 Sol),
tie-break (xai/grok-4.7), resolution rules, metrics, Wilson CIs, policy-cell rule, caps (1270 total; voters ≤ 900;
Sol ≤ min(300, remaining)), no retries, no fallback, lanes, gaps, pauses, probe budget and all breakers of Addenda 2–3.
All model outputs remain NOT GOLD.

## Why
At the user's explicit request (the operator, 2026-11-09 ~22:30 UTC+7), the Claude voter `ag/claude-opus-5-5-high` is replaced by
`ag/claude-sonnet-5-5-low`. Reason given: speed and rate limits on Opus high (many Antigravity 403/503 and slow calls).
To keep one model per voter, the Claude voter is re-run on **all 300 items**; no item mixes Opus and Sonnet.

## Change
1. Pre-swap probe (not a vote, outside the cap), logged in `probe_log_addendum4.jsonl`: `ag/claude-sonnet-5-5-low`,
   HTTP 200, returned model `claude-sonnet-5-5-low`, content `KET_NOI_OK`, latency 2.5 s.
2. Returned-model check for the Claude voter: required name is exactly `claude-sonnet-5-5-low`; any other name is
   `model_mismatch` and discarded (same guard as before). Health probes (probe3.py) now probe Sonnet low + Gemini.
3. Run 3 was stopped with SIGTERM at ~22:33 UTC+7; in-flight calls were drained and journaled. Journal at stop:
   461 intents / 461 calls, no duplicates, no orphans; Sol and tie-break: 0 calls issued.
4. All 95 Opus 5.5 high voter calls (88 ok, 4 http_error, 3 transport_error) and their 95 intents are moved to
   `archive_opus_voter/` (read-only, SHA256SUMS there, plus full pre-swap journal copies). They are **not used in scoring,
   Sol, or tie-break**, and they do not count against the voter cap of the active run. They are reported as an archived,
   unused partial run.
5. Kept and never re-sent: 272 cx/gpt-6-luna and 94 ag/gemini-3.8-flash-high journaled calls (366 total, including their
   non-votes). Remaining voter work: 300 Sonnet low + 206 Gemini + 28 Luna = 534 → active voter total 900 (= cap).
6. Code change is limited to the model name in `VOTERS`/`EXPECT` (run_eval.py) and `EXPECT` (probe3.py); SHAs in
   `run4_code.sha256`. Pre-change copies are in `archive_opus_voter/`.
7. The resume starts with `--skip-preprobe`, justified by the probe in (1) and the fact that the ag/ route served Gemini and
   Opus normally up to the stop; the in-run probe/pause/breaker logic of Addendum 2 is unchanged (probe budget used so far: 4/24).
8. Stop rule: if any breaker trips or the ag route fails persistently, stop and report; no further model swap without the user.
