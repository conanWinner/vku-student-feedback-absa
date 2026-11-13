"""Score eval_300 per SCORING_SPEC.md (d9f76dd0) + ADDENDUM_1 (5ff85c81)."""
import collections, csv, json, math, re, sys
from pathlib import Path
OUT = Path(__file__).resolve().parent; ROOT = OUT.parent
sys.path.insert(0, str(OUT))
import run_eval as E
ASP = E.ASPECTS; PRES = ("positive", "negative", "neutral"); USABLE = ("absent",) + PRES
def wilson(k, n, z=1.96):
    if n == 0: return None
    p = k / n; d = 1 + z*z/n; c = (p + z*z/(2*n)) / d; h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return [round(100*p, 1), round(100*(c-h), 1), round(100*(c+h), 1)]
SUG = re.compile(r"(^|\s)(nên|cần|mong|đề nghị|hy vọng|hi vọng|hãy|hạn chế|bổ sung|thêm|nhiều hơn|cụ thể hơn|rõ hơn|chậm lại|giảm|tăng)(\s|$|[,.])")
CRIT = re.compile(r"(^|\s)(không|chưa|kém|tệ|chán|khó hiểu|khó|dở|mờ|hư|hỏng|ồn|nóng|buồn ngủ|lan man|thiếu|ít|quá|hơi|nhàm|tẻ nhạt|qua loa|khó chịu|bất công|trễ|muộn|cũ)(\s|$|[,.])")
SUBJ = {"thầy","cô","giảng viên","gv","em","sinh viên","sv","trường","khoa","môn","mình","chúng em","các thầy","các cô"}
def has_suggestion(s):
    s = s.lower(); cues = [m.group(2) for m in re.finditer(r"(?=(^|\s)(nên|cần|mong|đề nghị|hy vọng|hi vọng|hãy|hạn chế|bổ sung|thêm|nhiều hơn|cụ thể hơn|rõ hơn|chậm lại|giảm|tăng)(\s|$|[,.]))", s)]
    if not cues: return False
    if set(cues) == {"nên"}:
        toks = s.split(); ok = False
        for i, t in enumerate(toks):
            if t != "nên": continue
            if i == 0: ok = True; break
            prev1 = toks[i-1]; prev2 = " ".join(toks[max(0, i-2):i])
            if prev1 in SUBJ or prev2 in SUBJ: ok = True; break
        return ok
    return True
