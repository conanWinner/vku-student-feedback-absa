"""Addendum 7e.6 (POST HOC, secondary): unresolved 7e.5 cells -> old released label.
Does not modify score.py, journals, data, or results.json. NOT GOLD."""
import collections, csv, json, sys
from pathlib import Path
OUT = Path(__file__).resolve().parent; ROOT = OUT.parent; sys.path.insert(0, str(OUT))
sys.path.insert(0, str(ROOT / "relabel_pilot_bundle_v3"))
import run_eval as E, score as S
from review_pilot.corpus import dataset_hash
from review_pilot.schema import old_label_decision
ASP = E.ASPECTS; OLD_DIR = OUT / "old_labels_7e6" / "Final_Data"
EXPECT_DS = "c13e760bb2d47295b5dea3ddda4e3d1e65f15846d2afece54ec9531db69643f1"
assert dataset_hash(OLD_DIR) == EXPECT_DS, "old-release dataset hash mismatch"
def load_old(name):
    g = collections.defaultdict(lambda: {"text": set(), "labels": {}})
    with (OLD_DIR / name).open(encoding="utf-8", newline="") as h:
        for r in csv.DictReader(h):
            x = g[r["id"].strip()]; x["text"].add(r["text"]); a, p = r["aspect"].strip(), r["sentiment"].strip()
            if a in x["labels"] and x["labels"][a] != p: raise ValueError(f"conflict {name} {r['id']} {a}")
            x["labels"][a] = p
    return g
def file_of(coll): return "validation.csv" if coll == "validation_final" else coll.replace("_final", "").replace("_", "") + ".csv"
items = json.loads((OUT / "items.json").read_text()); old_cache = {}
# --- 7e.5 final labels: same rule as score.py ---
V = E.voter_votes(); sj = {j["item_id"]: j for j in E.sol_jobs()}
sol_by = {k: E.first_ok_or_last(v) for k, v in E.grouped_calls(E.C / "sol_calls.jsonl").items()}
t4_by = {k: E.first_ok_or_last(v) for k, v in E.grouped_calls(E.C / "t4_calls.jsonl").items()}
final = {}
for it in items:
    iid = it["item_id"]; v = V[iid]
    rec = sol_by.get(sj[iid]["cache_key"]) if iid in sj else None
    if rec and rec.get("status") == "ok" and rec.get("returned_model") != E.SOL_EXPECT: rec = {**rec, "status": "model_mismatch"}
    rv = {x["aspect"]: x for x in rec["review"]["aspects"]} if rec and rec["status"] == "ok" else None
    tr = t4_by.get(E.cache_key(it["sentence"], E.T4, E.PSHA))
    tv = {x["aspect"]: x for x in tr["annotation"]["aspects"]} if tr and tr["status"] == "ok" else None
    for k, a in enumerate(ASP):
        decs = [x["aspects"][k]["decision"] for x in v.values()]
        if iid not in sj: final[(iid, a)] = (decs[0], "unanimous"); continue
        if rv is None and len(decs) == 3 and len(set(decs)) == 1: final[(iid, a)] = (decs[0], "unanimous"); continue
        if rv is not None:
            m = E.majority(decs); s = rv[a]
            if m is not None and s["decision"] == m and s["confidence"] in ("high", "medium") and s["decision"] not in ("abstain", "ambiguous"):
                final[(iid, a)] = (m, "sol_resolved"); continue
        votes = [("voter", d) for d in decs] + ([("sol", rv[a]["decision"])] if rv else []) + ([("t4", tv[a]["decision"])] if tv else [])
        cnt = collections.Counter(d for _, d in votes).most_common()
        if cnt:
            lab, n = cnt[0]; uniq = len(cnt) < 2 or cnt[1][1] < n; sup = {w for w, d in votes if d == lab}
            if n >= 3 and uniq and lab in S.USABLE and ({"sol", "t4"} & sup): final[(iid, a)] = (lab, "tiebreak_resolved"); continue
        final[(iid, a)] = ("unresolved", "unresolved")
# consistency with the primary 7e.5 output
prim = json.loads((OUT / "results.json").read_text())
assert dict(collections.Counter(s for _, s in final.values())) == prim["final_cells_by_source_all_3300"]
# --- apply fallback ---
fb_info = []; final7e6 = {}
for it in items:
    iid = it["item_id"]; fn = file_of(it["collection"])
    if fn not in old_cache: old_cache[fn] = load_old(fn)
    o = old_cache[fn].get(it["csv_id"]); found = o is not None and o["text"] == {it["sentence"]}
    for a in ASP:
        d, src = final[(iid, a)]
        if src == "unresolved":
            if found:
                ol = old_label_decision(o["labels"].get(a)); final7e6[(iid, a)] = (ol, "fallback_old_label")
                fb_info.append({"item_id": iid, "aspect": a, "old_label": ol, "explicit": a in o["labels"]})
            else:
                final7e6[(iid, a)] = ("unresolved", "unresolved"); fb_info.append({"item_id": iid, "aspect": a, "old_label": None, "explicit": False})
        else: final7e6[(iid, a)] = (d, src)
