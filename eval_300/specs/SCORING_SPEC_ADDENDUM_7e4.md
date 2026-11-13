# Addendum 7e.4 to SCORING_SPEC.md and ADDENDA 1–7e.3a (ADDENDUM_7e3 SHA 1b36d5cd3992735187f4e5501d13562d986eae21d711ae938378ab0b018ec1b7, ADDENDUM_7e3a SHA f5bcd7125e8e650306bae0111a0cbb32a8f0929f724f1fc942ef83756b20f45c). Voter-set change. Supersedes 7e.2 where they conflict.

This addendum was written:
- after the 7e.3 scheduler (PID 782911) was stopped with SIGTERM at about 06:25 UTC+7 on 2026-11-11 (drained by itself; 0 voter/Sol orphans; the in-flight Gemini-low E098 call was recorded by the scheduler);
- BEFORE any vote by `cx/gpt-5.6-luna` or `cx/gpt-5.6-terra` (only the non-vote pings below);
- BEFORE any new Sol call or t4 result;
- BEFORE the supersede records below were appended;
- BEFORE any scoring. **Scoring has not been run; human labels have not been loaded.** All model outputs remain NOT GOLD.

## Why (route history)

- **TrollLLM (`trollllm/deepseek-v4-1-flash`, V3 under 7e.2) failed at the provider.** From about 01:00 UTC+7 no new ok vote. The scheduler recorded 15 `parse_error` (HTTP 200 with empty content) and 8 `transport_error` attempts in total; the `tl` lane hit its breaker 9 times (failure streak). Operator checks at 06:17 UTC+7 (not votes): 3 non-stream calls returned HTTP 200 with empty content (0 completion tokens, status `in_progress`); 1 stream call returned `[Error] Upstream request failed`. The sibling `trollllm/deepseek-v4-flash` (user suggestion) gave 3/3 empty responses. So the whole TrollLLM provider/account was failing, not one model.
- **Gemini-low (`ag/gemini-3.8-flash-low`, V2 under 7e.2) was too slow.** 97 ok votes after ~8 h, 14 transport errors (mostly `ReadTimeout`), throughput about 7–10 items per hour; at that rate the remaining ~200 items would take > 20 h, past the working deadline for FJCAI 2027 (15 Nov 2026).
- User decision (Le Duc, 2026-11-11 ~06:24 UTC+7, verbatim): "Đồng ý, chuyển sang luna 6 + luna 5.6 + terra 5.6, triển khai luôn" (approving an all-Codex voter set, because "các model của codex thì oke").

## Voters (all `cx/*` over 9router, endpoint exactly `<9ROUTER_ENDPOINT>`)

- **V1 `cx/gpt-6-luna`** — unchanged; existing records reused (300/300 ok).
- **V2 `cx/gpt-5.6-luna`** (new). Returned-model check: exactly `gpt-5.6-luna`. Operator ping 06:27:33 UTC+7 with a dummy, non-research sentence through the voter path: ok, HTTP 200, parsed valid, 7.2 s. Not a vote.
- **V3 `cx/gpt-5.6-terra`** (new). Returned-model check: exactly `gpt-5.6-terra`. Ping 06:27:41 UTC+7: ok, HTTP 200, parsed valid, 7.7 s. Not a vote.
- Pings are in `probe_log_7e4.jsonl`; outside the caps.

Call settings unchanged: same voter system prompt (SHA `74d0fd7d…`, guideline v2), sentence-only input, temperature 0, max_tokens 2000, `stream: false`, no effort parameter, same `voter_call` → `post_once` path and parse/validity rules, 120 s hard wall-clock deadline (7e.3). Retries per Addendum 5: at most 3 non-voided attempts; the first ok counts.

**Disclosed limitation (must appear in the paper):** all three voters are OpenAI GPT-family models served through the same Codex route. Their errors are likely correlated, so agreement among them is weaker evidence of correctness than agreement among independent model families, and the unanimity rate (stage-1 coverage) may be inflated. Stage 3 (Claude Sonnet) is the only non-GPT signal. This is reported as a limitation; results are not re-weighted.

## Stage 2 and stage 3 (unchanged models and rules)

- Stage 2: Sol `cx/gpt-6.1-sol`, reasoning effort medium, same review prompt, 240 s hard deadline. Sol keys hash the tag `voter_set: "7e4"` (new keys; the input contains the new votes).
- Stage 3: blind 4th vote by Claude Code `claude-sonnet-5-5 --effort medium` on the user's computer through the existing remote job queue (`remote_t4_payload/jobs_t4.jsonl`), same job format and import checks.
- Decision rule unchanged (5 votes pooled: V1, V2, V3, Sol, t4; top label ≥ 3 votes, unique, usable, supported by Sol or t4; else `unresolved`, no fallback).

