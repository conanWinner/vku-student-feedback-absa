"""Addendum 5: retry non-ok journaled calls (up to 2 extra attempts). Does not issue first-attempt jobs.
Reuses run_eval call/validation/journal helpers and run_eval2 pacing/breakers. Append-only journals.
Successful (ok) calls are never re-called. Human labels are never loaded."""
import collections, json, os, signal, sys, threading, time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import run_eval as E
import run_eval2 as R
import probe3 as P

OUT = E.OUT
C = E.C
LOG = OUT / "retry_log.jsonl"
MAX_ATTEMPTS = 3  # 1 original + N=2 retries
STAGES = ("voters", "sol", "t4")


def log(x):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    print(s, flush=True)
    with LOG.open("a", encoding="utf-8") as h:
        h.write(s + "\n"); h.flush(); os.fsync(h.fileno())


def snapshot_failures():
    """Status counts only — no labels, no agreement."""
    out = {"stages": {}, "orphans": {}, "issued_intents": {}, "calls": {}}
    for stage in STAGES:
        calls = E.read(C / f"{stage}_calls.jsonl")
        intents = E.read(C / f"{stage}_intent.jsonl")
        ck, ik = {r["cache_key"] for r in calls}, {r["cache_key"] for r in intents}
        out["orphans"][stage] = len(ik - ck)
        out["issued_intents"][stage] = len(ik)
        out["calls"][stage] = len(calls)
        by = collections.Counter()
        for r in calls:
            m = r.get("requested_model") or r.get("model")
            st = r.get("status")
            by[f"{m}|{st}"] += 1
        fails = [r for r in calls if r.get("status") != "ok"]
        # one record per cache_key; originals only in the pre-retry snapshot
        key_fail = collections.Counter()
        groups = E.grouped_calls(C / f"{stage}_calls.jsonl")
        n_failed_jobs = n_ok_jobs = n_retryable = 0
        for k, recs in groups.items():
            picked = E.first_ok_or_last(recs)
            usable = E.usable_call_records(recs)
            if picked and picked.get("status") == "ok":
                n_ok_jobs += 1
            else:
                n_failed_jobs += 1
                key_fail[f"{(picked or {}).get('requested_model')}|{(picked or {}).get('status') or 'voided'}"] += 1
                if len(usable) < MAX_ATTEMPTS:
                    n_retryable += 1
        out["stages"][stage] = {
            "records": dict(by),
            "failed_jobs": n_failed_jobs,
            "ok_jobs": n_ok_jobs,
            "retryable_jobs": n_retryable,
            "failed_jobs_by_model_status": dict(key_fail),
            "fail_records": len(fails),
        }
    return out


def _jobs_for(stage):
    if stage == "voters":
        return {j["cache_key"]: j for j in E.voter_jobs()}
    if stage == "sol":
        return {j["cache_key"]: j for j in E.sol_jobs()}
    return {j["cache_key"]: j for j in E.t4_jobs()}


def retryable(stage):
    """Failed jobs that are still in the current job set and have remaining attempts."""
    jobs = _jobs_for(stage)
    out = []
    for k, recs in E.grouped_calls(C / f"{stage}_calls.jsonl").items():
        if k not in jobs:
            continue
        if any(r.get("status") == "ok" for r in recs):
            continue
        if len(recs) >= MAX_ATTEMPTS:
            continue
        out.append((jobs[k], recs))
    out.sort(key=lambda x: (x[0]["item_id"], x[0]["model"]))
    return out


def pending_first_attempt():
    """Unique first-attempt jobs not yet in the intent journal (run_eval2's work)."""
    counts = {}
    for stage in STAGES:
        jobs = _jobs_for(stage)
        intents = {r["cache_key"] for r in E.read(C / f"{stage}_intent.jsonl")}
        counts[stage] = sum(1 for k in jobs if k not in intents)
    return counts


