# Addendum 7e.3 to SCORING_SPEC.md and ADDENDA 1–7e.2 (ADDENDUM_7e2 SHA 4681386cfc520793705f1a8a7d83089466f4e577d5916badb67f567ea4bff713). Enforcement only. Written BEFORE the 7e.2 scheduler (PID 757648) is stopped, BEFORE any post-hoc record below, and BEFORE any scoring.

Date: 2026-11-10, about 22:55 UTC+7. NOT GOLD. Scoring has not been run.

## What happened

From about 22:41 UTC+7 the 7e.2 scheduler made no progress, although the endpoint itself was healthy. The `requests` timeout passed to each call (120 s voters, 240 s Sol) is a **per-socket-read** timeout, not a total deadline. When the server trickles bytes or keepalives, the call can run far longer than specified. At 22:51 two of the stuck calls ended by themselves, each with `transport_error` / `ReadTimeout` after about 620 s:

| Call | Issued | Result |
|---|---|---|
| Gemini-low E027 attempt 1 | 22:41:06 | ReadTimeout at 22:51:29 |
| TrollLLM E026 attempt 1 | 22:41:06 | ReadTimeout at 22:51:31 |

Sol E023 attempt 2 (issued 22:41:06, after attempt 1 had a normal ReadTimeout) was still hung at 22:55.

## Rule

The already-specified per-call timeouts become a **hard wall-clock deadline** on the whole HTTP call (connect, headers and body): **120 s for voters, 240 s for Sol**. The timeout values, pacing, prompts, models, retry rule and everything else are unchanged.

A call that exceeds the deadline is closed and recorded as `transport_error` with `error=ReadTimeout`, like any other timeout. It counts as one attempt under the existing Addendum 5 retry rule (max 3 non-voided attempts; the first ok counts).

## How the hung calls are recorded (decision, made before seeing any of their content; there is none)

- **E027 Gemini-low a1 and E026 TrollLLM a1:** already recorded by the scheduler as `transport_error`/`ReadTimeout` attempts. They stand as timeout attempts. E026 TrollLLM a2 was ok.
- **E023 Sol a2:** no record exists, because the call never returns. When the process is stopped, it is recorded post hoc as a `transport_error`/`ReadTimeout` attempt with `deadline_enforced_post_hoc=true`. The attribution is clean: the intent line, the attempt number and the issue time are all known, and 240 s had passed long before.
- **Calls in flight at shutdown:** the scheduler is stopped with SIGTERM, then the operator waits more than 120 s for these calls to finish and write. If one is still unanswered after its deadline, it is recorded the same way (post-hoc `ReadTimeout`). If a call cannot be attributed cleanly, it is voided with reason `hung_connection_no_deadline_2026-11-10`.

## Implementation

`deadline_http.py`: `DeadlineSession.post` runs each request on a fresh connection with `stream=True` and reads the body in chunks against the wall-clock deadline. The read timeout passed to `requests` is unchanged. A watchdog thread enforces the same deadline on the connect/headers phase. On expiry it closes the response and session and raises `requests.exceptions.ReadTimeout`, which the unchanged `post_once` and `sol_review.post` record as `transport_error`/`ReadTimeout`.

`parallel_eval.py` installs it under the existing `CapSess` (flag `--wall-deadline`). Old code is in `archive_pre_7e3/`; SHAs are in `addendum7e3_code.sha256`. Logs go to `run16_7e3_*`.
