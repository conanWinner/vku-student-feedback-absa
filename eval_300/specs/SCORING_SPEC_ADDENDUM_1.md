# Addendum 1 to SCORING_SPEC.md (SHA d9f76dd0…). Written BEFORE the restarted run.

Date: 2026-11-09, about 17:30 UTC+7. Everything in SCORING_SPEC.md stays in force except the items below.

## Why the change
`ag/claude-opus-4-6-thinking` stopped working on the router:
- The upstream returns 403.
- One probe returned HTTP 200 with `model: "gemini"` and the text "Claude Opus 4.6 is no longer available".
- E001–E003 were silently served by another model.

The user chose to replace that voter.

## Changes
1. **Voters:** cx/gpt-6-luna, **ag/claude-opus-5-5-high** (replaces ag/claude-opus-4-6-thinking), ag/gemini-3.8-flash-high.
2. **Tie-breaker (stage 3):** **xai/grok-4.7**, a different provider family from every voter and from Sol.
   - nvidia/deepseek-ai/deepseek-v4-pro was tried first and returned HTTP 410 (end of life).
   - The tie-break rule is unchanged except that "4th" now means grok-4.7: a winning label still needs support from Sol or the tie-breaker.
3. **Sol** is unchanged (cx/gpt-6.1-sol, reasoning_effort "high" requested).
4. **Returned-model check:** a vote counts only if the returned `model` equals:

   | Alias | Required returned name |
   |---|---|
   | cx/gpt-6-luna | gpt-6-luna |
   | ag/claude-opus-5-5-high | claude-opus-5-5-high |
   | ag/gemini-3.8-flash-high | gemini-3.8-flash-n |
   | xai/grok-4.7 | grok-4.7 |
   | Sol | gpt-6.1-sol (checked at scoring; not counted if different) |

   Anything else = `model_mismatch` = no vote.
5. **Clean restart:** the 13 calls of run 1 are archived in `archive_run1/` and excluded from scoring. All 300 sentences are re-run with a fresh journal and cache.
6. **Extra circuit breaker:** pause the stage after 3 consecutive model_mismatch / parse_error / http_error results from the same model.
7. **Unchanged:** caps, concurrency, no retries, metrics, policy-cell rule.

## Note for the paper
The voter set now differs from the 150-sentence pilot (Opus 5.5-high replaces Opus 4.6-thinking) and so does the tie-breaker (Grok 4.7 replaces Opus 5.5-high). Pilot and eval_300 numbers come from different model ensembles.
