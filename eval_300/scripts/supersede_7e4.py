"""Addendum 7e4: key-level supersede records for (1) all ag/gemini-3.8-flash-low and trollllm/deepseek-v4-1-flash voter keys,
(2) all still-active Sol keys (7e2 voter set; their input contained those votes). Append-only; nothing deleted; no content read.
t4 keys are blind (voter prompt + sentence) and are handled by the 7e2 reuse rule (decided after 7e4 stage 2, before scoring)."""
import json, sys, time, collections
from pathlib import Path
import run_eval as E
C = Path(sys.argv[1]); live = "--apply" in sys.argv; ts = time.time(); out = collections.Counter()
R = "design_7e4_user_decision_2026-11-11"
OLD = ("ag/gemini-3.8-flash-low", "trollllm/deepseek-v4-1-flash")
SEL = (("voters", lambda r: r.get("requested_model") in OLD), ("sol", lambda r: True))
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
               "n_call_records": sum(1 for x in rs if x["cache_key"] == k), "addendum": "7e4", "ts": ts,
               "note": "Addendum 7e4: key-level supersede (all attempts). Not used for the main result; not counted in caps. Kept, never deleted."}
        if live: E.app(p, rec)
    by = collections.Counter(r.get("requested_model") for r in keys.values())
    out[stage + "_keys"] = len(keys)
    out[stage + "_records"] = sum(1 for x in rs if x["cache_key"] in keys and not E.is_void_record(x))
    for m, n in by.items(): out[f"{stage}_keys:{m}"] = n
    for m in set(by): out[f"{stage}_records:{m}"] = sum(1 for x in rs if x["cache_key"] in keys and not E.is_void_record(x) and x.get("requested_model") == m)
print(json.dumps(dict(out), indent=1)); print("APPLIED" if live else "DRY")
