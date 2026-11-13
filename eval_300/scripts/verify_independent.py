"""Independent re-computation (does NOT import score.py / run_eval.py). Joins journals by (item_id, model)."""
import json, math, re, collections, csv
from pathlib import Path
B = Path(__file__).resolve().parent; R = B.parent
ASP = ["ky_nang_giang_day","hanh_vi","de_xuat","bai_tap","chuong_trinh_hoc","kien_thuc","kinh_nghiem","cung_cap_tai_lieu","thiet_bi_day_hoc","cham_diem","noi_chung"]
VOT = ["cx/gpt-6-luna","cx/gpt-5.6-luna","cx/gpt-5.6-terra"]
def wil(k, n, z=1.96):
    if not n: return None
    p = k/n; den = 1+z*z/n; mid = (p+z*z/(2*n))/den; half = z/den*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return [round(100*p,1), round(max(0,100*(mid-half)),1), round(min(100,100*(mid+half)),1)]
def jl(p): return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
items = json.load(open(B/"items.json"))
def first_ok(model, path):
    out = {}; seen = collections.defaultdict(list)
    for r in jl(path):
        if r.get("requested_model") == model: seen[r["item_id"]].append(r)
    for iid, rs in seen.items():
        assert not any(r.get("status") == "voided" for r in rs)
        ok = [r for r in rs if r["status"] == "ok"]
        if ok: out[iid] = ok[0]
    return out, seen
V = {m: first_ok(m, B/"cache/voters_calls.jsonl")[0] for m in VOT}
SOL, solall = first_ok("cx/gpt-6-sol", B/"cache/sol_calls.jsonl")
T4 = first_ok("claude-code/claude-sonnet-5-5-medium", B/"cache/t4_calls.jsonl")[0]
assert all(r["returned_model"] == "gpt-6-sol" for r in SOL.values())
def asp(ann): return {x["aspect"]: x["decision"] for x in ann["aspects"]}
fin = {}; routed = set()
for it in items:
    i = it["item_id"]; vv = {m: asp(V[m][i]["annotation"]) for m in VOT if i in V[m]}
    unan = len(vv) == 3 and all(len({vv[m][a] for m in VOT}) == 1 for a in ASP)
    if not unan: routed.add(i)
    sol = {x["aspect"]: x for x in SOL[i]["review"]["aspects"]} if i in SOL else None
    t4 = asp(T4[i]["annotation"]) if i in T4 else None
    for a in ASP:
        decs = [vv[m][a] for m in vv]
        if unan: fin[(i,a)] = (decs[0], "unanimous"); continue
        assert sol is not None
        c = collections.Counter(decs).most_common(1)[0]; maj = c[0] if len(decs) >= 2 and c[1] >= 2 and c[1] > len(decs)/2 else None
        s = sol[a]
        if maj is not None and s["decision"] == maj and s["confidence"] in ("high","medium") and maj not in ("abstain","ambiguous"):
            fin[(i,a)] = (maj, "sol_resolved"); continue
        pool = [("v",d) for d in decs] + [("s", s["decision"])] + ([("t", t4[a])] if t4 else [])
        cc = collections.Counter(d for _,d in pool).most_common()
        top, n = cc[0]; uniq = len(cc) == 1 or cc[1][1] < n; sup = {w for w,d in pool if d == top}
        if n >= 3 and uniq and top in ("absent","positive","negative","neutral") and sup & {"s","t"}: fin[(i,a)] = (top, "tiebreak_resolved")
        else: fin[(i,a)] = ("unresolved","unresolved")
out = {"routed_sentences": len(routed), "sol_ok": len(SOL), "t4_ok": len(T4), "votes_ok": {m: len(V[m]) for m in VOT},
       "coverage_3300": dict(collections.Counter(s for _,s in fin.values()))}
# 7e6 fallback, independent loader
def old(coll, cid, text):
    fn = "validation.csv" if coll == "validation_final" else "train" + coll.split("_")[1] + ".csv"
    labs = {}; texts = set()
    with open(B/"old_labels_7e6/Final_Data"/fn, encoding="utf-8", newline="") as h:
        for r in csv.DictReader(h):
            if r["id"].strip() == cid: texts.add(r["text"]); labs[r["aspect"].strip()] = r["sentiment"].strip()
    assert texts == {text}, (coll, cid)
    return labs
olds = {it["item_id"]: old(it["collection"], it["csv_id"], it["sentence"]) for it in items}
fin6 = {k: ((olds[k[0]].get(k[1], "absent"), "fallback") if s == "unresolved" else (d, s)) for k,(d,s) in fin.items()}
# human reference + policy rule written from the spec text
k2i = {(it["collection"], it["csv_id"]): it for it in items}
H = collections.defaultdict(set); notes = collections.defaultdict(set)
for r in jl(R/"human_review_db/human_reviewed_segments.jsonl"):
    k = (r["_collection"], r["csv_id"])
    if k in k2i: H[(k2i[k]["item_id"], r["user_aspect"])].add(r["user_sentiment"]); notes[(k2i[k]["item_id"], r["user_aspect"])].add(r["note"])
