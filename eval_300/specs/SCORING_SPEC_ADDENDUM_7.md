# Addendum 7 to SCORING_SPEC.md (d9f76dd0…) and ADDENDA 1–6 (ADDENDUM_6 SHA d1299aedd300554826af8506b7d2d772507b826a7d2c1f5ffd916328ac459e22). Written AFTER the 9router ag lane of `parallel_eval.py` (PID 689743) was stopped and drained, AFTER the route-sensitivity sample was frozen, and BEFORE any local-CLI research call. Written BEFORE any scoring.

Date: 2026-11-10, about 17:22 UTC+7. Scope: **route change for the remaining ag-lane voter work only**, plus a pre-registered route-sensitivity check. No change to cx (luna voter, Sol) or xai (t4) routes, prompts, resolution rules, metrics, or the Addendum 5 retry policy. All model outputs remain NOT GOLD.

## Why
At the user's request (Đoàn Quang Thắng, 2026-11-10, about 17:14–17:15 UTC+7), the slow 9router `ag/` voter lane is moved to CLIs on the user's own computer (machineId 52202068-c358-483c-be5c-9bc0e15581f1, Linux, user `conanwinner`):
- Claude voter via Claude Code (observed 2.1.318, `/home/conanwinner/.local/bin/claude`).
- Gemini voter via `agy` (Antigravity CLI; observed 1.5.4, `/home/conanwinner/.local/bin/agy`).

The user confirmed that Claude Code can select effort **low** (`--effort low`) even though the CLI model id is `claude-sonnet-5-5` rather than the 9router alias `ag/claude-sonnet-5-5-low`. cx and xai stay on 9router on the box.

This addendum does **not** re-run all 300 sentences. Local CLIs are used only for **remaining** ag-lane work (pending voter retries under Addendum 5, and unissued first-attempt Claude/Gemini voter jobs), plus the sensitivity check below.

The decision and the sensitivity sample were made after seeing only job **counts** and already-ok **item ids**. No label outcomes, no agreement scores, and no comparison against the human reference were inspected.

**Scoring has not been run yet.** Confirmed at the time this addendum was written: `eval_300/results.json` and `cells_scored.csv` do not exist; `paper_method/methods_multiagent.tex` still contains `\PLACEHOLDER{}` for the 300-sentence eval.

## Pre-switch journal (after SIGTERM of PID 689743)

SIGTERM at about 17:20 UTC+7; the process exited at about 17:21 UTC+7 after draining in-flight calls. Journals were consistent: **0 unmatched intents**. Unique first-attempt keys: 730 voters + 136 Sol + 20 t4. Settled items: 178 / 300. Luna is complete (300 ok). Remaining **scoring** ag-lane work (212 jobs):

| requested_model | kind | next attempt | n |
|---|---|---:|---:|
| ag/claude-sonnet-5-5-low | retry | 2 | 10 |
| ag/gemini-3.8-flash-high | retry | 2 | 32 |
| ag/claude-sonnet-5-5-low | first | 1 | 85 |
| ag/gemini-3.8-flash-high | first | 1 | 85 |

Three Gemini jobs already have 3 failed 9router attempts and stay non-votes (not re-sent). A frozen copy of these counts and the sensitivity list is in `sensitivity_sample_addendum7.json` and `remote_ag/pre_cli_snapshot.json`.

## Change
1. **Route, same model intent.** Scoring job identity (`cache_key`) still uses the 9router aliases `ag/claude-sonnet-5-5-low` and `ag/gemini-3.8-flash-high` and prompt SHA `74d0fd7d…`, so retries attach to the same jobs. The actual transport is:
   - Claude: `claude -p --output-format json --model claude-sonnet-5-5 --effort low --system-prompt-file system_prompt.txt --tools "" --disable-slash-commands --permission-mode default`. The prompt argument is exactly the existing user message `{"sentence": "<text>"}`. `--system-prompt-file` **replaces** Claude Code's default system prompt with the frozen voter system prompt (same bytes as `review_pilot.guideline.SYSTEM_PROMPT`, SHA `74d0fd7d…`). `--bare` is **not** used, because it would ignore the user's existing OAuth/keychain login. `--dangerously-skip-permissions` is not used.
   - Gemini: `agy -p --output-format json --model gemini-3.8-flash-high --sandbox --disable-slash-commands --print-timeout 180s`. `agy` has **no** `--system-prompt` flag, so the frozen system prompt bytes are prepended to the user message (`SYSTEM_PROMPT + "\n\n" + {"sentence": "..."}`). `--effort` is not passed (the 9router high setting is already in the model id `gemini-3.8-flash-high`). `--dangerously-skip-permissions` is not used.
