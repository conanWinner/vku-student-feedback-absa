# Addendum 7e.2 to SCORING_SPEC.md and ADDENDA 1–7e.1 (ADDENDUM_7e1 SHA 3ea3cef8cfa3997c9cc436162424fa50eb770d7a617261fa821c2014c8d981c9). FINAL design. Supersedes 7e/7e.1 where they conflict.

This addendum was written:
- after the 7e.1 scheduler (PID 746510) was stopped at about 21:23 UTC+7 (drained; 0 voter/Sol orphans);
- BEFORE any call to `ag/gemini-3.8-flash-low` or `trollllm/deepseek-v4-1-flash` other than the operator's pings described below;
- BEFORE any new Sol call or t4 result;
- BEFORE the void and supersede records below;
- BEFORE any scoring.

Date: 2026-11-10, about 22:25 UTC+7 (Asia/Saigon). All model outputs remain NOT GOLD. **Scoring has not been run; human labels have not been loaded.**

## Why

Under 7e.1 both `oc/*` free models hit HTTP 429 `FreeUsageLimitError` (the OpenCode free quota, shared by both) at about 21:22 UTC+7. That is far short of the ~600 calls needed.

User decision (the operator, 2026-11-10 22:17–22:18 UTC+7): final voter set, all over 9router (endpoint exactly `<9ROUTER_ENDPOINT>`), all light models of the same tier.

## Voters

- **V1 `cx/gpt-6-luna`.** Existing records are reused (300/300 ok).
- **V2 `ag/gemini-3.8-flash-low`** (new).
  - Returned-model check: exactly `gemini-3.8-flash-n`. That is the same name the high variant returns, so **the low tier cannot be verified from the response**. This must be disclosed.
  - An operator ping at 22:00 UTC+7 was OK (4.3 s). It was not a vote.
- **V3 `trollllm/deepseek-v4-1-flash`** (new).
  - Returned-model check: exactly `deepseek-v4-1-flash`.
  - An operator ping at 22:18 UTC+7 was 3/3 OK (~2.5 s). Not a vote.
- The 17 + 4 earlier `oc/deepseek-v4.1-flash-free` votes come from a different route and are **not reused**; they are superseded.

**Call settings:**
- Same voter system prompt (SHA `74d0fd7d…`, guideline v2) and input (sentence only).
- Same body: temperature 0, max_tokens 2000, `stream: false` sent explicitly, as for every voter body. No effort parameter.
- Same `voter_call` → `post_once` path, same parse/validity rules, 120 s timeout.
- Retries per Addendum 5: at most 3 non-voided attempts; the first ok counts.

**Pacing (lanes):**
- One call in flight per lane.
- Gemini-low runs on the **ag** lane with the ag pacing (start gap 20 s with the existing +10/−5 tuning, 503 pause). The ag re-probe probes only `ag/gemini-3.8-flash-low`, using the shared `probe3.py` budget (19/36 used).
- TrollLLM runs on its own lane **`tl`** with a fixed 20 s start gap. Its breaker:
  - Triggers: 3 consecutive HTTP or transport errors, a failure streak of 3, or a window of more than 20 % failures.
  - Action: a 900 s cooldown, at most 8 of them.
- Quota and rate-limit errors (429) trigger the breaker the same way.
- **If errors on a lane persist for more than 30 min, the lane is stopped and reported. Models are never switched.**

**Stage 2:** Sol `cx/gpt-6.1-sol`, **medium** reasoning effort, as in 7e.1 (same review prompt, 240 s). Sol keys hash the tag `voter_set: "7e2"`.

**Stage 3:** blind 4th vote by Claude Code `claude-sonnet-5-5 --effort medium` on the user's computer, through the remote job queue of 7e.1. Job format, import checks, one outstanding attempt per job, and attempt+1 export after an imported failure are all unchanged.
- **Reuse rule:** t4 is blind (voter prompt + sentence only) and its key does not depend on the voters. A 7e.1 t4 job or result (E011, E012 exported, no results yet) is reused if and only if that item still has open cells after the 7e.2 stage 2.
- 7e.1 t4 jobs or results for items that do not need stage 3 under 7e.2 are **superseded** (append-only, reason below) when stage 2 is complete and before scoring. The scheduler does not wait on outstanding t4 jobs that are not needed.

## Void and supersede (append-only; nothing deleted)

**Void first.** The six quota-429 attempts get per-attempt void records with `void_reason=oc_free_quota_429_2026-11-10`:
- GLM E012 a1–a3
- oc-DeepSeek E022 a1–a3

**Then supersede**, with key-level records and `void_reason=design_7e2_user_decision_2026-11-10`:

| Superseded | Keys | Call records |
|---|---|---|
| `oc/glm-5.3-flash-free` voter | 12 | 15 |
| `oc/deepseek-v4.1-flash-free` voter | 22 | 24 |
| 7e.1 Sol-medium | 5 | 5 |

The earlier supersedes (Claude-low, Gemini-high, older Sol, 7d t4) and the xai voids stay. Superseded or voided results may appear only as clearly labelled secondary information.

## Decision rule (unchanged)

Five votes are pooled: V1, V2, V3, Sol, and the Claude-medium t4. A cell is `tiebreak_resolved` if the top label has at least 3 votes, is unique, is a usable label, and is supported by Sol or by the 4th model. Otherwise it is `unresolved`; there is no fallback.

## Caps (as in 7e.1; hard guard, counting active keys only)

- VOTER_CAP 900 (luna 300 + Gemini-low 300 + TrollLLM 300).
- SOL_CAP 300.
- TOTAL_CAP 1500.
- Active at this addendum: voters 300 (luna), Sol 0, t4 2 (E011/E012 outstanding).

## Code refusals

The box refuses to issue any of these as a voter:
- `xai/*`
- `agy`
- `oc/*`
- `ag/gemini-3.8-flash-high`
- any Claude model

It never calls t4 itself.

## Implementation

- `run_eval.py`: VOTERS, EXPECT, Sol key tag.
- `parallel_eval.py`: lane `tl` with the 20 s gap; the ag re-probe model; refusals; `--design-7e2`; waiting only on needed t4 jobs.
- `probe3.py`: EXPECT gains the two new models.

Old versions are in `archive_pre_7e2/`, and SHAs are in `addendum7e2_code.sha256`. Logs go to `run15_7e2_*`. Dummy live checks go to `probe_log_7e2.jsonl`; they are not votes and are outside the caps.
