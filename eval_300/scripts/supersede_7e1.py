"""Addendum 7e1: key-level supersede records (append-only, nothing deleted) for Claude-low voter keys,
all not-yet-superseded Sol keys (7e high-effort), and 7d Sol-as-4th t4 keys. No content read."""
import json, sys, time, collections
from pathlib import Path
import run_eval as E
C = Path(sys.argv[1]); live = "--apply" in sys.argv
R = "design_7e1_user_decision_2026-11-10"; ts = time.time(); out = collections.Counter()
SEL = (("voters", lambda r: r.get("requested_model") == "ag/claude-sonnet-5-5-low"),
       ("sol", lambda r: True),
       ("t4", lambda r: r.get("requested_model") == "cx/gpt-6.1-sol"))
for stage, sel in SEL:
    p = C / f"{stage}_calls.jsonl"; rs = E.read(p)
    already = {r["cache_key"] for r in rs if r.get("superseded")}
    keys = {}
    for r in rs:
        if not E.is_void_record(r) and sel(r) and r["cache_key"] not in already:
            keys.setdefault(r["cache_key"], r)
    for k, r in keys.items():
        rec = {"cache_key": k, "requested_model": r.get("requested_model"), "item_id": r.get("item_id"), "stage": stage,
               "status": "voided", "voided": True, "superseded": True, "void_scope": "key", "void_reason": R,
               "n_call_records": sum(1 for x in rs if x["cache_key"] == k), "addendum": "7e1", "ts": ts,
               "note": "Addendum 7e1: key-level supersede (all attempts). Not used for the main result; not counted in caps. Kept, never deleted."}
        if live: E.app(p, rec)
    out[stage + "_keys"] = len(keys); out[stage + "_records"] = sum(1 for x in rs if x["cache_key"] in keys)
print(dict(out))