**Sol route problem found before the restart.** The last 7e.3 Sol attempt (E055 a3, 06:12:40 UTC+7) and a trivial operator ping at 06:27:42 UTC+7 (not research data) both returned HTTP 400: "The 'gpt-6.1-sol' model requires a newer version of Codex. Please upgrade to the latest app or CLI". This is a router/client-version issue on 9router, not a model change. Rule (pre-registered here, pacing only):
- The scheduler is started with `--hold-lanes cx` (Addendum 7c operator hold). Under 7e.4 the `cx` lane carries only Sol (V1 luna is complete), so **no Sol call is issued and no Sol attempt is burned** while the route is broken. Voters V2/V3 run on their own lanes.
- When a trivial Sol ping (logged to `probe_log_7e4.jsonl`) returns ok with returned model `gpt-6.1-sol`, the scheduler is restarted without the hold. Sol is never substituted by another model; if the route cannot be fixed, the user decides.
- Consequence: no new t4 jobs are exported until Sol has run for an item (t4 needs Sol settled, unchanged gating).

## t4 records (blind; reuse rule of 7e.2)

t4 keys are `cache_key(sentence, claude-code/claude-sonnet-5-5-medium, prompt SHA)`: the t4 input is the voter prompt + sentence only, so it does **not** depend on the voters. As in 7e.2: an existing t4 job/result (2 imported 7e.1 results, 9 outstanding jobs) is reused if and only if that item still has open cells after 7e.4 stage 2; t4 jobs/results for items that do not need stage 3 under 7e.4 are superseded (append-only, reason `design_7e4_user_decision_2026-11-11`) once stage 2 is complete and before scoring. The scheduler waits only on outstanding t4 jobs that are still needed.

## Supersede (append-only; nothing deleted), reason `design_7e4_user_decision_2026-11-11`

| Superseded | Keys | Call records |
|---|---|---|
| `ag/gemini-3.8-flash-low` voter | 98 | 112 |
| `trollllm/deepseek-v4-1-flash` voter | 81 | 97 |
| 7e.2/7e.3 Sol-medium (voter set 7e2) | 23 | 27 |
| **Total** | **202** | **236** |

(Counted by `supersede_7e4.py` in dry-run mode, which reads only keys, models and statuses, never labels.) Earlier supersedes and voids stay. Superseded results may appear only as clearly labelled secondary information (e.g. route history).

## Pacing (lanes)

- One call in flight per lane.
- **`cx2` = `cx/gpt-5.6-luna` and `cx3` = `cx/gpt-5.6-terra`**, each its own lane (different models), fixed 20 s start gap per lane, and the same breaker as the 7e.2 `tl` lane: 3 consecutive HTTP/transport errors, failure streak of 3, or > 20 % failures in a 30-call window → 900 s cooldown, at most 8. 401/403 aborts the run.
- `cx` lane (Sol): pacing unchanged from 7e.2/7e.3 code (one in flight, breaker as above, no extra start gap); held at start as described.
- `ag` and `tl` lanes remain in the code but receive no work.
- If errors on a lane persist > 30 min, the lane is stopped and reported. Models are never switched without a user decision and a new addendum.

## Caps (unchanged values; hard guard counting active keys only)

- VOTER_CAP 900 = luna-6 300 (active) + gpt-5.6-luna 300 + gpt-5.6-terra 300. After the supersede, active voter keys = 300, so the full 600 new keys fit.
- SOL_CAP 300; active Sol keys after supersede = 0.
- TOTAL_CAP 1500 ≥ 900 + 300 + 11 active t4 keys (+ any new t4 ≤ 300 items would exceed only if all three stages maxed, which is impossible: t4 only for items with open cells). No cap change needed.

## Code refusals

Under `--design-7e4` the box refuses to issue any voter that is not one of the three `cx/*` voters above (so no `ag/*`, `trollllm/*`, `oc/*`, `xai/*`, `agy`, Claude). It never calls t4 itself. The 7e.2 mode is refused because `run_eval.VOTERS` changed.

## Implementation

- `run_eval.py`: VOTERS, EXPECT (+2), Sol key tag `7e4`.
- `parallel_eval.py`: lanes `cx2`/`cx3` with the 20 s gap and `tl`-style breaker; `--design-7e4` required for live; voter refusal; self-test updated.
- `supersede_7e4.py`, `probe_7e4.py` (new).
Old versions in `archive_pre_7e4/`; SHAs in `addendum7e4_code.sha256`. Logs `run17_7e4_*`, pid `run17_7e4.pid`.
Command: `nohup python3 -u parallel_eval.py --live --design-7e4 --wall-deadline --hold-lanes cx >> run17_7e4_stdout.txt 2>> run17_7e4_stderr.txt &`
