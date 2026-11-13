"""eval_300 runner: voters -> Sol -> tiebreak. Human labels are never loaded here."""
import collections, hashlib, json, os, time, random, signal, sys, threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
ROOT = Path("/workspace/relabel-pilot-v3-20261108")
sys.path.insert(0, str(ROOT / "relabel_pilot_bundle_v3")); sys.path.insert(0, str(ROOT / "sol_review"))
from review_pilot.client import post_once, cache_key
from review_pilot.guideline import prompt_sha256
from review_pilot.config import ASPECTS, MODELS
import sol_review as S
OUT = Path(__file__).resolve().parent; C = OUT / "cache"; C.mkdir(exist_ok=True)
T4 = "claude-code/claude-sonnet-5-5-medium"  # ADDENDUM_7e1: remote Claude Code CLI (--effort medium), blind voter prompt; was cx/gpt-6.1-sol (7d), xai/grok-4.7 before
T4_ROUTE = "claude-code-remote"
T4_CLI_MODEL = "claude-sonnet-5-5"; T4_EFFORT = "medium"
S.REASONING_EFFORT = "medium"  # ADDENDUM_7e1: stage-2 Sol medium (was high)
S.MODEL = "cx/gpt-6-sol"  # ADDENDUM_7e5: cx/gpt-6.1-sol blocked by 9router (HTTP 400 "requires a newer version of Codex"); user decision 2026-11-11 06:54 UTC+7
SOL_EXPECT = "gpt-6-sol"; SOL_REFUSED = ("cx/gpt-6.1-sol",)
assert S.MODEL == "cx/gpt-6-sol" and S.MODEL not in SOL_REFUSED
# ADDENDUM_4: Claude voter ag/claude-opus-5-5-high -> ag/claude-sonnet-5-5-low (user request); nothing else changed.
# ADDENDUM_7e: voter 3 ag/gemini-3.8-flash-high -> oc/deepseek-v4.1-flash-free (user decision); caps count active (non-voided/superseded) keys.
# ADDENDUM_7e1: V2 ag/claude-sonnet-5-5-low -> oc/glm-5.3-flash-free (user decision 21:14)
# ADDENDUM_7e2 (FINAL): V2 ag/gemini-3.8-flash-low, V3 trollllm/deepseek-v4-1-flash (oc/* dropped: free quota 429)
# ADDENDUM_7e4: all-Codex voters (TrollLLM provider empty responses; Gemini-low too slow). User decision 2026-11-11 06:24 UTC+7.
VOTERS = ("cx/gpt-6-luna", "cx/gpt-5.6-luna", "cx/gpt-5.6-terra"); TOTAL_CAP = 1500; VOTER_CAP = 900; CONC = int(os.environ.get("EVAL_CONC", "2")); GAP = float(os.environ.get("EVAL_GAP_S", "0"))
PSHA = prompt_sha256()
assert PSHA.startswith("74d0fd7d"), PSHA
SAMPLE = [json.loads(l) for l in (ROOT / "human_review_db/eval_sample_DRAFT.jsonl").read_text().splitlines() if l.strip()]
ITEMS = [{"item_id": f"E{i:03d}", "sentence": s["sentence"]} for i, s in enumerate(SAMPLE, 1)]
(OUT / "items.json").write_text(json.dumps([{**it, "collection": s["collection"], "csv_id": s["csv_id"]} for it, s in zip(ITEMS, SAMPLE)], ensure_ascii=False, indent=1))

def read(p): return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
def app(p, rec):
    with p.open("a", encoding="utf-8") as h:
        h.write(json.dumps(rec, ensure_ascii=False) + "\n"); h.flush(); os.fsync(h.fileno())
def grouped_calls(path):
    by = collections.defaultdict(list)
    for r in read(path):
        by[r["cache_key"]].append(r)
    return by
def is_void_record(r):
    """Addendum 7b: append-only tombstones / unused-but-logged records."""
    return bool(r.get("voided")) or r.get("status") in ("voided", "unused")

def voided_attempts(recs):
    atts = set()
    for r in recs:
        if not is_void_record(r):
            continue
        if r.get("void_attempt") is not None:
            atts.add(r["void_attempt"])
        elif r.get("attempt") is not None:
            atts.add(r["attempt"])
        else:
            for x in recs:
                if not is_void_record(x):
                    atts.add(x.get("attempt") or 1)
    return atts

def usable_call_records(recs):
    """Drop void tombstones and the attempts they exclude. Voided attempts do not count toward the retry cap."""
    if not recs:
        return []
    void_atts = voided_attempts(recs)
    out = []
    for r in recs:
        if is_void_record(r):
            continue
        if (r.get("attempt") or 1) in void_atts:
            continue
        out.append(r)
    return out

def first_ok_or_last(recs):
    """Addendum 5 + 7b: first ok among non-voided attempts; else the last usable record (a non-vote)."""
    recs = usable_call_records(recs)
    if not recs:
        return None
    for r in recs:
        if r.get("status") == "ok":
            return r
    return recs[-1]
def total_issued():
    return sum(len(read(C / f"{s}_intent.jsonl")) for s in ("voters", "sol", "t4"))

