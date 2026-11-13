# Addendum 7c to SCORING_SPEC.md (d9f76dd0…) and ADDENDA 1–7b (ADDENDUM_7b SHA d188e25fa15d2476d382a2f24b50602f23f71158fb65f07a7c44ec6be9b8e20c). Written BEFORE any new Gemini call on any route after the agy diagnosis, BEFORE the void records below were appended, and BEFORE any scoring.

Date: 2026-11-10, about 20:40 UTC+7 (Asia/Saigon). Scope: **route for the remaining Gemini voter work only**. No change to cx (luna, Sol), xai (t4), the Claude voter route of Addenda 7/7b (Claude Code `claude-sonnet-5-5 --effort low`, per-call empty temp cwd), prompts, resolution rules, metrics, or the Addendum 5 retry policy except as stated. All model outputs remain NOT GOLD. **Scoring has not been run.**

## Decision

User decision (the operator, 2026-11-10, about 20:35 UTC+7): the `agy` CLI route for the Gemini voter is **abandoned**. Reason (diagnostics on dummy, non-eval sentences only): `agy` cannot be made a single-shot call. Even with a no-tools workspace agent and session-only deny rules it still invoked `manage_task` and `list_resources`; in the live attempt-3 call for E085 it had earlier invoked `search_web` about 10 times looking for the UIT-VSFC dataset (a label-leak / contamination risk); 2 of 3 dummy sentences hit the 120 s print timeout. Disabling those tools would require editing the user's global `agy` config, which is out of scope.

`agy` is **never started again** for this eval (scoring or sensitivity).

## Gemini route (from this addendum on)

The Gemini voter `ag/gemini-3.8-flash-high` returns to the **original 9router route**: endpoint exactly `<9ROUTER_ENDPOINT>` (chat/completions), the same request body and parameters, prompt (SHA `74d0fd7d…`), guideline v2 and timeouts as `run_eval2.py` / `retry_failed.py` (the same `run_eval.voter_call` → `review_pilot.client.post_once` path), and the same Addendum 4/5 returned-model check: a vote counts only if the returned model name is exactly `gemini-3.8-flash-n` (as before); otherwise `model_mismatch`, non-vote.

These calls run on the **box ag lane** of the scheduler, with the existing ag pacing unchanged (one ag call in flight, start gap 20 s with the +10/−5 tuning, cap 60 s, floor 10 s; 503 pause; per-lane breakers; same timeouts). The user did **not** approve shrinking gaps or timeouts and they are not shrunk. Re-probe after an ag breaker uses the shared `probe3.py` log/budget (36) and protocol; since Claude is no longer on the 9router lane, the re-probe in this mode probes only `ag/gemini-3.8-flash-high` (one probe per round, two healthy rounds to resume). This only affects pacing, not what counts as a vote.

Remaining Gemini jobs = unissued first attempts plus Addendum 5 retries, under the cap of **3 non-voided attempts per job**. Attempt numbers are never reused (next attempt = highest attempt number used so far + 1). Gemini jobs that already have 3 non-voided failed 9router attempts stay **non-votes** and are not re-sent.

## Claude route (unchanged)

Claude voter jobs keep coming only from the user-machine Claude Code runner (`run_local.py --live --only-cli claude-code`, payload `remote_ag_payload_7c/`, `run_local.py` SHA bdf0bd24166b003424f516cf6d5cefeddd50ce3d563ad4128825c53b0f393e60, `jobs.json` SHA cda52a371e2197cb756b5c5a829e93a56e0e463991f3dd62652a65e3b052c309). The box scheduler never issues Claude over 9router, and the importer imports only Claude lines from `remote_ag/results.jsonl`; any Gemini/`agy` line there is marked excluded and never imported.

## agy attempt-3 records for E084 / E085 (void rule)

Two `agy` attempt-3 scoring records were imported into `cache/voters_calls.jsonl` as `parse_error` (print timeout after 2 min, partial, **no content, no vote**). E085 a3 is the call that used `search_web`. Rule: both are **voided** with append-only void records (`status=voided`, `void_attempt=3`, `void_reason=agy_route_abandoned_tool_use_2026-11-10`), with matching marks in `remote_ag/imported_ids.jsonl` and `remote_ag/quarantine_agy_7b.jsonl`. Voided attempts **neither count as votes nor consume the retry cap**. This decision was made before seeing any content of these records — they had none (parse_error, empty content); only their status/error/latency fields were seen. The attempt-2 voids of Addendum 7b stay. Consequence: E084 and E085 Gemini each have 1 non-voided attempt (9router a1 ReadTimeout) and get 9router attempt 4 (then 5 if needed, max 3 non-voided); E087 Gemini gets attempt 3.

## Sensitivity sample (Addendum 7 §5)

The Gemini half (30 items) is **dropped**: there is no Gemini CLI route anymore, and re-running Gemini over the same 9router route would not be a route-vs-route comparison. The Claude half (30 items, Claude Code vs 9router) is kept unchanged, not imported, not scored, and not compared to the human reference. The report must state that the sensitivity check covers Claude only.

## Implementation

`parallel_eval.py --live --ag-from-remote --gemini-9router` (Addendum 7c mode): the ag lane issues only `ag/gemini-3.8-flash-high` jobs over 9router; Claude ag jobs are left to the remote import; the importer is called with only-model `ag/claude-sonnet-5-5-low`. Void-aware planning (`usable_call_records`, `next_attempt`) is unchanged, and an in-flight or already-ok job is never re-issued. Code SHAs are in `addendum7c_code.sha256`. Logs: `run11_*`.

## Unchanged

cx/gpt-6-luna, Sol (cx/gpt-6.1-sol), t4 (xai/grok-4.7), endpoint and timeouts, prompt SHA, guideline v2, resolution rules (incl. ≥3-vote tie-break), metrics, Wilson CIs, policy-cell rule, first-attempt caps, Addendum 5 retry policy (with the 7b/7c voided-attempt exception), Addendum 6 parallelism, no fallback between routes, no use of `archive_opus_voter/`, no edits to the user's Claude/`agy` global config, no original-data changes, no push. `NINE_ROUTER_API_KEY` stays on the box and is never logged.
