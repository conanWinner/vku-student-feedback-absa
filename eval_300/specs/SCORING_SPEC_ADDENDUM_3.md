# Addendum 3 to SCORING_SPEC.md (d9f76dd0…), ADDENDUM_1 (5ff85c81…), ADDENDUM_2. Written BEFORE resuming run 3.

Date: 2026-11-09, about 20:45 UTC+7. Scope: **probe budget only (pacing)**. Nothing else changes: models, returned-model
check, prompts, routing, resolution rules, metrics, Wilson CIs, policy-cell rule, caps (1270; voters ≤ 900; Sol ≤ min(300, remaining)),
no retries, no fallback, lanes/gaps/pauses and all breakers of Addendum 2.

## Why
The first resume attempt of run 3 (`run_eval2.py --live`, started ~18:32 UTC+7) used all 12 pre-resume probes while the ag/ route
returned "upstream 403" (as HTTP 503). The 6th round (~20:15 UTC+7) was healthy for both ag models (HTTP 200, returned names
`claude-opus-5-5-high` and `gemini-3.8-flash-n`, text OK), but the pre-resume budget was exhausted before a 2nd healthy round
could be taken, so the script stopped with `pre_resume_probe_budget_exhausted`. No research call was made in that attempt
(voter journal still 27 lines). The user asked to continue ("tiếp đi, thử lại").

## Change
1. The 12 probes of attempt 1 are archived read-only in `probe_log_run3_attempt1.jsonl` and kept in the report.
2. The probe budget is reset once: a fresh `probe_log_run3.jsonl` with the same limits as Addendum 2 (pre-resume max 12,
   shared total max 24, one round ≈ every 10 min, resume after 2 consecutive healthy rounds). Probes remain non-votes, outside the 1270 cap.
3. No code change: run_eval2.py, probe3.py and run_eval.py are run with the SHAs recorded in `run3_code.sha256`.
4. Resume uses the existing intent journal and content-addressed cache; the 27 journaled voter calls (14 ok, 13 http_503) are not re-sent.
5. Stop rule for this attempt: if the ag route is down persistently (budget exhausted again) or any breaker trips, stop and report; no model swap.