SUGW = r"(nên|cần|mong|đề nghị|hy vọng|hi vọng|hãy|hạn chế|bổ sung|thêm|nhiều hơn|cụ thể hơn|rõ hơn|chậm lại|giảm|tăng)"
CRW = r"(không|chưa|kém|tệ|chán|khó hiểu|khó|dở|mờ|hư|hỏng|ồn|nóng|buồn ngủ|lan man|thiếu|ít|quá|hơi|nhàm|tẻ nhạt|qua loa|khó chịu|bất công|trễ|muộn|cũ)"
SUBJ = {"thầy","cô","giảng viên","gv","em","sinh viên","sv","trường","khoa","môn","mình","chúng em","các thầy","các cô"}
def sugg_only(s):
    s = s.lower(); cues = set(m.group(2) for m in re.finditer(r"(?=(^|\s)" + SUGW + r"(\s|$|[,.]))", s))
    if not cues: return False
    if cues == {"nên"}:
        t = s.split(); ok = False
        for j, w in enumerate(t):
            if w == "nên" and (j == 0 or t[j-1] in SUBJ or " ".join(t[max(0,j-2):j]) in SUBJ): ok = True
        if not ok: return False
    return not re.search(r"(^|\s)" + CRW + r"(\s|$|[,.])", s)
sent = {it["item_id"]: it["sentence"] for it in items}
cells = [(i,a,next(iter(h))) for (i,a),h in H.items() if len(h) == 1]
pol = {(i,a) for i,a,h in cells if h == "negative" and sugg_only(sent[i])}
def em(F, C): return wil(sum(F[(i,a)][0] == h for i,a,h in C), len(C))
excl = [c for c in cells if (c[0],c[1]) not in pol]
PRES = ("positive","negative","neutral")
def det(F, C): return wil(sum(F[(i,a)][0] in PRES for i,a,h in C), len(C))
def pgd(F, C):
    D = [c for c in C if F[(c[0],c[1])][0] in PRES]; return wil(sum(F[(i,a)][0] == h for i,a,h in D), len(D))
out.update({"n_cells": len(cells), "policy_cells": len(pol), "sugg_only_sentences": sum(sugg_only(s) for s in sent.values()),
  "7e5": {"exact_all": em(fin, cells), "exact_excl": em(fin, excl), "det_all": det(fin, cells), "det_excl": det(fin, excl), "pgd_all": pgd(fin, cells), "pgd_excl": pgd(fin, excl),
          "cov_ref": wil(sum(fin[(i,a)][1] != "unresolved" for i,a,h in cells), len(cells)),
          "resolved_only_all": em(fin, [c for c in cells if fin[(c[0],c[1])][1] != "unresolved"]),
          "resolved_only_excl": em(fin, [c for c in excl if fin[(c[0],c[1])][1] != "unresolved"]),
          "per_stage": {g: [len([c for c in cells if fin[(c[0],c[1])][1] == g]), em(fin, [c for c in cells if fin[(c[0],c[1])][1] == g])] for g in ("unanimous","sol_resolved","tiebreak_resolved","unresolved")},
          "per_note": {g: em(fin, [c for c in cells if ("Đã check tay" in notes[(c[0],c[1])]) == (g == "checked")]) for g in ("checked","kept_ai")},
          "per_aspect": {a: [len([c for c in cells if c[1]==a]), em(fin, [c for c in cells if c[1]==a]), det(fin,[c for c in cells if c[1]==a])] for a in ASP},
          "per_aspect_excl": {a: em(fin, [c for c in excl if c[1]==a]) for a in ASP},
          "voter_vs_human_all": {m: wil(sum(i in V[m] and asp(V[m][i]["annotation"])[a] == h for i,a,h in cells), len(cells)) for m in VOT},
          "voter_vs_human_excl": {m: wil(sum(i in V[m] and asp(V[m][i]["annotation"])[a] == h for i,a,h in excl), len(excl)) for m in VOT},
          "confusion": dict(collections.Counter(f"{h}->{fin[(i,a)][0]}" for i,a,h in cells)),
          "present_no_human": sum(1 for k,(d,s) in fin.items() if d in PRES and k not in H)},
  "7e6": {"exact_all": em(fin6, cells), "exact_excl": em(fin6, excl), "det_all": det(fin6, cells), "det_excl": det(fin6, excl), "pgd_all": pgd(fin6, cells), "pgd_excl": pgd(fin6, excl),
          "cov_ref": wil(sum(fin6[(i,a)][1] != "unresolved" for i,a,h in cells), len(cells)),
          "fallback_labels": dict(collections.Counter(d for (d,s) in fin6.values() if s == "fallback")),
          "fallback_on_ref": [len([c for c in cells if fin6[(c[0],c[1])][1]=="fallback"]), em(fin6, [c for c in cells if fin6[(c[0],c[1])][1]=="fallback"])],
          "old_release_vs_human_all433": wil(sum(olds[i].get(a,"absent") == h for i,a,h in cells), len(cells))}})
# consensus agreement (secondary)
res_c = [k for k,(d,s) in fin.items() if s != "unresolved"]
out["consensus"] = {m: [len(res_c), wil(sum(asp(V[m][k[0]]["annotation"])[k[1]] == fin[k][0] for k in res_c if k[0] in V[m]), len([k for k in res_c if k[0] in V[m]]))] for m in VOT}
out["consensus"]["sol"] = wil(sum(next(x for x in SOL[k[0]]["review"]["aspects"] if x["aspect"]==k[1])["decision"] == fin[k][0] for k in res_c if k[0] in SOL), sum(1 for k in res_c if k[0] in SOL))
out["consensus"]["t4"] = wil(sum(asp(T4[k[0]]["annotation"])[k[1]] == fin[k][0] for k in res_c if k[0] in T4), sum(1 for k in res_c if k[0] in T4))
pres = [k for k in res_c if fin[k][0] in PRES]
out["consensus_present"] = {m: [len(pres), wil(sum(asp(V[m][k[0]]["annotation"])[k[1]] == fin[k][0] for k in pres if k[0] in V[m]), len([k for k in pres if k[0] in V[m]]))] for m in VOT}
json.dump(out, open(B/"verify_independent.json","w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False))