def run_stage(stage, key, stopflag):
    jobs = retryable(stage)
    log({"event": "retry_stage_start", "stage": stage, "retryable": len(jobs),
         "models": dict(collections.Counter(j["model"] for j, _ in jobs))})
    if not jobs:
        return {"stage": stage, "issued": 0, "ok": 0, "fail": 0, "hard": None, "lane_stop": {}}

    paths = {s: (C / f"{s}_calls.jsonl", C / f"{s}_intent.jsonl") for s in STAGES}
    sess = R.CapSess()
    lock = threading.Lock()
    gap = 20.0
    last_ag_start = 0.0
    ag_pause_until = 0.0
    ag_ok_streak = 0
    ag_win = collections.deque(maxlen=30)
    ag_consec = 0
    lane_stop = {"cx": None, "xai": None, "ag": None}
    lane_consec = {"cx": 0, "xai": 0}
    lane_win = {"cx": collections.deque(maxlen=30), "xai": collections.deque(maxlen=30)}
    model_streak = collections.Counter()
    hard = None
    need_probe = False
    probe_state = {"thread": None, "result": None}
    inflight = {}
    counts = collections.Counter()
    issued = ok_n = fail_n = 0

    def lane_of(m):
        return "ag" if m.startswith("ag/") else ("xai" if m.startswith("xai/") else "cx")

    q = {"ag": collections.deque(), "cx": collections.deque(), "xai": collections.deque()}
    for j, recs in jobs:
        q[lane_of(j["model"])].append((j, recs))

    def do_call(st, j):
        if st == "voters":
            rec = E.voter_call(sess, j, key)
        elif st == "sol":
            rec = E.sol_call(sess, j, key)
        else:
            rec = E.t4_call(sess, j, key)
        rec["item_id"] = j["item_id"]
        rec["requested_model"] = j["model"]
        if rec.get("status") != "ok" and getattr(sess.tl, "err", None):
            rec["error_detail"] = sess.tl.err
        rec["ts"] = time.time()
        return rec

    def issue(j, recs):
        nonlocal issued
        orig = recs[0]
        attempt = len(recs) + 1
        intent = {
            "item_id": j["item_id"], "cache_key": j["cache_key"], "model": j["model"],
            "status": "issued_retry", "attempt": attempt, "addendum": 5,
            "retry_of": {"cache_key": orig["cache_key"], "status": orig.get("status"),
                         "error": orig.get("error"), "ts": orig.get("ts"),
                         "http_status": orig.get("http_status"), "n_prior": len(recs)},
        }
        with lock:
            s = json.dumps(intent, ensure_ascii=False)
            if key in s:
                raise RuntimeError("key in payload")
            E.app(paths[stage][1], intent)
            issued += 1
        inflight[pool.submit(do_call, stage, j)] = (j, recs, lane_of(j["model"]), attempt, orig)

    pool = ThreadPoolExecutor(2)
    try:
        while True:
            if hard or stopflag.is_set():
                break
            now = time.time()
            ag_busy = any(t[2] == "ag" for t in inflight.values())
            other_busy = sum(1 for t in inflight.values() if t[2] != "ag")
            if need_probe and not ag_busy and probe_state["thread"] is None:
                log({"event": "ag_pause_reprobe", "probes_used": P.used(), "budget": P.TOTAL_BUDGET})
                need_probe = False
                def _pr():
                    probe_state["result"] = P.wait_healthy(key, "addendum5_retry", None, first_delay=60, log=log)
                probe_state["result"] = None
                probe_state["thread"] = threading.Thread(target=_pr, daemon=True)
                probe_state["thread"].start()
            if probe_state["thread"] is not None:
                if not probe_state["thread"].is_alive():
                    probe_state["thread"] = None
                    if probe_state["result"]:
                        ag_win.clear(); ag_consec = 0
                        for mm in E.VOTERS:
                            if mm.startswith("ag/"):
                                model_streak.pop(mm, None)
                        log({"event": "ag_resume"})
                    else:
                        lane_stop["ag"] = "probe_budget_exhausted"
                        log({"event": "ag_lane_stop", "why": "probe_budget_exhausted", "ag_unissued": len(q["ag"])})
                    continue
            if q["ag"] and lane_stop["ag"] is None and probe_state["thread"] is None and not need_probe and not ag_busy and now >= ag_pause_until and now - last_ag_start >= gap and len(inflight) < 2:
                j, recs = q["ag"].popleft(); last_ag_start = now; issue(j, recs); continue
            olimit = 1 if (q["ag"] and lane_stop["ag"] is None) or ag_busy else 2
            if other_busy < olimit and len(inflight) < 2:
                pick = None
                if q["cx"] and lane_stop["cx"] is None:
                    pick = q["cx"].popleft()
                elif q["xai"] and lane_stop["xai"] is None:
                    pick = q["xai"].popleft()
                if pick:
                    issue(*pick); continue
            if not inflight:
                can = (
                    (q["ag"] and lane_stop["ag"] is None and probe_state["thread"] is None and not need_probe)
                    or (q["cx"] and lane_stop["cx"] is None)
                    or (q["xai"] and lane_stop["xai"] is None)
                )
                if not can and probe_state["thread"] is None and not need_probe:
                    break
                time.sleep(1); continue
            fin, _ = wait(set(inflight), timeout=2, return_when=FIRST_COMPLETED)
            for f in fin:
                j, recs, lane, attempt, orig = inflight.pop(f)
                rec = f.result()
                rec["attempt"] = attempt
                rec["addendum"] = 5
                rec["retry_of"] = {"cache_key": orig["cache_key"], "status": orig.get("status"),
                                   "error": orig.get("error"), "ts": orig.get("ts"),
                                   "http_status": orig.get("http_status"), "n_prior": len(recs)}
                with lock:
                    s = json.dumps(rec, ensure_ascii=False)
                    if key in s:
                        raise RuntimeError("key in payload")
                    E.app(paths[stage][0], rec)
                counts[f"{stage}|{j['model']}|{rec['status']}"] += 1
                ok = rec["status"] == "ok"
                if ok:
                    ok_n += 1
                else:
                    fail_n += 1
                log({"n_retry": ok_n + fail_n, "stage": stage, "item": j["item_id"], "model": j["model"],
                     "status": rec["status"], "attempt": attempt, "err": rec.get("error"),
                     "detail": rec.get("error_detail"), "gap": gap})
                try:
                    hs = int(rec.get("http_status") or 0)
                except Exception:
                    hs = 0
                if hs in (401, 403):
                    hard = f"http_{hs}:{j['model']}"
                m = j["model"]
                model_streak[m] = model_streak[m] + 1 if rec["status"] in ("model_mismatch", "parse_error", "http_error") else 0
                if lane == "ag":
                    ag_win.append(ok); ag_consec = 0 if ok else ag_consec + 1
                    if hs == 503:
                        rs = R.reset_seconds(rec.get("error_detail")); pause = (rs + 30) if rs is not None else 150
                        ag_pause_until = time.time() + pause; gap = min(60.0, gap + 10); ag_ok_streak = 0
                        log({"event": "ag_pause", "seconds": pause, "reset_stated": rs, "gap": gap})
                    elif ok:
                        ag_ok_streak += 1
                        if ag_ok_streak >= 30:
                            gap = max(10.0, gap - 5); ag_ok_streak = 0; log({"event": "gap_down", "gap": gap})
                    if model_streak[m] >= 3 or ag_consec >= 3 or (len(ag_win) >= 30 and ag_win.count(False) / len(ag_win) > 0.30):
                        need_probe = True
                else:
                    lane_win[lane].append(ok)
                    if rec["status"] in ("http_error", "transport_error"):
                        lane_consec[lane] += 1
                    else:
                        lane_consec[lane] = 0
                    why = None
                    if lane_consec[lane] >= 3:
                        why = "3_consecutive_http_transport"
                    elif model_streak[m] >= 3:
                        why = f"failure_streak:{m}"
                    elif len(lane_win[lane]) >= 30 and lane_win[lane].count(False) / len(lane_win[lane]) > 0.20:
                        why = "window_failure_gt_20pct"
                    if why and lane_stop[lane] is None:
                        lane_stop[lane] = why
                        log({"event": "lane_stop", "lane": lane, "why": why})
    finally:
        for f in list(inflight):
            j, recs, lane, attempt, orig = inflight.pop(f)
            try:
                rec = f.result(timeout=300)
                rec["attempt"] = attempt
                rec["addendum"] = 5
                rec["retry_of"] = {"cache_key": orig["cache_key"], "status": orig.get("status"),
                                   "error": orig.get("error"), "ts": orig.get("ts"),
                                   "http_status": orig.get("http_status"), "n_prior": len(recs)}
                s = json.dumps(rec, ensure_ascii=False)
                if key in s:
                    raise RuntimeError("key in payload")
                E.app(paths[stage][0], rec)
                counts[f"{stage}|{j['model']}|{rec['status']}"] += 1
                if rec["status"] == "ok":
                    ok_n += 1
                else:
                    fail_n += 1
            except Exception as e:
                log({"event": "inflight_lost", "item": j["item_id"], "err": type(e).__name__, "attempt": attempt})
        pool.shutdown(wait=True)
    res = {"event": "retry_stage_end", "stage": stage, "issued": issued, "ok": ok_n, "fail": fail_n,
           "calls_made": dict(counts), "hard": hard, "lane_stop": lane_stop,
           "cancelled": stopflag.is_set(),
           "unissued": {ln: len(q[ln]) for ln in q}, "probes_used": P.used()}
    log(res)
    E.app(OUT / "stage_log.jsonl", res)
    return res


