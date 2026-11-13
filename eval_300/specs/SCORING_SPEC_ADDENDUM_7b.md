# Addendum 7b to SCORING_SPEC.md (d9f76dd0…) and ADDENDA 1–7 (ADDENDUM_7 SHA 0bd25dcda86e7e474eaa3fd825c4bb833d9506b2b39a1a4680b48596ad06e398). Written AFTER the user-machine CLI runner (PID 35836) was stopped and drained, AFTER all agy results so far were quarantined, and BEFORE any clean replacement Gemini call or any scoring.

Date: 2026-11-10, about 17:45 UTC+7 (Asia/Saigon). Scope: **incident response and invocation hardening** for the Addendum 7 local-CLI Gemini voter (`agy`), plus the same per-call empty-cwd isolation for Claude Code. No change to cx (luna, Sol) or xai (t4) routes, prompts, resolution rules, metrics, or the Addendum 5 retry policy except as stated for **voided / unused-but-logged** records. All model outputs remain NOT GOLD. **Scoring has not been run.**

## Path taken

A **clean-enough session-only `agy` configuration was found**. The runner is restarted with Claude Code **and** the fixed `agy` invocation (per-call empty temp cwd, plus session-only tool-deny `--settings`). 9router `ag/` is **not** re-enabled for Gemini. The original smoke-test budget of ~7k input tokens was **not** reproduced (best clean call: 19,396 input, 0 cache_read, 1 turn, ~30 s); the gap is attributed to tool/MCP *schemas* that `agy` still injects from the user's global MCP config, which this addendum does **not** modify. Tool *calls*, file access, and workspace reads are denied. This is sufficient to restore independence/blindness for scoring calls.

## Incident (17:31 UTC+7)

The first live `agy` scoring calls behaved as a multi-step agent, not as a single-turn voter:

| item | attempt | status | input_tokens | cache_read_tokens | latency | notes |
|---|---:|---|---:|---:|---:|---|
| E084 | 2 | content_ready (ok after import) | 75,769 | 0 | 46 s | imported into `cache/voters_calls.jsonl` as an Addendum 7 ok vote |
| E085 | 2 | parse_error | 126,654 | 646,947 | 184 s | print timeout 3m, partial; never imported as a vote |
| E087 | 2 | parse_error | 150,351 | 593,162 | 184 s | print timeout 3m, partial; drained in-flight after SIGTERM; never imported as a vote |

`agy` had also spawned `npm exec brave-mcp`. The runner's cwd was `/home/conanwinner/vku_eval_local/`, which contained `jobs.json` (all other remaining sentences) and `results.jsonl` (already-finished Claude votes). That is a contamination / independence-blindness risk. A pre-cutover smoke test had been ~7k tokens.

Claude Code on the same runner looked fine and is **kept**: 51 `content_ready` scoring results; `input_tokens` 2; first call `cache_creation_input_tokens` 53,136 / `cache_read_input_tokens` 0, later calls a constant `cache_read_input_tokens` 50,095 plus ~3k cache creation; `--tools ""`; wall time ~6–8 s. Those results remain valid scoring votes.

## Stop confirmation

