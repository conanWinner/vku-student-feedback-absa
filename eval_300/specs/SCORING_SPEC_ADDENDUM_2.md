# Addendum 2 to SCORING_SPEC.md (SHA d9f76dd0…) and ADDENDUM_1 (SHA 5ff85c81…). Written BEFORE resuming run 2.

Date: 2026-11-09, about 18:20 UTC+7. Scope: **pacing and breaker handling only**. No change to models, prompts,
routing, resolution rules, metrics, policy-cell rule, caps (1270 total; voters ≤ 900; Sol ≤ min(300, remaining)), or the no-retry rule.

## Why
Run 2 tripped twice (after 18 and 9 voter calls). Every failure was HTTP 503 from the whole `ag/` (Antigravity) route with
the message "upstream 403 … (reset after ~1–2m)", i.e. upstream rate limiting. It hit both ag/claude-opus-5-5-high and
ag/gemini-3.8-flash-high. All cx/ calls succeeded. 27 voter calls are journaled: 14 ok, 13 http_503 (all ag/).

## Changes
1. **Already-failed calls stay non-votes.** The 13 journaled http_503 voter calls (E005–E009, ag/ only) are not re-sent
   (no-retry rule). Their cells simply have fewer valid votes and follow the spec's existing routing (fewer than 3 valid
   votes → Sol). The final report states how many sentences/cells lack votes.
2. **Health probes before resuming.** One cheap probe call per ag model ("Reply with exactly: KET_NOI_OK", max_tokens 50),
   one round about every 10 min. Resume only after 2 consecutive healthy rounds (round healthy = both ag models return HTTP 200,
   the expected returned model name from Addendum 1, and the text). Pre-resume budget: max 12 probes.
   Probes are health checks only: never used as votes, not counted in the 1270 research-call cap, logged in `probe_log_run3.jsonl`.
3. **Lanes / concurrency (total in flight ≤ 2, as in the spec).**
   - ag lane: max 1 ag/ call in flight across all ag models. Minimum gap between ag call starts: start 20 s.
     Tuning (fixed now): after 30 consecutive ag calls without a 503, gap −5 s (floor 10 s); after any ag 503, gap +10 s (cap 60 s).
   - other lane: cx/ (voter luna, then Sol) and xai/ (tie-break) at 1 in flight while ag calls remain; 2 in flight when no ag work remains.
   - Pipelining: an item's Sol call is issued only after all 3 of its voter calls are journaled; its tie-break call only after its
     Sol call is journaled (or Sol is not needed). Routing and job identity are computed exactly as in run_eval.py, so the result
     is the same as running stages one after another.
4. **ag 503 with a stated reset.** The attempt is journaled as a failed non-vote (no retry). All ag calls pause for the stated
   reset time + 30 s (no stated reset: 150 s).
5. **Breakers.**
   - Unchanged, global hard stop: any real HTTP 401/403 status; API key appearing in any record.
   - Unchanged, per model (Addendum 1 #6): 3 consecutive model_mismatch / parse_error / http_error from one model.
     For cx/ and xai/ this stops that lane. For ag/ it triggers pause + re-probe (below).
   - cx/ and xai/ lanes: 3 consecutive HTTP/transport errors in the lane, or > 20% non-ok in the lane's last 30 results → stop the lane.
   - ag lane: > 30% failing over the last 30 ag calls (checked once ≥ 30 ag results since the last resume), 3 consecutive ag
     failures, or the per-model streak above → pause ag and re-probe (same probe protocol, one round ~ every 10 min, 2 consecutive
     healthy rounds to resume; the ag failure window and streaks are reset on resume).
   - Probe budget shared across pre-resume and in-run re-probes: max 24 probes in total. If it runs out, stop the ag lane,
     let cx/xai work that does not depend on missing ag calls finish, and report the partial state. Unissued ag voter jobs then
     get no call (same treatment as "beyond budget": their cells follow the spec with fewer votes).
   - The breaker split by lane is a deviation from the spec's single global "> 20% of last 30" rule, made because rate-limit 503s
     on ag/ are handled by the pause rule above; it does not affect which results count as votes.
6. **Diagnostics.** Non-200 responses keep a sanitized error message (≤ 200 chars, key-checked) in the call record.

## Unchanged
Models (Addendum 1), returned-model check, prompts, temperature, max_tokens, timeouts, routing, resolution rules, metrics, Wilson CIs,
policy-cell rule, caps, no retries, no fallback, endpoint allowlist, redirects off.