def main():
    key = os.environ.get("NINE_ROUTER_API_KEY", "")
    if not key:
        raise SystemExit("key not set")
    if "--plan" in sys.argv:
        snap = snapshot_failures()
        plan = {s: [{"item_id": j["item_id"], "model": j["model"], "prior": len(recs),
                     "last_status": recs[-1]["status"]} for j, recs in retryable(s)] for s in STAGES}
        # counts only in the printed plan summary; item list is ids+status, no labels
        print(json.dumps({"snapshot": snap, "retryable_n": {s: len(plan[s]) for s in STAGES},
                          "pending_first_attempt": pending_first_attempt()}, ensure_ascii=False, indent=1))
        return 0
    if "--live" not in sys.argv:
        raise SystemExit("need --live")
    stopflag = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stopflag.set())
    signal.signal(signal.SIGINT, lambda *a: stopflag.set())
    stages = [s for s in STAGES if s in sys.argv]
    if not stages:
        stages = list(STAGES)
    hard = None
    summary = []
    for st in stages:
        if stopflag.is_set() or hard:
            break
        # recompute job set at the start of each stage (voters first, then sol from final-so-far votes)
        r = run_stage(st, key, stopflag)
        summary.append(r)
        if r.get("hard"):
            hard = r["hard"]
    rec = {"event": "retry_done", "hard": hard, "summary": [{k: x.get(k) for k in ("stage", "issued", "ok", "fail", "hard", "lane_stop")} for x in summary]}
    log(rec)
    tmp = OUT / "retry_status.json.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    tmp.replace(OUT / "retry_status.json")
    return 0 if not hard else 3


if __name__ == "__main__":
    sys.exit(main())
