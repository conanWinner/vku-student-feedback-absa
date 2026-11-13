"""Addendum 7e: append key-level supersede records for Gemini voter keys and all pre-7e Sol keys. Append-only. No content read."""
import json, sys, time, collections
from pathlib import Path
import run_eval as E
C = Path(sys.argv[1]); live = "--apply" in sys.argv
R = "voter3_replaced_by_deepseek_user_decision_2026-11-10"; ts = time.time(); out = collections.Counter()
for stage, sel in (("voters", lambda r: r.get("requested_model") == "ag/gemini-3.8-flash-high"), ("sol", lambda r: True)):
    p = C / f"{stage}_calls.jsonl"; rs = E.read(p)
    already = {r["cache_key"] for r in rs if r.get("superseded")}
    keys = {}
    for r in rs:
        if sel(r) and not r.get("superseded") and r["cache_key"] not in already:
            keys.setdefault(r["cache_key"], r)
    for k, r in keys.items():
        rec = {"cache_key": k, "requested_model": r.get("requested_model"), "item_id": r.get("item_id"), "stage": stage,
               "status": "voided", "voided": True, "superseded": True, "void_scope": "key", "void_reason": R,
               "n_call_records": sum(1 for x in rs if x["cache_key"] == k), "addendum": "7e", "ts": ts,
               "note": "Addendum 7e: key-level supersede (all attempts). Not used for the main result; not counted in caps. Record kept, never deleted."}
        if live: E.app(p, rec)
        out[stage] += 1
    out[stage + "_records_covered"] = sum(1 for x in rs if x["cache_key"] in keys)
print(dict(out))
