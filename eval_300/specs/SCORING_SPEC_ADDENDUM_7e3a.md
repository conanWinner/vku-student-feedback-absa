# Addendum 7e.3a: factual note to ADDENDUM_7e3 (SHA 1b36d5cd3992735187f4e5501d13562d986eae21d711ae938378ab0b018ec1b7). Written after PID 757648 stopped, BEFORE the 7e.3 restart and BEFORE any scoring.

7e.3 stated that Sol E023 attempt 2 was still hung, and it was written while that call was still open. In fact the call ended by itself at 22:53:31 UTC+7, about 745 s after it was issued at 22:41:06, and the old scheduler recorded it as `transport_error`/`ReadTimeout`. Attempt 3 then returned ok at 22:53:49.

So **all three calls hung at 22:41 were recorded by the scheduler itself** as `transport_error`/`ReadTimeout` timeout attempts, and they count under the retry rule exactly as 7e.3 specifies:
- Gemini-low E027 a1 (about 620 s)
- TrollLLM E026 a1 (about 625 s)
- Sol E023 a2 (about 745 s)

**No post-hoc records and no voids were needed.**

The scheduler was stopped with SIGTERM at about 22:54 UTC+7 and drained cleanly. There are 0 voter or Sol orphans. Two t4 jobs are outstanding (expected): E023, plus the earlier export 7bfbca78…. Rules are unchanged.

Side note: the E023 t4 job was exported while E023's Sol attempt 3 was in flight, because `job_settled` counts an in-flight intent as an attempt. t4 is blind, so this is harmless. Under the 7e.2 reuse rule that job is used only if E023 still has open cells; otherwise it is superseded before scoring.
