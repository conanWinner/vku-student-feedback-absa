"""Addendum 7e2: (1) per-attempt voids for the six oc free-quota 429 attempts; (2) key-level supersede records for the
oc GLM / oc DeepSeek voter keys and all still-active (7e1 Sol-medium) Sol keys. Append-only; no content read."""
import json, sys, time, collections
from pathlib import Path
import run_eval as E
C = Path(sys.argv[1]); live = "--apply" in sys.argv; ts = time.time(); out = collections.Counter()
p = C / "voters_calls.jsonl"; rs = E.read(p)
for r in rs:
    if (not E.is_void_record(r) and r.get("http_status") == 429 and r.get("requested_model", "").startswith("oc/")
            and (r["item_id"], r["requested_model"]) in {("E012", "oc/glm-5.3-flash-free"), ("E022", "oc/deepseek-v4.1-flash-free")}):
        a = r.get("attempt") or 1
        rec = {"cache_key": r["cache_key"], "requested_model": r["requested_model"], "item_id": r["item_id"], "stage": "voters",
               "attempt": a, "void_attempt": a, "status": "voided", "voided": True, "void_reason": "oc_free_quota_429_2026-11-10",
               "voided_status": r.get("status"), "voided_http_status": 429, "addendum": "7e2", "ts": ts,
               "note": "Addendum 7e2: OpenCode free-quota 429 (FreeUsageLimitError). Not a vote; does not count toward the retry cap."}
        if live: E.app(p, rec)
        out["void_429"] += 1
R = "design_7e2_user_decision_2026-11-10"
SEL = (("voters", lambda r: r.get("requested_model") in ("oc/glm-5.3-flash-free", "oc/deepseek-v4.1-flash-free")),
       ("sol", lambda r: True))
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
               "n_call_records": sum(1 for x in rs if x["cache_key"] == k), "addendum": "7e2", "ts": ts,
               "note": "Addendum 7e2: key-level supersede (all attempts). Not used for the main result; not counted in caps. Kept, never deleted."}
        if live: E.app(p, rec)
    out[stage + "_keys"] = len(keys); out[stage + "_records"] = sum(1 for x in rs if x["cache_key"] in keys and not E.is_void_record(x))
print(dict(out))