2. **CLI extra context.** Even with `--system-prompt-file` / in-message system text, the CLIs may still inject their own agent wrapper, session, or environment context (often several thousand tokens). That is a documented route difference versus 9router. Temperature 0 and `max_tokens` 2000 are request parameters on 9router and are **not** settable on these CLI invocations; CLI defaults apply. Wall-clock timeout is 180 s (agy `--print-timeout 180s`; Claude via the runner's subprocess timeout).
3. **Returned-model check.**
   - Claude Code: a vote is valid only if the JSON `modelUsage` key is exactly `claude-sonnet-5-5` (this is a known id difference from the 9router returned name `claude-sonnet-5-5-low`). Any other key is `model_mismatch` (non-vote).
   - `agy`: record whatever model id the JSON reports (`model` / `usage.model`, etc.). If the JSON does not report a model, record the requested `--model gemini-3.8-flash-high` flag as the evidence (`returned_model_source: cli_model_flag`) and do not treat a missing field as a mismatch. A reported id that is clearly not Gemini 3.8 Flash high is `model_mismatch`.
4. **Journal route tag.** Each imported scoring record has `addendum: 7` and `route: "claude-code"` or `route: "agy"` (and `endpoint: "cli:…"`). 9router records are unchanged. Journals stay append-only. For scoring, Addendum 5 still applies: the **first ok** attempt for a `cache_key` counts, whether it came from 9router or a CLI; ok keys are never re-called; failed jobs get up to 2 extra attempts (attempt numbers continue from the 9router failures).
5. **Route-sensitivity check (not used for scoring cells).** Before any CLI result was seen, a sample of already-ok 9router items was frozen, seed `20261110`, streams `20261110:addendum7-route-sensitivity:claude` and `:gemini`, n=30 each, item ids only. Official lists are in `sensitivity_sample_addendum7.json` (Claude starts E124, E002, E144, …; Gemini starts E022, E070, E030, …; overlap 6 items). Each sampled item is re-run **once** (plus Addendum 5 retries only if the CLI call itself fails) through the new route for that model. Results are logged in the remote `results.jsonl` with `kind: "sensitivity"` and are **not imported** into `cache/voters_calls.jsonl` and are **not used** for cell labels, Sol/t4 routing, or metrics. The report may include route-vs-route agreement (new CLI label vs the already-ok 9router label on the same item/aspect). It must **not** compare either route to the human reference in this check.
6. **Box scheduler.** `parallel_eval.py --live --ag-from-remote` no longer issues 9router `ag/` voter calls. cx and xai continue on 9router with the Addendum 6 one-per-lane concurrency and unchanged timeouts. Sol/t4 issuance still waits until an item's voter votes are settled (Addendum 6 §3). An importer validates CLI outputs with the official `validate_annotation` schema and appends accepted records into `cache/voters_calls.jsonl`. Sync is by `CopyToBox` of `/home/conanwinner/vku_eval_local/results.jsonl` and `local_status.json` into `eval_300/remote_ag/` (every 15–20 minutes, and once when the remote worker is complete). The box process only reads those already-copied files.
7. **What is not sent to the user machine.** The job file contains item ids, cache keys, model aliases, sentences, and the frozen prompt. It does not contain `NINE_ROUTER_API_KEY`, any other secret, or a Mongo URI.

## Unchanged
cx/gpt-6-luna, Sol (cx/gpt-6.1-sol), t4 (xai/grok-4.7), their 9router endpoint and timeouts, prompt SHA `74d0fd7d…`, guideline v2, resolution rules, metrics, Wilson CIs, policy-cell rule, first-attempt caps, Addendum 5 retry policy, Addendum 6 cx/xai parallelism and ag-gap rules (the latter now unused because the box no longer issues ag 9router calls), no fallback, no use of `archive_opus_voter/`.