def run_stage(stage, jobs, call, cap):
    calls_p, intent_p = C / f"{stage}_calls.jsonl", C / f"{stage}_intent.jsonl"
    seen = {r["cache_key"] for r in read(calls_p)} | {r["cache_key"] for r in read(intent_p)}
    pending = [j for j in jobs if j["cache_key"] not in seen]
    room = min(cap - len(read(intent_p)), TOTAL_CAP - total_issued())
    skipped = pending[max(room, 0):]; pending = pending[:max(room, 0)]
    print(json.dumps({"stage": stage, "jobs": len(jobs), "already": len(jobs) - len(pending) - len(skipped), "pending": len(pending), "over_cap_skipped": len(skipped)}), flush=True)
    key = os.environ.get("NINE_ROUTER_API_KEY", "")
    if not key: raise SystemExit("key not set")
    import requests
    sess = requests.Session(); stop = threading.Event(); lock = threading.Lock()
    signal.signal(signal.SIGTERM, lambda *a: stop.set()); signal.signal(signal.SIGINT, lambda *a: stop.set())
    def one(j):
        with lock: app(intent_p, {"item_id": j["item_id"], "cache_key": j["cache_key"], "model": j["model"], "status": "issued"})
        if GAP: time.sleep(GAP)
        rec = call(sess, j, key); rec["item_id"] = j["item_id"]; rec["requested_model"] = j["model"]
        if key in json.dumps(rec): raise RuntimeError("key in payload")
        return rec
    it = iter(pending); infl = {}; made = 0; consec = 0; window = collections.deque(maxlen=30); stopped = None; mm = collections.Counter()
    with ThreadPoolExecutor(CONC) as pool:
        def sub():
            if stopped or stop.is_set(): return
            j = next(it, None)
            if j: infl[pool.submit(one, j)] = j
        for _ in range(CONC): sub()
        while infl:
            fin, _ = wait(set(infl), return_when=FIRST_COMPLETED)
            for f in fin:
                infl.pop(f); rec = f.result(); app(calls_p, rec); made += 1
                ok = rec["status"] == "ok"; window.append(ok)
                if made % 25 == 0 or not ok:
                    print(json.dumps({"stage": stage, "n": made, "item": rec["item_id"], "model": rec["requested_model"], "status": rec["status"], "err": rec.get("error")}), flush=True)
                if rec["status"] in ("http_error", "transport_error"):
                    consec += 1
                    if rec.get("http_status") in (401, 403): stopped = "auth_or_block"
                    elif consec >= 3: stopped = "3_consecutive_http_transport"
                else: consec = 0
                mm[rec["requested_model"]] = mm[rec["requested_model"]] + 1 if rec["status"] in ("model_mismatch", "parse_error", "http_error") else 0
                if mm[rec["requested_model"]] >= 3: stopped = stopped or f"failure_streak:{rec['requested_model']}"
                if len(window) >= 30 and window.count(False) / len(window) > 0.20: stopped = stopped or "window_failure_gt_20pct"
                sub()
    res = {"stage": stage, "calls_made": made, "stopped": stopped, "cancelled": stop.is_set(), "over_cap_skipped": len(skipped)}
    print(json.dumps(res), flush=True); app(OUT / "stage_log.jsonl", res)
    return res

def voter_jobs():
    jobs = []
    for it in ITEMS:  # interleave by sentence
        for m in VOTERS:
            jobs.append({**it, "model": m, "cache_key": cache_key(it["sentence"], m, PSHA)})
    return jobs
EXPECT = {"cx/gpt-6-luna": "gpt-6-luna", "ag/claude-sonnet-5-5-low": "claude-sonnet-5-5-low",
          "ag/gemini-3.8-flash-high": "gemini-3.8-flash-n", "oc/deepseek-v4.1-flash-free": "deepseek-v4.1-flash-free", "oc/glm-5.3-flash-free": "glm-5.3-flash-free",
          "ag/gemini-3.8-flash-low": "gemini-3.8-flash-n",  # 7e2: same name as the high variant; low tier not verifiable
          "trollllm/deepseek-v4-1-flash": "deepseek-v4-1-flash", T4: "claude-sonnet-5-5",
          "cx/gpt-5.6-luna": "gpt-5.6-luna", "cx/gpt-5.6-terra": "gpt-5.6-terra"}  # 7e4
assert all(v.startswith("cx/") and "claude" not in v for v in VOTERS), VOTERS  # ADDENDUM_7e4: cx-only voters
def guard(rec, model):
    """Reject silent router substitution: a vote counts only if the returned model name matches the pilot's."""
    if rec["status"] == "ok" and rec.get("returned_model") != EXPECT[model]:
        rec["status"] = "model_mismatch"; rec["error"] = f"returned:{rec.get('returned_model')}"; rec["annotation_unused"] = rec.pop("annotation", None)
    return rec
def voter_call(sess, j, key): return guard(post_once(sess, j["sentence"], j["model"], key, PSHA).as_dict(), j["model"])

