"""SECONDARY, exploratory (not pre-registered): per-model agreement with the FINAL pipeline consensus.
Consensus is computed exactly as score.py (same code path is re-imported). NOT GOLD; voters are part of the
consensus, so agreement is partly circular. Suggestion-only sentences = score.suggestion_only (spec rule)."""
import collections, json, sys
from pathlib import Path
OUT = Path(__file__).resolve().parent; sys.path.insert(0, str(OUT))
import run_eval as E, score as S
ASP = E.ASPECTS
items = json.loads((OUT / "items.json").read_text())
V = E.voter_votes(); sj = {j["item_id"]: j for j in E.sol_jobs()}
sol_by = {k: E.first_ok_or_last(v) for k, v in E.grouped_calls(E.C / "sol_calls.jsonl").items()}
t4_by = {k: E.first_ok_or_last(v) for k, v in E.grouped_calls(E.C / "t4_calls.jsonl").items()}
rows = []
for it in items:
    iid = it["item_id"]; v = V[iid]
    rec = sol_by.get(sj[iid]["cache_key"]) if iid in sj else None
    rv = {x["aspect"]: x for x in rec["review"]["aspects"]} if rec and rec.get("status") == "ok" and rec.get("returned_model") == E.SOL_EXPECT else None
    tr = t4_by.get(E.cache_key(it["sentence"], E.T4, E.PSHA))
    tv = {x["aspect"]: x for x in tr["annotation"]["aspects"]} if tr and tr["status"] == "ok" else None
    for k, a in enumerate(ASP):
        decs = [x["aspects"][k]["decision"] for x in v.values()]
        if iid not in sj or (rv is None and len(decs) == 3 and len(set(decs)) == 1): fin, src = decs[0], "unanimous"
        else:
            fin, src = None, None
            if rv is not None:
                m = E.majority(decs); s = rv[a]
                if m is not None and s["decision"] == m and s["confidence"] in ("high", "medium") and s["decision"] not in ("abstain", "ambiguous"): fin, src = m, "sol_resolved"
            if fin is None:
                votes = [("voter", d) for d in decs] + ([("sol", rv[a]["decision"])] if rv else []) + ([("t4", tv[a]["decision"])] if tv else [])
                cnt = collections.Counter(d for _, d in votes).most_common(); fin, src = "unresolved", "unresolved"
                if cnt:
                    lab, n = cnt[0]; uniq = len(cnt) < 2 or cnt[1][1] < n; sup = {w for w, d in votes if d == lab}
                    if n >= 3 and uniq and lab in S.USABLE and ({"sol", "t4"} & sup): fin, src = lab, "tiebreak_resolved"
        r = {"item_id": iid, "aspect": a, "final": fin, "source": src, "sugg_only": S.suggestion_only(it["sentence"]),
             "sol": rv[a]["decision"] if rv else None, "t4": tv[a]["decision"] if tv else None}
        for m in E.VOTERS: r[m] = v[m]["aspects"][k]["decision"] if m in v else "no_vote"
        rows.append(r)
def agree(R, m, present_only=False):
    R = [r for r in R if r["final"] != "unresolved" and r[m] is not None]
    if present_only: R = [r for r in R if r["final"] in S.PRES]
    return {"n": len(R), "agree": S.wilson(sum(r[m] == r["final"] for r in R), len(R))}
res = {"NOTE": "secondary exploratory; consensus is NOT GOLD; voters contribute to consensus (circular)",
       "coverage_3300": dict(collections.Counter(r["source"] for r in rows)),
       "suggestion_only_sentences": sum(S.suggestion_only(i["sentence"]) for i in items)}
for tag, R in (("all", rows), ("excl_sugg_only_sentences", [r for r in rows if not r["sugg_only"]])):
    res[tag] = {"coverage": dict(collections.Counter(r["source"] for r in R)), "n_cells": len(R)}
    for m in list(E.VOTERS) + ["sol", "t4"]:
        res[tag][m] = {"all_cells": agree(R, m), "consensus_present_cells": agree(R, m, True)}
res["per_aspect_voter_agree_all"] = {a: {m: agree([r for r in rows if r["aspect"] == a], m)["agree"] for m in E.VOTERS} for a in ASP}
res["per_aspect_coverage"] = {a: dict(collections.Counter(r["source"] for r in rows if r["aspect"] == a)) for a in ASP}
res["final_label_dist"] = dict(collections.Counter(r["final"] for r in rows))
(OUT / "consensus_agreement.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
