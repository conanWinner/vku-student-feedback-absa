# Addendum 7c.1 (operational note to ADDENDUM_7c, SHA dc7607960ba3c94b724f872a64a0747af84e8685a906f4fd1e9933d1b6d8d7c3). Written after PID 706319 drained, BEFORE the 7c restart and BEFORE any scoring.

Date: 2026-11-10, about 20:42 UTC+7. Pacing only; nothing about what counts as a vote changes.

1. **xai lane hold.** The last t4 calls of PID 706319 (E120 attempts 1–3) returned HTTP 404 `No active credentials for provider: xai` from 9router, and a single non-vote health check at 20:38:57 UTC+7 (`probe_log_7c_xai.jsonl`, dummy text, outside caps) returned the same. To avoid burning t4 attempts on a router credential outage, the 7c restart uses `--hold-lanes xai`: the xai lane issues nothing (no attempts consumed) until it is restarted without the hold after xai credentials are restored. The E120 t4 attempts already burned stay in the journal as-is (not voided by this note; any decision on them is left to a later addendum written before scoring).
2. **Gemini pre-restart probe.** One shared-budget probe (`probe3.py`, n=19 of 36, 20:39:06 UTC+7) on `ag/gemini-3.8-flash-high`: HTTP 200, returned `gemini-3.8-flash-n`, healthy. Non-vote.
3. Flag `--hold-lanes <lanes>` added to `parallel_eval.py`; SHAs in `addendum7c_code.sha256`.