The previous assistant sent SIGTERM to runner PID 35836 at about 17:31 UTC+7; it had not exited after 30 s (agy child 43816 in flight). A second SIGTERM at 17:33:11 UTC+7 was followed by a graceful drain: the runner exited at about 17:33:27 UTC+7 (~25 s); agy 43816 and its brave-mcp child were gone. Journals on the user machine were consistent: 54 results / 54 intents / 0 unmatched / `local_status.json` state=`stopped`. Counts: `claude-code|content_ready` 51 (10 retry + 41 first); `agy|content_ready` 1 (E084); `agy|parse_error` 2 (E085, E087). Long-running `brave-mcp` processes that predated the runner (likely the user's Antigravity IDE) were **not** killed. A copy of `results.jsonl`, `intent.jsonl`, and `runner_log.jsonl` was placed in `eval_300/remote_ag/quarantine_20261110/` and was **not** used as the live import path until the importer was taught to skip quarantined `agy` lines.

## Quarantine (append-only; nothing deleted)

All three `agy` scoring records are marked `excluded` / `contaminated-risk` / `voided`. They are **never** imported as scoring votes. Voided attempts **do not count** toward the Addendum 5 retry cap (max 3 *non-voided* attempts). Attempt numbers are not reused: the next clean Gemini call for E084, E085, and E087 is **attempt 3**.

Box-side appends (no lines deleted):

- `remote_ag/quarantine_agy_7b.jsonl` — the official exclusion list (E084 / E085 / E087, attempt 2, with the token counts above).
- `cache/voters_calls.jsonl` — a `status=voided` tombstone for the already-imported E084 Gemini ok vote (`cache_key` `ea07d4b566…`, attempt 2, imported at ts 1794306217). After this tombstone, `first_ok_or_last` / `voter_votes` / `job_settled` treat that Gemini cell as **pending**.
- `cache/voters_calls.jsonl` and `voters_intent.jsonl` — voided *records* of the never-imported E085 and E087 attempt-2 parse_errors, so the next clean call is attempt 3 rather than a reused attempt 2.
- `remote_ag/imported_ids.jsonl` — matching `voided_7b` / `quarantined_7b` marks (the original import lines stay).
- `cache/sol_calls.jsonl` — the Sol issued **after** the contaminated E084 Gemini import is **unused-but-logged**: `cache_key` `dd51331f6666d5bd95992efea4a223ae0f05c56af2dcb15d771d3e139c320701`, status ok at ts 1794306332, then a `status=voided` tombstone. It must not be used for scoring or as the current `sol_jobs()` body. After the void, `sol_jobs()` produces a different key (`27a22874…`, a 2-vote body). That key is **not issued** until all three voter jobs are settled (Addendum 6 §3); E084's Gemini cell is still pending, so no replacement Sol is issued now.
- **t4 E084 is not voided.** One ok t4 record exists at ts 1794293735, *before* the Gemini import. The t4 `cache_key` is sentence+model+prompt SHA only, so it may be reused later if the cell is still open after a clean Gemini vote (and, if needed, a new Sol). The earlier pre-import Sol `f3cf427b…` is also left in the log and is not the current `sol_jobs()` key.

`import_remote_ag.py` skips any remote line that is voided/excluded or whose `(cache_key, attempt)` is in `quarantine_agy_7b.jsonl`. `_has_ok` uses only non-voided records, so a later clean attempt can be imported. After this skip list was in place, the 51 Claude results in the quarantine file were imported: 50 new ok votes, 4 skipped (already-imported E084 Claude + 3 quarantined agy). Journals remain 0-orphan.

Routing after the void (recomputed, no scoring): E084 valid voters are luna + Claude only; Gemini is pending attempt 3; `open_cells` for E084 is 11× `open` with no current Sol review; remaining scoring CLI work is 161 jobs (Gemini: 3× a3, 29× a2, 85× a1; Claude: 44× a1 first).

## Diagnosis (dummy non-eval sentence, empty `mktemp -d`, no files)

Prompt: frozen `SYSTEM_PROMPT` + `{"sentence":"Xin chao, day la cau kiem tra ket noi, khong phai phan hoi sinh vien."}`. Flags in every test: `--output-format json --sandbox --disable-slash-commands --print-timeout 90s --model gemini-3.8-flash-high`. User global settings were **not** modified. Official `settings.json` keys were taken from https://antigravity.google/schemas/v1/settings.json (session-only `--settings`, never saved). There is **no** settings key that disables MCP loading; MCP lives in `~/.gemini/config/mcp_config.json`, which was not edited. `--new-project` was not used (it would create persistent Antigravity projects and is not acceptable once per scoring call). `agy agents` printed no usable agent list.

| test | extra | exit | status | input_tokens | cache_read_tokens | num_turns | wall |
|---|---|---:|---|---:|---:|---:|---|
| A | empty cwd only | 3 | ERROR (print timeout 90s) | 103,568 | 197,617 | 1 | ~90 s |
| B | `--mode plan` | 0 | SUCCESS | 82,385 | 223,540 | 1 | (stderr: plan has no effect while slash-command expansion is disabled) |
| C | guessed `--settings` `allowedTools` / `enableTools` / `mcpServers` | 1 | (no JSON) | — | — | — | immediate: unknown setting `allowedTools` |
| D | session-only official `--settings` denying `mcp(*)`, `read_file(*)`, `write_file(*)`, `command(*)`, `read_url(*)`, `execute_url(*)`, plus `allowNonWorkspaceAccess: false`, `toolPermission: strict` | 0 | SUCCESS | **19,396** | **0** | **1** | ~30 s |

Test D is the fixed invocation. First live scoring calls are expected around this size (roughly 15–25k input, cache_read 0 or negligible, `num_turns` 1, success in well under the 120 s print timeout), **not** 75k–150k input or hundreds of thousands of cache_read tokens, and **not** a 3-minute print timeout.

## Fixed invocation

1. **Per-call empty temp cwd.** For every Claude Code and every `agy` call, the runner creates `mkdtemp(prefix="vku_cli_cwd_")`, runs the CLI with `cwd` set to that empty directory, and deletes the directory afterwards (`shutil.rmtree`). The directory has no `jobs.json`, no `results.jsonl`, no prompt file, and no other eval files. The job is fed only via argv (`-p`): for Claude, the user message `{"sentence": "..."}` plus `--system-prompt-file` pointing at an **absolute** path *outside* the cwd; for `agy`, `SYSTEM_PROMPT + "\n\n" + {"sentence": "..."}` in `-p`.
2. **Runner files stay outside the CLI cwd.** `jobs.json`, `results.jsonl`, `intent.jsonl`, `runner_log.jsonl`, `local_status.json`, `run_local.pid`, and `system_prompt.txt` remain in `/home/conanwinner/vku_eval_local/`, which is never used as `agy` or Claude cwd.
3. **`agy` session-only tool deny** (not written to `~/.gemini/antigravity-cli/settings.json`):

   `agy -p <combined> --model gemini-3.8-flash-high --output-format json --sandbox --disable-slash-commands --print-timeout 120s --settings '{"allowNonWorkspaceAccess":false,"toolPermission":"strict","permissions":{"deny":["mcp(*)","read_file(*)","write_file(*)","command(*)","read_url(*)","execute_url(*)"]}}'`

   Print timeout is 120 s (was 180 s), which is enough for a single-turn ~30 s call and fails faster if the agent starts wandering again.
4. **Claude Code isolation.** The same per-call empty cwd is applied for consistency. Flags are otherwise unchanged from Addendum 7 (`--tools ""`, `--disable-slash-commands`, `--effort low`, `--model claude-sonnet-5-5`, `--permission-mode default`, no `--bare`). Existing Claude results remain valid, as justified in the Incident section (tools already disabled; input 2 tokens; constant ~50k cache; ~6–8 s).
5. **Journals and scoring rules.** New CLI records are tagged `addendum: "7b"` and `isolation: "empty_temp_cwd"`. `run_eval.first_ok_or_last`, `usable_call_records`, `parallel_eval.job_settled` / `next_attempt`, and the importer ignore voided records and do not count voided attempts toward the cap. `score.py` already goes through `first_ok_or_last` / `voter_votes` (it must not be run until the eval finishes).
6. **Sensitivity jobs** (`kind: "sensitivity"`) use the same isolated invocation when they run; they remain not-for-scoring.

## Unchanged

cx/gpt-6-luna, Sol (cx/gpt-6.1-sol), t4 (xai/grok-4.7), their 9router endpoint and timeouts, prompt SHA `74d0fd7d…`, guideline v2, resolution rules, metrics, Wilson CIs, policy-cell rule, first-attempt caps, Addendum 5 retry policy (with the voided-attempt exception above), Addendum 6 cx/xai parallelism, no fallback, no use of `archive_opus_voter/`, no edits to the user's Claude or `agy` global config, no original-data changes, no push/clone, `NINE_ROUTER_API_KEY` never on the user machine.