def suggestion_only(s): return has_suggestion(s) and not CRIT.search(s.lower())
def main():
    items = json.loads((OUT / "items.json").read_text())
    key2item = {(x["collection"], x["csv_id"]): x for x in items}
    R = [json.loads(l) for l in (ROOT / "human_review_db/human_reviewed_segments.jsonl").read_text().splitlines() if l.strip()]
    human = collections.defaultdict(lambda: {"labels": set(), "notes": set()})
    for r in R:
        k = (r["_collection"], r["csv_id"])
        if k in key2item:
            h = human[(key2item[k]["item_id"], r["user_aspect"])]; h["labels"].add(r["user_sentiment"]); h["notes"].add(r["note"])
    V = E.voter_votes()
    sj = {j["item_id"]: j for j in E.sol_jobs()}
    sol_by = {k: E.first_ok_or_last(v) for k, v in E.grouped_calls(E.C / "sol_calls.jsonl").items()}
    t4_by = {k: E.first_ok_or_last(v) for k, v in E.grouped_calls(E.C / "t4_calls.jsonl").items()}
    sol_bad_name = []
    final = {}
    for it in items:
        iid = it["item_id"]; v = V[iid]
        rec = sol_by.get(sj[iid]["cache_key"]) if iid in sj else None
        if rec and rec.get("status") == "ok" and rec.get("returned_model") != E.SOL_EXPECT:
            sol_bad_name.append(iid); rec = {**rec, "status": "model_mismatch"}
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
                lab, n = cnt[0]; uniq = len(cnt) < 2 or cnt[1][1] < n
                sup = {w for w, d in votes if d == lab}
                if n >= 3 and uniq and lab in USABLE and ({"sol", "t4"} & sup):
                    final[(iid, a)] = (lab, "tiebreak_resolved"); continue
            final[(iid, a)] = ("unresolved", "unresolved")
    cells = []; dropped = 0
    sent = {x["item_id"]: x["sentence"] for x in items}
    for (iid, a), h in human.items():
        if len(h["labels"]) != 1: dropped += 1; continue
        hl = next(iter(h["labels"])); d, src = final[(iid, a)]
        note = "checked" if "Đã check tay" in h["notes"] else "kept_ai"
        cells.append({"item_id": iid, "aspect": a, "human": hl, "system": d, "source": src, "note": note,
                      "policy_cell": hl == "negative" and suggestion_only(sent[iid]), "sentence": sent[iid],
                      **{f"voter:{m}": next((x["aspects"][ASP.index(a)]["decision"] for mm, x in V[iid].items() if mm == m), "no_vote") for m in E.VOTERS}})
    def metrics(S, cond=False):
        if cond: S = [c for c in S if c["system"] != "unresolved"]
        n = len(S); det = [c for c in S if c["system"] in PRES]
        return {"n": n, "aspect_recall": wilson(len(det), n), "polarity_acc_given_detection": wilson(sum(c["system"] == c["human"] for c in det), len(det)),
                "exact_match": wilson(sum(c["system"] == c["human"] for c in S), n), "n_detected": len(det), "n_exact": sum(c["system"] == c["human"] for c in S)}
    def block(S):
        return {"main": metrics(S), "coverage_conditional": metrics(S, True), "coverage": wilson(sum(c["system"] != "unresolved" for c in S), len(S))}
    allc = cells; excl = [c for c in cells if not c["policy_cell"]]
    res = {"spec_sha": "d9f76dd03248998d1bbf4c5476c57d0d46823c71f460b945001bcd33f8c3dd2c", "addendum_sha": "5ff85c810cf9bb6eac3b81376e544160c6b04b04bf80faf6f62397f52bdfae29",
           "NOT_GOLD_reference_is_human_verified_AI_anchored": True, "n_cells": len(cells), "dropped_conflicting_cells": dropped,
           "policy_cells": sum(c["policy_cell"] for c in cells), "sentences_suggestion_only": sum(suggestion_only(s) for s in sent.values()),
           "a_all": block(allc), "b_excl_policy": block(excl),
           "per_aspect_all": {a: block([c for c in allc if c["aspect"] == a]) for a in ASP if any(c["aspect"] == a for c in allc)},
           "per_aspect_excl": {a: block([c for c in excl if c["aspect"] == a]) for a in ASP if any(c["aspect"] == a for c in excl)},
           "per_note_all": {g: block([c for c in allc if c["note"] == g]) for g in ("checked", "kept_ai")},
           "per_note_excl": {g: block([c for c in excl if c["note"] == g]) for g in ("checked", "kept_ai")},
           "per_stage_all": {g: metrics([c for c in allc if c["source"] == g]) for g in ("unanimous", "sol_resolved", "tiebreak_resolved", "unresolved")},
           "per_stage_excl": {g: metrics([c for c in excl if c["source"] == g]) for g in ("unanimous", "sol_resolved", "tiebreak_resolved", "unresolved")},
           "single_voter_exact_all": {m: wilson(sum(c[f"voter:{m}"] == c["human"] for c in allc), len(allc)) for m in E.VOTERS},
           "single_voter_exact_excl": {m: wilson(sum(c[f"voter:{m}"] == c["human"] for c in excl), len(excl)) for m in E.VOTERS},
           "confusion_all": {f"{h}->{s}": n for (h, s), n in sorted(collections.Counter((c["human"], c["system"]) for c in allc).items())},
           "system_present_no_human_row": sum(1 for (iid, a), (d, _) in final.items() if d in PRES and (iid, a) not in human),
           "final_cells_by_source_all_3300": dict(collections.Counter(s for _, s in final.values())),
           "sol_name_mismatch": sol_bad_name}
    st = collections.Counter(); 
    for stage in ("voters", "sol", "t4"):
        for r in E.read(E.C / f"{stage}_calls.jsonl"): st[f"{stage}|{r['requested_model']}|{r['status']}"] += 1
    res["call_status"] = dict(st); res["calls_issued"] = {s: len(E.read(E.C / f"{s}_intent.jsonl")) for s in ("voters", "sol", "t4")}
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    with (OUT / "cells_scored.csv").open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(cells[0])); w.writeheader(); w.writerows(cells)
    print(json.dumps({k: res[k] for k in ("n_cells", "policy_cells", "a_all", "b_excl_policy", "per_stage_all", "single_voter_exact_all", "call_status", "calls_issued", "final_cells_by_source_all_3300", "sol_name_mismatch")}, ensure_ascii=False, indent=1))
if __name__ == "__main__": main()
