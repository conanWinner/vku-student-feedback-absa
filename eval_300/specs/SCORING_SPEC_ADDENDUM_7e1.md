# Addendum 7e.1 to SCORING_SPEC.md and ADDENDA 1–7e (ADDENDUM_7e SHA 8545ba6bcf1397fa82a3743e4f37050164ac3bbacb052f0bd392e7dba2605097). Supersedes 7e where they conflict. Written after scheduler PID 740561 drained (0 orphans), BEFORE any GLM call, any medium-effort Sol call or any Claude-medium t4 job, BEFORE the supersede records below, and BEFORE any scoring.

Date: 2026-11-10, about 21:20 UTC+7 (Asia/Saigon). All model outputs remain NOT GOLD. **Scoring has not been run; human labels have not been loaded.**

## State of 7e when this was written

7e was written and sha'd. The scheduler ran under 7e from 21:10 to 21:16 UTC+7 and produced:

- **17 DeepSeek voter calls**, all ok (E001–E017). Only their status, latency, returned model and parse validity were seen, not label contents.
- **9 Sol calls** at high effort on 7e disagreements (luna + Claude + DeepSeek inputs).
- No t4 calls.

## Decision

User decision (Le Duc, 2026-11-10 21:14 UTC+7): change of design.

- **Voters (all over 9router, endpoint exactly `<9ROUTER_ENDPOINT>`):**
  - **V1** `cx/gpt-6-luna`: existing records reused (300/300 ok).
  - **V2** `oc/glm-5.3-flash-free`: new, replaces Claude Sonnet as a voter. A dummy ping at 21:11 returned HTTP 200, model `glm-5.3-flash-free`. The model is not listed in `/v1/models` but is callable.
  - **V3** `oc/deepseek-v4.1-flash-free`: per 7e. The 17 existing ok 7e DeepSeek records are reused, because voter calls are blind and independent of the other voters.
- **Stage 2:** Sol `cx/gpt-6.1-sol` with **medium** reasoning effort (was high). Same review prompt, anonymised-vote input format and 240 s timeout.
- **Stage 3 (blind 4th vote):** Claude Sonnet 5.5, **medium** effort, via the Claude Code CLI on the user's computer (`--model claude-sonnet-5-5 --effort medium`). It uses the plain voter system prompt (SHA `74d0fd7d…`) and the user message `{"sentence": …}` only, with the same CLI invocation and isolation as the 7c Claude-only runner: an empty temp cwd per call, `--tools ""`, `--disable-slash-commands`, `--output-format json`, `--system-prompt-file`, and no 9router key in the env.

## Voter calls (V2, V3)

V2 and V3 use the identical voter prompt, inputs, temperature 0, max_tokens 2000, the `voter_call` → `post_once` path, the same parse/validity rules, and no effort parameter. Returned-model checks are exact: `glm-5.3-flash-free` and `deepseek-v4.1-flash-free`; otherwise the result is `model_mismatch`, a non-vote.

- **Timeout:** 120 s, the same as Gemini's.
- **Lanes:** one call in flight per oc model. DeepSeek runs on the ag lane with Gemini's pacing (20 s start gap with tuning, 503 pause, re-probe of DeepSeek only via the shared `probe3.py` budget). GLM runs on its own lane, `oc2`, which reuses the former xai lane slot. That lane has the generic breaker: 3 consecutive HTTP/transport errors, failure streak 3, or a window above 20 % stops the lane for a 900 s cooldown, with at most 8 cooldowns.
- **Retries (Addendum 5):** at most 3 non-voided attempts per job; the first ok counts.
- **Unavailability:** if a lane has only errors for more than 30 minutes, it is stopped and reported. There is no switch of model.

## Stage 3 as a remote job queue

The box cannot reach the user's computer, so stage 3 runs as a queue.

**Box side:**
1. When an item's voters and Sol are settled and open cells remain (`open_cells`), the box scheduler appends a job line to `remote_t4_payload/jobs_t4.jsonl`. The line holds `job_id = <cache_key>:a<attempt>`, `item_id`, `cache_key`, the sentence, the exact `user_message`, `prompt_sha256`, `cli_model claude-sonnet-5-5` and `effort medium`. At the same moment it writes an intent line to `cache/t4_intent.jsonl`.
2. At most one outstanding attempt per job. A retry, which becomes a new job line with attempt+1, is exported only after the previous attempt's result has been imported as a non-ok. The 3-attempt cap counts outstanding attempts.
3. The importer (`import_remote_t4.py`) reads `remote_t4/results.jsonl` (copied back by the operator). It accepts a line only if:
   - `job_id` matches an exported job (same cache_key, attempt and item);
   - `requested_model` is `claude-code/claude-sonnet-5-5-medium`, `cli_model` is `claude-sonnet-5-5` and the `effort` tag is `medium`;
   - the returned model is exactly `claude-sonnet-5-5` (else `model_mismatch`);
   - the content passes the official `validate_annotation` (else `parse_error`/`schema_error`).

   An accepted line is appended to `cache/t4_calls.jsonl`. Transport, CLI and rate-limit failures are non-votes that consume an attempt. Each job is imported at most once, and an already-ok key is never imported again.