# --- score on human cells (same reference + metrics as score.py) ---
key2item = {(x["collection"], x["csv_id"]): x for x in items}; sent = {x["item_id"]: x["sentence"] for x in items}
human = collections.defaultdict(lambda: {"labels": set(), "notes": set()})
for l in (ROOT / "human_review_db/human_reviewed_segments.jsonl").read_text().splitlines():
    if not l.strip(): continue
    r = json.loads(l); k = (r["_collection"], r["csv_id"])
    if k in key2item: h = human[(key2item[k]["item_id"], r["user_aspect"])]; h["labels"].add(r["user_sentiment"]); h["notes"].add(r["note"])
cells = []
for (iid, a), h in human.items():
    if len(h["labels"]) != 1: continue
    hl = next(iter(h["labels"])); d, src = final7e6[(iid, a)]; d5, src5 = final[(iid, a)]
    cells.append({"item_id": iid, "aspect": a, "human": hl, "system_7e6": d, "source_7e6": src, "system_7e5": d5, "source_7e5": src5,
                  "note": "checked" if "Đã check tay" in h["notes"] else "kept_ai", "policy_cell": hl == "negative" and S.suggestion_only(sent[iid]), "sentence": sent[iid]})
def metrics(C, cond=False):
    if cond: C = [c for c in C if c["system_7e6"] != "unresolved"]
    n = len(C); det = [c for c in C if c["system_7e6"] in S.PRES]; ex = sum(c["system_7e6"] == c["human"] for c in C)
    return {"n": n, "aspect_recall": S.wilson(len(det), n), "polarity_acc_given_detection": S.wilson(sum(c["system_7e6"] == c["human"] for c in det), len(det)),
            "exact_match": S.wilson(ex, n), "n_detected": len(det), "n_exact": ex}
def block(C): return {"main": metrics(C), "coverage_conditional": metrics(C, True), "coverage": S.wilson(sum(c["system_7e6"] != "unresolved" for c in C), len(C))}
excl = [c for c in cells if not c["policy_cell"]]; fbh = [c for c in cells if c["source_7e6"] == "fallback_old_label"]
res = {"POST_HOC": True, "addendum": "SCORING_SPEC_ADDENDUM_7e6.md", "NOT_GOLD": True,
       "WARNING": "old release equals the human-verified reference on this sample (SCORING_SPEC.md); fallback inflates agreement",
       "old_dataset_sha256": EXPECT_DS, "n_unresolved_7e5": len(fb_info),
       "fallback_applied": sum(1 for f in fb_info if f["old_label"] is not None), "fallback_explicit_polarity": sum(f["explicit"] for f in fb_info),
       "fallback_implicit_absent": sum(1 for f in fb_info if f["old_label"] == "absent" and not f["explicit"]),
       "still_unresolved": sum(1 for f in fb_info if f["old_label"] is None),
       "fallback_label_dist": dict(collections.Counter(f["old_label"] for f in fb_info)),
       "final_cells_by_source_all_3300": dict(collections.Counter(s for _, s in final7e6.values())),
       "final_label_dist_all_3300": dict(collections.Counter(d for d, _ in final7e6.values())),
       "n_cells": len(cells), "policy_cells": len(cells) - len(excl),
       "a_all": block(cells), "b_excl_policy": block(excl),
       "fallback_cells_on_human_ref": {"n": len(fbh), "exact": S.wilson(sum(c["system_7e6"] == c["human"] for c in fbh), len(fbh)),
                                       "n_exact": sum(c["system_7e6"] == c["human"] for c in fbh)},
       "per_stage_all": {g: metrics([c for c in cells if c["source_7e6"] == g]) for g in ("unanimous", "sol_resolved", "tiebreak_resolved", "fallback_old_label", "unresolved")},
       "per_aspect_all": {a: block([c for c in cells if c["aspect"] == a]) for a in ASP},
       "per_aspect_excl": {a: block([c for c in excl if c["aspect"] == a]) for a in ASP},
       "per_note_all": {g: block([c for c in cells if c["note"] == g]) for g in ("checked", "kept_ai")}}
(OUT / "results_7e6_fallback.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
with (OUT / "cells_scored_7e6.csv").open("w", encoding="utf-8-sig", newline="") as h:
    w = csv.DictWriter(h, fieldnames=list(cells[0])); w.writeheader(); w.writerows(cells)
with (OUT / "final_labels_7e6.jsonl").open("w", encoding="utf-8") as h:
    for it in items:
        for a in ASP:
            d, s = final7e6[(it["item_id"], a)]; d5, s5 = final[(it["item_id"], a)]
            h.write(json.dumps({"item_id": it["item_id"], "collection": it["collection"], "csv_id": it["csv_id"], "aspect": a,
                                "label_7e6": d, "source_7e6": s, "label_7e5": d5, "source_7e5": s5}, ensure_ascii=False) + "\n")
print(json.dumps({k: res[k] for k in ("n_unresolved_7e5", "fallback_applied", "fallback_explicit_polarity", "fallback_implicit_absent", "still_unresolved",
      "fallback_label_dist", "final_cells_by_source_all_3300", "fallback_cells_on_human_ref", "per_stage_all")}, ensure_ascii=False, indent=1))
for t in ("a_all", "b_excl_policy"): print(t, json.dumps(res[t], ensure_ascii=False))