def voter_votes():
    by = {k: first_ok_or_last(v) for k, v in grouped_calls(C / "voters_calls.jsonl").items()}
    out = {}
    for it in ITEMS:
        votes = {}
        for m in VOTERS:
            rec = by.get(cache_key(it["sentence"], m, PSHA))
            if rec and rec.get("status") == "ok":
                votes[m] = rec["annotation"]
        out[it["item_id"]] = votes
    return out
def needs_sol(votes):
    if len(votes) < 3: return True
    return any(len({v["aspects"][k]["decision"] for v in votes.values()}) > 1 for k in range(len(ASPECTS)))
def sol_jobs():
    V = voter_votes(); jobs = []
    for it in ITEMS:
        v = V[it["item_id"]]
        if not needs_sol(v): continue
        valid = list(v.items()); rng = random.Random(f"{S.SHUFFLE_SEED}:{it['item_id']}"); rng.shuffle(valid)
        anon = {"ABC"[i]: a for i, (m, a) in enumerate(valid)}; mapping = {"ABC"[i]: m for i, (m, _) in enumerate(valid)}
        user = json.dumps({"sentence": it["sentence"], "so_nguoi_gan_nhan_hop_le": len(anon), "nhan": {k: x["aspects"] for k, x in anon.items()}}, ensure_ascii=False)
        body = {"model": S.MODEL, "max_tokens": S.MAX_TOKENS, "stream": False, "reasoning_effort": S.REASONING_EFFORT,
                "messages": [{"role": "system", "content": S.REVIEW_SYSTEM}, {"role": "user", "content": user}]}
        k = hashlib.sha256(json.dumps({"stage": "eval300-sol", "voter_set": "7e4", "reviewer": "gpt-6-sol", "addendum": "7e5", "body": body}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        jobs.append({**it, "model": S.MODEL, "body": body, "cache_key": k, "anon_map": mapping, "votes": v})
    return jobs
def sol_call(sess, j, key):
    # ADDENDUM_7e5: only cx/gpt-6-sol; returned model must be exactly gpt-6-sol
    if j["model"] in SOL_REFUSED or j["model"] != S.MODEL or j["body"]["model"] != S.MODEL or S.MODEL in SOL_REFUSED:
        raise RuntimeError("ADDENDUM_7e5: Sol reviewer must be cx/gpt-6-sol")
    rec = S.post(sess, j, key)
    if rec.get("status") == "ok" and rec.get("returned_model") != SOL_EXPECT:
        rec["status"] = "model_mismatch"; rec["error"] = f"returned:{rec.get('returned_model')}"; rec["review_unused"] = rec.pop("review", None)
    rec["reviewer_addendum"] = "7e5"
    return rec

def majority(decs):
    if len(decs) < 2: return None
    d, n = collections.Counter(decs).most_common(1)[0]
    return d if n >= 2 and n > len(decs) / 2 else None
def open_cells():
    """Per item: dict aspect -> stage-1/2 status. Returns (status map, sol reviews)."""
    V = voter_votes(); sj = {j["item_id"]: j for j in sol_jobs()}
    sol_by = {k: first_ok_or_last(v) for k, v in grouped_calls(C / "sol_calls.jsonl").items()}
    status = {}
    for it in ITEMS:
        iid = it["item_id"]; v = V[iid]; st = {}
        rec = sol_by.get(sj[iid]["cache_key"]) if iid in sj else None
        rv = {x["aspect"]: x for x in rec["review"]["aspects"]} if rec and rec["status"] == "ok" else None
        for k, a in enumerate(ASPECTS):
            decs = [x["aspects"][k]["decision"] for x in v.values()]
            if iid not in sj: st[a] = ("unanimous", decs[0]); continue
            if rv is None:
                st[a] = ("unanimous", decs[0]) if len(decs) == 3 and len(set(decs)) == 1 else ("open", None); continue
            m = majority(decs); s = rv[a]
            if m is not None and s["decision"] == m and s["confidence"] in ("high", "medium") and s["decision"] not in ("abstain", "ambiguous"):
                st[a] = ("sol_resolved", s["decision"])
            else: st[a] = ("open", None)
        status[iid] = (st, rv)
    return status
def t4_jobs():
    st = open_cells(); jobs = []
    for it in ITEMS:
        if any(s == "open" for s, _ in st[it["item_id"]][0].values()):
            jobs.append({**it, "model": T4, "cache_key": cache_key(it["sentence"], T4, PSHA)})
    return jobs
def t4_call(sess, j, key):
    raise RuntimeError("ADDENDUM_7e1: t4 is remote-only (Claude Code medium on the user machine); the box never calls it")

if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "plan":
        print(json.dumps({"items": len(ITEMS), "voter_jobs": len(voter_jobs()), "issued_total": total_issued()})); sys.exit()
    if "--live" not in sys.argv: raise SystemExit("need --live")
    if stage == "voters": r = run_stage("voters", voter_jobs(), voter_call, VOTER_CAP)
    elif stage == "sol": r = run_stage("sol", sol_jobs(), sol_call, 300)
    elif stage == "t4": r = run_stage("t4", t4_jobs(), t4_call, TOTAL_CAP)
    sys.exit(0 if r["stopped"] is None else 3)