4. The 7d effort tags cannot be verified from the CLI output, so `effort` is the runner's record of the flag it passed.
5. The scheduler keeps running while t4 attempts are outstanding.

**Remote side:** `run_local_t4.py` reads the jobs file and runs each job not yet in its `results.jsonl`, one call at a time. It writes append-only results and `local_status_t4.json`, and it is idempotent when re-run or when the jobs file grows; it does not retry by itself. Rate-limit rounds are as in 7c: same attempt, backoff, at most 5 rounds.

T4 job identity is `cache_key(sentence, "claude-code/claude-sonnet-5-5-medium", prompt_sha)`.

## Superseded and voided (append-only; nothing deleted)

Every record listed here gets a key-level supersede record (`status=voided`, `superseded=true`, `void_scope=key`, `void_reason=design_7e1_user_decision_2026-11-10`). None is used for the main result or counted in caps.

| Stage | What | Keys | Records |
|---|---|---|---|
| Voters | Claude Sonnet low (remote imports plus earlier 9router attempts) | 271 | 298 |
| Voters | Gemini | 215 | 264 (already superseded in 7e) |
| Sol | 7e high-effort records | 9 | 9 |
| Sol | pre-7e records | 155 | — (already superseded in 7e) |
| t4 | 7d Sol-as-4th records (`cx/gpt-6.1-sol` high) | 29 | 29 |
| t4 | xai records | — | — (already voided in 7d) |

Claude-low and Gemini results may be reported only as clearly labelled secondary or sensitivity information, never in the main result. The Claude Code low runner's final results, from a session that completed at 21:01, are not imported into the scoring journal.

Sol keys now hash the tag `voter_set: "7e1"` (key only; the request body is unchanged apart from `reasoning_effort: medium`).

## Decision rule (unchanged)

There are 5 pooled votes: V1, V2, V3, Sol (stage 2) and the Claude-medium t4. A cell is `tiebreak_resolved` if the top label has ≥3 votes, is unique, is a usable label, and is supported by Sol or the 4th model. Otherwise it is `unresolved`, with no fallback. Unanimity and Sol eligibility are as in the base spec, recomputed from the new voter set.

Limitation: V1 and Sol are both from the cx (GPT) family, and the 4th model (Claude) is independent of both. The voter set is all 9router; Claude only appears as a stage-3 CLI vote.

## Call budget (hard guard, not a scoring rule)

Caps count active (non-voided, non-superseded) unique keys; retries are bounded by the 3-attempt rule.

- **VOTER_CAP 900:** luna 300 + GLM 300 + DeepSeek 300.
- **SOL_CAP 300.**
- **TOTAL_CAP 1500:** 900 + 300 Sol + 300 t4.

Active right now: voters 317 (luna 300 + DeepSeek 17), Sol 0, t4 0. Expected: about 900 voter keys, about 200–250 Sol, about 50–80 t4, about 1200 in total.

## Code refusals

The box scheduler refuses to issue `xai/*`, `agy`, any Gemini model or any Claude model as a voter. It never issues t4 itself (t4 is remote only).

## Unchanged

Voter prompt and guideline v2, parse rules, metrics, Wilson CIs, policy-cell rule, Addendum 5 retry policy with voided-attempt exceptions, timeouts (120 s voters, 240 s Sol), no fallback between routes, no original-data changes, and no push. `NINE_ROUTER_API_KEY` stays in env and is never logged.

## Implementation

- `run_eval.py`: VOTERS, EXPECT, Sol effort medium for this eval, Sol key tag `7e1`, T4 label.
- `parallel_eval.py`: the `--design-7e1` mode, lane `oc2`, remote t4 export/import, refusals.
- `probe3.py`: unchanged from 7e, except that EXPECT includes GLM.
- New files: `import_remote_t4.py`, `supersede_7e1.py`, and `remote_t4_payload/run_local_t4.py` with its `system_prompt.txt`.

Old versions are in `archive_pre_7e1/`, SHAs in `addendum7e1_code.sha256`. Logs `run14_7e1_*`.
