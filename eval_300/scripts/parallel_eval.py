"""Addendum 6 scheduler (+ Addendum 7e5 `--design-7e5`: stage-2 Sol = cx/gpt-6-sol medium, 6.1 refused; + Addendum 7e4 `--design-7e4`: all-Codex voters luna-6 (cx, reused) / gpt-5.6-luna (cx2) / gpt-5.6-terra (cx3), Sol held/cx; + Addendum 7e2 `--design-7e2`: voters luna / Gemini-low (ag) / TrollLLM DeepSeek (tl) on 9router; 7e1: voters on 9router, Sol medium, t4 = remote Claude Code medium job queue; + Addendum 7d: t4 = cx/gpt-6.1-sol high on the cx lane, xai never called; + Addendum 7c `--gemini-9router`: box ag lane runs Gemini over 9router, Claude imported from remote): one in-flight call per lane (ag, cx, xai) at the same time.
Ag pacing (single call, gap, 503 pause, re-probe) and all timeouts are unchanged.
Combines Addendum 5 retries and remaining first-attempt work. Does not change
run_eval2.py or retry_failed.py. Human labels are never loaded. Not gold. No scoring."""
from __future__ import annotations
import collections, json, os, signal, sys, threading, time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

import run_eval as E
import run_eval2 as R
import probe3 as P

OUT = E.OUT
LIVE_C = (OUT / "cache").resolve()
LOG = OUT / "parallel_log.jsonl"
STATUS = OUT / "parallel_status.json"
LOCKF = OUT / "parallel.lock"
MAX_ATTEMPTS = 3  # 1 original + 2 retries (Addendum 5)
STAGES = ("voters", "sol", "t4")
LANES = ("ag", "cx", "cx2", "cx3", "tl")  # Addendum 7e4: cx2/cx3 = new voter lanes
GAP_LANES = ("cx2", "cx3", "tl")  # fixed 20 s start gap
BRK_LANES = ("cx", "cx2", "cx3", "tl")  # tl-style breaker
LANE_MODEL = {"cx/gpt-5.6-luna": "cx2", "cx/gpt-5.6-terra": "cx3"}
COOLDOWN_S = 900
MAX_COOLDOWNS = 8
SOL_CAP = min(300, E.TOTAL_CAP - E.VOTER_CAP)
GEMINI = "ag/gemini-3.8-flash-low"  # Addendum 7e2: the ag-lane voter (V2) and the only model the ag re-probe checks
TL_GAP_S = 20.0  # Addendum 7e2: fixed start gap on the TrollLLM lane; 7e4: also cx2/cx3
BANNED = ("xai/", "agy", "oc/", "ag/gemini-3.8-flash-high", "ag/claude", "cc/")  # Addendum 7d/7e/7e1: never issued by the box
REMOTE_T4_DIR = OUT / "remote_t4_payload"   # Addendum 7e1: jobs exported here (box -> user machine)
REMOTE_T4_RESULTS = OUT / "remote_t4"       # Addendum 7e1: results copied back here (user machine -> box)
CLAUDE = "ag/claude-sonnet-5-5-low"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(x, log_path=None):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    print(s, flush=True)
    p = log_path or LOG
    with p.open("a", encoding="utf-8") as h:
        h.write(s + "\n"); h.flush(); os.fsync(h.fileno())


def write_status(state, **kw):
    rec = {"state": state, "time": now_iso(), **kw}
    tmp = STATUS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    tmp.replace(STATUS)


def lane_of(model):
    # Addendum 7e2: trollllm/ -> own lane "tl" (former xai/oc2 slot); ag/ (Gemini-low) keeps the ag lane pacing; t4 is remote-only.
    if model in LANE_MODEL:  # Addendum 7e4
        return LANE_MODEL[model]
    if model.startswith("trollllm/"):
        return "tl"
    if model.startswith("oc/"):
        return "banned"
    if model.startswith("ag/"):
        return "ag"
    if model.startswith("claude-code/"):
        return "remote_t4"
    if model.startswith("xai/"):
        return "banned"
    return "cx"


def assert_not_live(cache):
    if Path(cache).resolve() == LIVE_C:
        raise SystemExit("refusing to dry-run or self-test on the live cache")


# ---------- journal state (pure planning) ----------

def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


class Journal:
    def __init__(self, cache):
        self.cache = Path(cache)
        self.reload()

    def reload(self):
        self.calls = {s: read_jsonl(self.cache / f"{s}_calls.jsonl") for s in STAGES}
        self.intents = {s: read_jsonl(self.cache / f"{s}_intent.jsonl") for s in STAGES}
        self.groups = {s: collections.defaultdict(list) for s in STAGES}
        for s in STAGES:
            for r in self.calls[s]:
                self.groups[s][r["cache_key"]].append(r)
        self.issued_keys = {s: {r["cache_key"] for r in self.intents[s]} for s in STAGES}
        self.orphan_atts = {s: set() for s in STAGES}  # (cache_key, attempt) intent without call
        call_atts = {s: {(r["cache_key"], r.get("attempt") or 1) for r in self.calls[s]} for s in STAGES}
        for s in STAGES:
            for r in self.intents[s]:
                att = r.get("attempt") or 1
                if (r["cache_key"], att) not in call_atts[s]:
                    self.orphan_atts[s].add((r["cache_key"], att))

    def _active(self, s, k):
        """Addendum 7e: a key whose call records are all voided/superseded, with no un-voided orphan intent, is not counted in caps."""
        recs = self.groups[s].get(k, [])
        if not recs or E.usable_call_records(recs):
            return True
        va = E.voided_attempts(recs)
        return any(kk == k and a not in va for (kk, a) in self.orphan_atts[s])

    def unique_n(self):
        return {s: sum(1 for k in self.issued_keys[s] if self._active(s, k)) for s in STAGES}

    def unique_total(self):
        return sum(self.unique_n().values())


def job_settled(jnl, stage, key):
    recs_all = jnl.groups[stage].get(key, [])
    recs = E.usable_call_records(recs_all)
    if any(r.get("status") == "ok" for r in recs):
        return True
    void_atts = E.voided_attempts(recs_all)
    n_orph = sum(1 for (k, a) in jnl.orphan_atts[stage] if k == key and a not in void_atts)
    return (len(recs) + n_orph) >= MAX_ATTEMPTS


def next_attempt(jnl, stage, key, inflight_atts):
    """Return the next attempt number, or None if settled, in-flight, or not issuable.

    Addendum 7b: voided attempts are ignored for the retry cap and for ok-settlement,
    but their attempt numbers are not reused.
    """
    recs_all = jnl.groups[stage].get(key, [])
    recs = E.usable_call_records(recs_all)
    if any(r.get("status") == "ok" for r in recs):
        return None
    if any(k == key and st == stage for (st, k, _a) in inflight_atts):
        return None
    void_atts = E.voided_attempts(recs_all)
    n_orph = sum(1 for (k, a) in jnl.orphan_atts[stage] if k == key and a not in void_atts)
    if (len(recs) + n_orph) >= MAX_ATTEMPTS:
        return None
    used = {r.get("attempt") or 1 for r in recs_all}
    used |= {a for (k, a) in jnl.orphan_atts[stage] if k == key}
    return max(used, default=0) + 1


def first_attempt_room(jnl, stage, pending_voter_first):
    uniq = jnl.unique_n()
    total = jnl.unique_total()
    if stage == "voters":
        return uniq["voters"] < E.VOTER_CAP and total < E.TOTAL_CAP
    reserve_v = min(pending_voter_first, max(0, E.VOTER_CAP - uniq["voters"]))
    if total + reserve_v >= E.TOTAL_CAP:
        return False
    if stage == "sol":
        return uniq["sol"] < SOL_CAP
    reserve_s = max(0, SOL_CAP - uniq["sol"])
    if total + reserve_v + reserve_s >= E.TOTAL_CAP:
        return False
    return total < E.TOTAL_CAP


def item_voters_settled(jnl, iid, vjobs_by_item):
    jobs = vjobs_by_item.get(iid, [])
    return bool(jobs) and all(job_settled(jnl, "voters", j["cache_key"]) for j in jobs)


def count_pending_voter_first(jnl, vjobs):
    n = 0
    for j in vjobs:
        recs = jnl.groups["voters"].get(j["cache_key"], [])
        if recs or j["cache_key"] in jnl.issued_keys["voters"]:
            continue
        n += 1
    return n


def build_queues(jnl, inflight_atts=frozenset()):
    """Build per-lane job lists from the journal. No I/O besides what Journal already loaded.
    Sol/t4 only for items whose voter (and for t4, Sol) inputs are final.
    Requires E.C to point at jnl.cache so sol_jobs/t4_jobs/voter_votes read the same files."""
    vjobs = E.voter_jobs()
    v_by = collections.defaultdict(list)
    for j in vjobs:
        v_by[j["item_id"]].append(j)
    settled = {it["item_id"] for it in E.ITEMS if item_voters_settled(jnl, it["item_id"], v_by)}
    pend_v_first = count_pending_voter_first(jnl, vjobs)
    q = {ln: [] for ln in LANES + ("remote_t4",)}

    def consider(stage, j):
        key = j["cache_key"]
        nxt = next_attempt(jnl, stage, key, inflight_atts)
        if nxt is None:
            return
        kind = "first" if nxt == 1 else "retry"
        if kind == "first" and not first_attempt_room(jnl, stage, pend_v_first):
            return
        recs = jnl.groups[stage].get(key, [])
        q[lane_of(j["model"])].append({
            "stage": stage, "item_id": j["item_id"], "model": j["model"],
            "cache_key": key, "kind": kind, "attempt": nxt, "job": j,
            "prior": recs,
        })

    # Voters: retries and first-attempts, in voter_jobs order (retries stay in that order but first after retries per lane)
    v_retry, v_first = [], []
    for j in vjobs:
        recs = jnl.groups["voters"].get(j["cache_key"], [])
        nxt = next_attempt(jnl, "voters", j["cache_key"], inflight_atts)
        if nxt is None:
            continue
        (v_retry if nxt > 1 else v_first).append(j)
    for j in v_retry + v_first:
        consider("voters", j)

    # Sol: only items with all 3 voter jobs settled (ok or retries exhausted)
    sj = {j["item_id"]: j for j in E.sol_jobs()}
    s_retry, s_first = [], []
    for iid in (it["item_id"] for it in E.ITEMS):
        if iid not in settled or iid not in sj:
            continue
        j = sj[iid]
        nxt = next_attempt(jnl, "sol", j["cache_key"], inflight_atts)
        if nxt is None:
            continue
        (s_retry if nxt > 1 else s_first).append(j)
    for j in s_retry + s_first:
        consider("sol", j)

    # t4: voters settled AND sol inputs final (not needed, or current-body Sol settled)
    tj = {j["item_id"]: j for j in E.t4_jobs()}
    t_retry, t_first = [], []
    for iid, j in tj.items():
        if iid not in settled:
            continue
        if iid in sj and not job_settled(jnl, "sol", sj[iid]["cache_key"]):
            continue
        nxt = next_attempt(jnl, "t4", j["cache_key"], inflight_atts)
        if nxt is None:
            continue
        (t_retry if nxt > 1 else t_first).append(j)
    for j in t_retry + t_first:
        consider("t4", j)

    return q, settled, sj


def plan_summary(q, jnl, settled):
    def slim(jobs):
        c = collections.Counter(f"{j['kind']}|{j['stage']}|{j['model']}" for j in jobs)
        return {"n": len(jobs), "by": dict(c)}
    return {
        "lanes": {ln: slim(q[ln]) for ln in LANES},
        "settled_items": len(settled),
        "unique_issued": jnl.unique_n(),
        "orphans_unmatched": {s: len(jnl.orphan_atts[s]) for s in STAGES},
    }


# ---------- live / dry-run loop ----------

def can_issue_ag(now, last_ag_start, gap, ag_pause_until, ag_busy, lane_stop, need_probe, probing):
    return (not ag_busy and lane_stop["ag"] is None and not need_probe and not probing
            and now >= ag_pause_until and now - last_ag_start >= gap)


def can_issue_lane(lane, busy, lane_stop, cooldown_until, now):
    if busy or lane_stop[lane] is not None:
        # cooldown expiry is handled by the loop (clears lane_stop)
        return False
    if now < cooldown_until.get(lane, 0):
        return False
    return True


def run_scheduler(cache, *, live, key, call_fn, stopflag, log_path=None,
                  gap_init=20.0, time_fn=time.time, sleep_fn=time.sleep,
                  cooldown_s=COOLDOWN_S, status_fn=None, ag_from_remote=False, gemini_9router=False, hold_lanes=(),
                  design_7e1=False, remote_t4_dir=None, remote_t4_results=None):
    cache = Path(cache)
    if not live:
        assert_not_live(cache)
    if live and not key:
        raise SystemExit("key not set")
    jlock = threading.Lock()
    paths = {s: (cache / f"{s}_calls.jsonl", cache / f"{s}_intent.jsonl") for s in STAGES}
    gap = gap_init
    last_ag_start = 0.0
    ag_pause_until = 0.0
    ag_ok_streak = 0
    ag_win = collections.deque(maxlen=30)
    ag_consec = 0
    lane_stop = {ln: None for ln in LANES}
    # Addendum 7c: operator hold (e.g. router has no credentials for a provider). Held lanes issue nothing,
    # so no attempts are burned; they never expire by cooldown. Pacing only; does not change what counts.
    held = set(hold_lanes)
    for ln in held:
        lane_stop[ln] = "operator_hold"
    lane_consec = {ln: 0 for ln in BRK_LANES}
    lane_win = {ln: collections.deque(maxlen=30) for ln in BRK_LANES}
    model_streak = collections.Counter()
    cooldown_until = {ln: 0.0 for ln in LANES}
    cooldowns = {ln: 0 for ln in LANES}
    tl_last = {"t": 0.0}
    gap_last = {ln: 0.0 for ln in GAP_LANES}  # Addendum 7e4: per-lane start time
    hard = None
    need_probe = False
    probe_state = {"thread": None, "result": None}
    inflight = {}  # future -> work
    counts = collections.Counter()
    issued_n = collections.Counter()
    lp = log_path or LOG

    def _log(x):
        log(x, log_path=lp)

    def inflight_atts():
        return frozenset((w["stage"], w["cache_key"], w["attempt"]) for w in inflight.values())

    if gemini_9router and not ag_from_remote:
        raise SystemExit("--gemini-9router requires --ag-from-remote")
    remote_pending = {"n": 0, "by": {}}

    def split_ag(q):
        # Addendum 7c: box ag lane = Gemini over 9router only; Claude stays remote (import only).
        if gemini_9router:
            rem = [w for w in q["ag"] if w["model"] != GEMINI]
            q["ag"] = [w for w in q["ag"] if w["model"] == GEMINI]
            remote_pending["n"] = len(rem)
            remote_pending["by"] = dict(collections.Counter(w["model"] for w in rem))
        return q

    # Addendum 7e1: stage 3 is a remote job queue (Claude Code medium on the user machine).
    t4_dir = Path(remote_t4_dir or (REMOTE_T4_DIR if live else cache / "_remote_t4_payload"))
    t4_res = Path(remote_t4_results or (REMOTE_T4_RESULTS if live else cache / "_remote_t4"))
    t4_jobs_p = t4_dir / "jobs_t4.jsonl"
    if design_7e1:
        t4_dir.mkdir(parents=True, exist_ok=True); t4_res.mkdir(parents=True, exist_ok=True)
    exported = {r["job_id"] for r in read_jsonl(t4_jobs_p)} if design_7e1 else set()
    t4_out = {"outstanding": 0, "exported_this_run": 0}

    def t4_outstanding_keys(jnl):
        va_by = {k: E.voided_attempts(v) for k, v in jnl.groups["t4"].items()}
        return {k for (k, a) in jnl.orphan_atts["t4"] if a not in va_by.get(k, set())}

    def export_t4(jnl, ws):
        if not design_7e1:
            return
        out = t4_outstanding_keys(jnl)
        for w in ws:
            if w["cache_key"] in out:
                continue  # one outstanding attempt per job; retry only after the previous result is imported
            j = w["job"]
            jid = f"{w['cache_key']}:a{w['attempt']}"
            if jid in exported:
                continue
            job = {"job_id": jid, "item_id": j["item_id"], "cache_key": w["cache_key"], "attempt": w["attempt"],
                   "kind": w["kind"], "requested_model": E.T4, "cli": "claude-code", "cli_model": E.T4_CLI_MODEL,
                   "effort": E.T4_EFFORT, "sentence": j["sentence"],
                   "user_message": json.dumps({"sentence": j["sentence"]}, ensure_ascii=False),
                   "prompt_sha256": E.PSHA, "addendum": "7e1", "exported_ts": time_fn()}
            intent = {"item_id": j["item_id"], "cache_key": w["cache_key"], "model": E.T4,
                      "status": "issued_retry" if w["kind"] == "retry" else "issued", "attempt": w["attempt"],
                      "route": "remote_t4_queue", "job_id": jid, "addendum": "7e1"}
            with jlock:
                E.app(paths["t4"][1], intent)
                E.app(t4_jobs_p, job)
            exported.add(jid); out.add(w["cache_key"]); t4_out["exported_this_run"] += 1
            _log({"event": "t4_export", "item": j["item_id"], "attempt": w["attempt"], "job_id": jid})

    last_t4_import = {"t": 0.0}

    def try_import_t4():
        if not design_7e1:
            return
        nowp = time_fn()
        if live and nowp - last_t4_import["t"] < 5:
            return
        last_t4_import["t"] = nowp
        try:
            import import_remote_t4 as IRT
            st = IRT.import_new(cache=cache, results_path=t4_res / "results.jsonl", jobs_path=t4_jobs_p,
                                mark_path=t4_res / "imported_ids.jsonl", lock=jlock)
            if st.get("imported") or st.get("rejected"):
                _log({"event": "t4_import", **st})
        except Exception as e:
            _log({"event": "t4_import_error", "err": f"{type(e).__name__}: {e}"[:200]})

    def refresh():
        # Point run_eval helpers at this cache
        E.C = cache
        try_import_t4()
        jnl = Journal(cache)
        q, settled, sj = build_queues(jnl, inflight_atts())
        t4_ws = q.pop("remote_t4", [])
        export_t4(jnl, t4_ws)
        if design_7e1:
            jnl = Journal(cache)
            # Addendum 7e2: wait only on outstanding t4 jobs that are still needed (items with open cells)
            t4_out["outstanding"] = len(t4_outstanding_keys(jnl) & {w["cache_key"] for w in t4_ws})
        return jnl, split_ag(q), settled, sj

    jnl, queues, settled, sj = refresh()
    _log({"event": "scheduler_start", "live": live, "ag_from_remote": ag_from_remote,
          "gemini_9router": gemini_9router, "hold_lanes": sorted(held), "addendum": ("7e5" if design_7e1 else ("7e" if gemini_9router else None)), "t4_model": E.T4, "voters": list(E.VOTERS),
          "sol_effort": E.S.REASONING_EFFORT, "t4_outstanding": t4_out["outstanding"],
          "remote_pending": dict(remote_pending),
          "plan": plan_summary(queues, jnl, settled), "time": now_iso()})
    last_import = {"t": 0.0, "stats": None}

    def try_import():
        if not ag_from_remote or not live:
            return
        nowp = time_fn()
        if nowp - last_import["t"] < 5:
            return
        last_import["t"] = nowp
        try:
            import import_remote_ag as IRA
            stats = IRA.import_new(lock=jlock, only_models=({CLAUDE} if gemini_9router else None))
            last_import["stats"] = stats
            if stats.get("imported"):
                _log({"event": "remote_import", **stats})
        except Exception as e:
            _log({"event": "remote_import_error", "err": type(e).__name__})
    if status_fn:
        status_fn("running", pid=os.getpid(), plan=plan_summary(queues, jnl, settled))

    def write_intent(w):
        j = w["job"]
        if w["kind"] == "retry":
            orig = w["prior"][0] if w["prior"] else {}
            rec = {
                "item_id": j["item_id"], "cache_key": j["cache_key"], "model": j["model"],
                "status": "issued_retry", "attempt": w["attempt"], "addendum": 5,
                "retry_of": {"cache_key": orig.get("cache_key", j["cache_key"]), "status": orig.get("status"),
                             "error": orig.get("error"), "ts": orig.get("ts"),
                             "http_status": orig.get("http_status"), "n_prior": len(w["prior"])},
            }
        else:
            rec = {"item_id": j["item_id"], "cache_key": j["cache_key"], "model": j["model"], "status": "issued"}
        s = json.dumps(rec, ensure_ascii=False)
        if key and key in s:
            raise RuntimeError("key in payload")
        E.app(paths[w["stage"]][1], rec)

    def write_call(w, rec):
        rec = dict(rec)
        rec["item_id"] = w["item_id"]
        rec["requested_model"] = w["model"]
        if w["kind"] == "retry":
            orig = w["prior"][0] if w["prior"] else {}
            rec["attempt"] = w["attempt"]
            rec["addendum"] = 5
            rec["retry_of"] = {"cache_key": orig.get("cache_key", w["cache_key"]), "status": orig.get("status"),
                               "error": orig.get("error"), "ts": orig.get("ts"),
                               "http_status": orig.get("http_status"), "n_prior": len(w["prior"])}
        rec.setdefault("ts", time_fn())
        s = json.dumps(rec, ensure_ascii=False)
        if key and key in s:
            raise RuntimeError("key in payload")
        E.app(paths[w["stage"]][0], rec)
        return rec

    def do_call(w):
        rec = call_fn(w["stage"], w["job"])
        return rec

    def issue(w):
        if w["model"].startswith(BANNED) or lane_of(w["model"]) in ("banned", "remote_t4"):
            raise RuntimeError("Addendum 7d/7e/7e1: xai/agy/gemini/claude must never be called by the box")
        if w["stage"] == "voters" and ("claude" in w["model"] or w["model"] not in E.VOTERS or not w["model"].startswith("cx/")):
            raise RuntimeError("Addendum 7e4: only the three cx/* voters may be issued as voters")
        if w["stage"] == "t4":
            raise RuntimeError("Addendum 7e1: t4 is remote-only")
        if w["stage"] == "sol" and (w["model"] != "cx/gpt-6-sol" or w["model"] in E.SOL_REFUSED):
            raise RuntimeError("Addendum 7e5: the only stage-2 reviewer is cx/gpt-6-sol")
        with jlock:
            write_intent(w)
            issued_n[f"{w['stage']}|{w['kind']}|{w['model']}"] += 1
        fut = pool.submit(do_call, w)
        inflight[fut] = w
        _log({"event": "issue", "stage": w["stage"], "item": w["item_id"], "model": w["model"],
              "kind": w["kind"], "attempt": w["attempt"], "lane": lane_of(w["model"]),
              "inflight_lanes": sorted({lane_of(x["model"]) for x in inflight.values()})})

    pool = ThreadPoolExecutor(len(LANES))
    try:
        while True:
            if hard or stopflag.is_set():
                break
            now = time_fn()
            # expire cx/xai cooldowns
            for ln in BRK_LANES:
                if ln in held:
                    continue
                if lane_stop[ln] and now >= cooldown_until[ln]:
                    _log({"event": "lane_cooldown_end", "lane": ln, "n": cooldowns[ln]})
                    lane_stop[ln] = None
                    lane_consec[ln] = 0
                    lane_win[ln].clear()
            busy = {ln: any(lane_of(w["model"]) == ln for w in inflight.values()) for ln in LANES}

            if need_probe and not busy["ag"] and probe_state["thread"] is None:
                if not live:
                    need_probe = False
                    ag_win.clear(); ag_consec = 0
                    _log({"event": "ag_resume", "dry_run": True})
                else:
                    _log({"event": "ag_pause_reprobe", "probes_used": P.used(), "budget": P.TOTAL_BUDGET})
                    need_probe = False
                    def _pr():
                        if gemini_9router or design_7e1:
                            probe_state["result"] = P.wait_healthy(key, "addendum7e_voter3_9router", None, first_delay=60, log=_log,
                                                                   models=(GEMINI,))
                        else:
                            probe_state["result"] = P.wait_healthy(key, "addendum6_parallel", None, first_delay=60, log=_log)
                    probe_state["result"] = None
                    probe_state["thread"] = threading.Thread(target=_pr, daemon=True)
                    probe_state["thread"].start()
            probing = probe_state["thread"] is not None
            if probing:
                if not probe_state["thread"].is_alive():
                    probe_state["thread"] = None
                    probing = False
                    if probe_state["result"]:
                        ag_win.clear(); ag_consec = 0
                        for mm in E.VOTERS:
                            if mm.startswith("ag/"):
                                model_streak.pop(mm, None)
                        _log({"event": "ag_resume"})
                    else:
                        lane_stop["ag"] = "probe_budget_exhausted"
                        _log({"event": "ag_lane_stop", "why": "probe_budget_exhausted"})

            issued_any = False
            # Fill every free lane this tick (ag + cx + xai can all be in flight).
            if ((not ag_from_remote) or gemini_9router) and queues["ag"] and can_issue_ag(now, last_ag_start, gap, ag_pause_until, busy["ag"], lane_stop, need_probe, probing):
                last_ag_start = now
                issue(queues["ag"].pop(0)); issued_any = True
                busy["ag"] = True
            if ag_from_remote:
                try_import()
            if queues["cx"] and can_issue_lane("cx", busy["cx"], lane_stop, cooldown_until, now):
                issue(queues["cx"].pop(0)); issued_any = True
                busy["cx"] = True
            for ln in GAP_LANES:  # Addendum 7e4: cx2/cx3 (and tl) one in flight, fixed 20 s start gap
                if queues[ln] and can_issue_lane(ln, busy[ln], lane_stop, cooldown_until, now) and now - gap_last[ln] >= TL_GAP_S:
                    gap_last[ln] = now
                    issue(queues[ln].pop(0)); issued_any = True
                    busy[ln] = True
            if issued_any:
                if status_fn:
                    status_fn("running", pid=os.getpid(), addendum=("7e5" if design_7e1 else ("7e" if gemini_9router else None)), t4_outstanding=t4_out["outstanding"], t4_exported_this_run=t4_out["exported_this_run"],
                          remote_pending=dict(remote_pending), queued={ln: len(queues[ln]) for ln in LANES}, inflight={
                        lane_of(w["model"]): f"{w['stage']}:{w['item_id']}:{w['model']}:{w['kind']}"
                        for w in inflight.values()
                    }, issued_this_run=dict(issued_n), lane_stop=dict(lane_stop))
                continue

            if not inflight:
                if ag_from_remote:
                    try_import()
                jnl, queues, settled, sj = refresh()
                ag_local = (not ag_from_remote) or gemini_9router
                still = any(queues[ln] and lane_stop[ln] is None for ln in BRK_LANES + (("ag",) if ag_local else ()))
                waiting_cd = any(lane_stop[ln] and queues[ln] and ln not in held for ln in BRK_LANES)
                waiting_ag = (queues["ag"] and (need_probe or probing or lane_stop["ag"])) if ag_local else False
                waiting_remote = False
                if ag_from_remote:
                    st = None
                    sp = E.OUT / "remote_ag" / "local_status.json"
                    if sp.exists():
                        try: st = json.loads(sp.read_text()).get("state")
                        except Exception: st = None
                    # Keep running while scoring ag jobs are still unsettled, unless the remote worker is complete
                    # (then remaining failed jobs are just residual non-votes after retries).
                    remote_work = remote_pending["n"] if gemini_9router else len(queues["ag"])
                    waiting_remote = bool(remote_work) and st != "complete"
                waiting_t4 = bool(design_7e1 and live and t4_out["outstanding"])
                if not still and not waiting_cd and not waiting_ag and not waiting_remote and not waiting_t4 and not probing and not need_probe:
                    break
                # stall if a lane exceeded cooldown budget and is the only remaining work
                blocked_only = (not any(queues[ln] and lane_stop[ln] is None for ln in LANES)
                                and any(cooldowns[ln] > MAX_COOLDOWNS and queues[ln] for ln in LANES))
                if blocked_only and not probing and not need_probe:
                    hard = hard or "stalled_max_cooldowns"
                    break
                sleep_fn(1)
                continue

            fin, _ = wait(set(inflight), timeout=1, return_when=FIRST_COMPLETED)
            for f in fin:
                w = inflight.pop(f)
                rec = f.result()
                with jlock:
                    rec = write_call(w, rec)
                counts[f"{w['stage']}|{w['model']}|{rec.get('status')}"] += 1
                ok = rec.get("status") == "ok"
                ln = lane_of(w["model"])
                _log({"event": "complete", "n": sum(counts.values()), "stage": w["stage"], "item": w["item_id"],
                      "model": w["model"], "status": rec.get("status"), "attempt": w["attempt"], "kind": w["kind"],
                      "err": rec.get("error"), "detail": rec.get("error_detail"), "lane": ln, "gap": gap,
                      "inflight_lanes": sorted({lane_of(x["model"]) for x in inflight.values()})})
                try:
                    hs = int(rec.get("http_status") or 0)
                except Exception:
                    hs = 0
                if hs in (401, 403):
                    hard = f"http_{hs}:{w['model']}"
                m = w["model"]
                model_streak[m] = model_streak[m] + 1 if rec.get("status") in ("model_mismatch", "parse_error", "http_error") else 0
                if ln == "ag":
                    ag_win.append(ok); ag_consec = 0 if ok else ag_consec + 1
                    if hs == 503:
                        rs = R.reset_seconds(rec.get("error_detail")); pause = (rs + 30) if rs is not None else 150
                        ag_pause_until = time_fn() + pause; gap = min(60.0, gap + 10); ag_ok_streak = 0
                        _log({"event": "ag_pause", "seconds": pause, "reset_stated": rs, "gap": gap})
                    elif ok:
                        ag_ok_streak += 1
                        if ag_ok_streak >= 30:
                            gap = max(10.0, gap - 5); ag_ok_streak = 0; _log({"event": "gap_down", "gap": gap})
                    if model_streak[m] >= 3 or ag_consec >= 3 or (len(ag_win) >= 30 and ag_win.count(False) / len(ag_win) > 0.30):
                        need_probe = True
                else:
                    lane_win[ln].append(ok)
                    if rec.get("status") in ("http_error", "transport_error"):
                        lane_consec[ln] += 1
                    else:
                        lane_consec[ln] = 0
                    why = None
                    if lane_consec[ln] >= 3:
                        why = "3_consecutive_http_transport"
                    elif model_streak[m] >= 3:
                        why = f"failure_streak:{m}"
                    elif len(lane_win[ln]) >= 30 and lane_win[ln].count(False) / len(lane_win[ln]) > 0.20:
                        why = "window_failure_gt_20pct"
                    if why and lane_stop[ln] is None:
                        cooldowns[ln] += 1
                        lane_stop[ln] = why
                        cooldown_until[ln] = time_fn() + (0 if not live else cooldown_s)
                        _log({"event": "lane_stop", "lane": ln, "why": why, "cooldown_s": 0 if not live else cooldown_s,
                              "n": cooldowns[ln]})
                        if cooldowns[ln] > MAX_COOLDOWNS:
                            _log({"event": "lane_max_cooldowns", "lane": ln})
            if fin:
                jnl, queues, settled, sj = refresh()
    finally:
        for f in list(inflight):
            w = inflight.pop(f)
            try:
                rec = f.result(timeout=300)
                with jlock:
                    write_call(w, rec)
                counts[f"{w['stage']}|{w['model']}|{rec.get('status')}"] += 1
            except Exception as e:
                _log({"event": "inflight_lost", "item": w["item_id"], "stage": w["stage"],
                      "err": type(e).__name__, "attempt": w["attempt"]})
        pool.shutdown(wait=True)
    E.C = cache
    jnl = Journal(cache)
    q, settled, sj = build_queues(jnl)
    q = split_ag(q)
    if design_7e1:
        q.pop("remote_t4", None)
    remaining = {ln: len(q[ln]) for ln in LANES}
    if design_7e1:
        remaining["remote_t4_outstanding"] = len(t4_outstanding_keys(jnl))
    if gemini_9router:
        remaining["remote_claude"] = remote_pending["n"]
    ev = "complete"
    state = "complete"
    if hard and str(hard).startswith("http_"):
        ev, state = "aborted", "aborted"
    elif hard or any(remaining[ln] and (lane_stop[ln] or cooldowns[ln] > MAX_COOLDOWNS) for ln in LANES):
        if any(remaining[ln] for ln in LANES) or remaining.get("remote_claude") or remaining.get("remote_t4_outstanding"):
            ev, state = "stalled", "stalled"
    res = {"event": ev, "state": state, "hard": hard, "lane_stop": lane_stop, "cancelled": stopflag.is_set(),
           "calls_made": dict(counts), "issued_this_run": dict(issued_n), "remaining": remaining,
           "unique_issued": jnl.unique_n(), "orphans_unmatched": {s: len(jnl.orphan_atts[s]) for s in STAGES},
           "cooldowns": cooldowns, "probes_used": P.used() if live else 0}
    _log(res)
    if status_fn:
        status_fn(state, pid=os.getpid(), **{k: res[k] for k in res if k not in ("event", "state")})
    return 0 if state == "complete" and not stopflag.is_set() else (3 if state != "complete" else 2)


# ---------- self-test / dry-run (no network) ----------

def _ann(decisions):
    return {"aspects": [{"aspect": a, "decision": d, "evidence": "e"} for a, d in zip(E.ASPECTS, decisions)]}


def _ok_voter(j, decisions):
    return {"cache_key": j["cache_key"], "status": "ok", "requested_model": j["model"], "item_id": j["item_id"],
            "http_status": 200, "returned_model": E.EXPECT[j["model"]], "annotation": _ann(decisions),
            "error": None, "endpoint": "<9ROUTER_ENDPOINT>"}


def _fail_voter(j, status="transport_error", err="ReadTimeout"):
    return {"cache_key": j["cache_key"], "status": status, "requested_model": j["model"], "item_id": j["item_id"],
            "http_status": 503 if status == "http_error" else None, "error": err,
            "endpoint": "<9ROUTER_ENDPOINT>"}


def _intent(j, attempt=1):
    rec = {"item_id": j["item_id"], "cache_key": j["cache_key"], "model": j["model"], "status": "issued"}
    if attempt > 1:
        rec.update({"status": "issued_retry", "attempt": attempt, "addendum": 5})
    return rec


def _write_mini(cache, intents, calls):
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    by_i, by_c = {s: [] for s in STAGES}, {s: [] for s in STAGES}
    for stage, rec in intents:
        by_i[stage].append(rec)
    for stage, rec in calls:
        by_c[stage].append(rec)
    for s in STAGES:
        (cache / f"{s}_intent.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in by_i[s]))
        (cache / f"{s}_calls.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in by_c[s]))


def _sol_ok(j, decision="absent", conf="high"):
    return {"cache_key": j["cache_key"], "status": "ok", "requested_model": j["model"], "item_id": j["item_id"],
            "http_status": 200, "returned_model": "gpt-6-sol",
            "review": {"aspects": [{"aspect": a, "decision": decision, "confidence": conf,
                                    "evidence": "e", "rationale": "r"} for a in E.ASPECTS]}}


def self_test(copy_dir):
    import tempfile, shutil
    assert_not_live(copy_dir)
    failures = []

    def check(name, cond, detail=""):
        if not cond:
            failures.append(f"{name}: {detail}")
            print("FAIL", name, detail, flush=True)
        else:
            print("ok ", name, flush=True)

    # A. helper tests
    class Dummy:
        pass
    # next_attempt / settled via a tiny journal
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        assert_not_live(td)
        E.C = td
        real_items = E.ITEMS
        items = E.ITEMS[:4]
        E.ITEMS = items  # isolate the synthetic universe
        # map original ids to jobs
        all_v = [j for j in E.voter_jobs() if j["item_id"] in {it["item_id"] for it in items}]
        by = collections.defaultdict(list)
        for j in all_v:
            by[j["item_id"]].append(j)
        # A: 3 voters disagree on first aspect → settled, needs sol, no sol yet → cx first sol
        # B: 2 ok + 1 fail attempt 1 (gemini) → NOT settled, no sol
        # C: 3 unanimous ok → no sol, no t4
        # D: 3 disagree, sol ok but abstain → t4 first
        absents = ["absent"] * 11
        pos = ["positive"] + ["absent"] * 10
        neg = ["negative"] + ["absent"] * 10
        A, B, C, D = [it["item_id"] for it in items]
        intents, calls = [], []
        # A, C, D all 3 ok; B luna+sonnet ok, gemini fail
        for iid, decs in (
            (A, (pos, neg, absents)),
            (B, (pos, pos, None)),
            (C, (absents, absents, absents)),
            (D, (pos, neg, absents)),
        ):
            for j, dec in zip(by[iid], decs):
                intents.append(("voters", _intent(j)))
                if dec is None:
                    calls.append(("voters", _fail_voter(j)))
                else:
                    calls.append(("voters", _ok_voter(j, dec)))
        _write_mini(td, intents, calls)
        # need sol records for D only; compute sol job after votes exist
        E.C = td
        sj = {j["item_id"]: j for j in E.sol_jobs()}
        check("synthetic A needs sol", A in sj)
        check("synthetic B in sol_jobs (partial votes) but must be gated", B in sj,
              "expected needs_sol due to <3 votes")
        check("synthetic C not in sol_jobs (unanimous)", C not in sj)
        check("synthetic D needs sol", D in sj)
        # write D sol abstain
        intents.append(("sol", _intent(sj[D])))
        calls.append(("sol", _sol_ok(sj[D], decision="abstain", conf="low")))
        _write_mini(td, intents, calls)
        E.C = td
        jnl = Journal(td)
        q, settled, sj2 = build_queues(jnl)
        check("A settled", A in settled)
        check("B not settled", B not in settled)
        check("C settled", C in settled)
        check("D settled", D in settled)
        sol_items = {w["item_id"] for w in q["cx"] if w["stage"] == "sol"}
        t4_items = {w["item_id"] for w in q["remote_t4"] if w["stage"] == "t4"}  # Addendum 7e1: t4 is a remote job queue
        v_retry_items = {(w["item_id"], w["model"]) for ln in LANES for w in q[ln] if w["kind"] == "retry"}
        check("sol queue has A (first), not B, not C, not D (already has sol)",
              A in sol_items and B not in sol_items and C not in sol_items and D not in sol_items,
              f"sol_items={sol_items}")
        check("B voter-3 (7e4: gpt-5.6-terra) is a retry on cx3", (B, E.VOTERS[2]) in v_retry_items and any(w["item_id"] == B and w["model"] == E.VOTERS[2] for w in q["cx3"]), f"{v_retry_items}")
        check("D is in t4 queue (sol final, open cells)", D in t4_items, f"t4_items={t4_items}")
        check("C not in t4 (unanimous)", C not in t4_items)
        check("no ok key re-queued",
              all(not any(r.get("status") == "ok" for r in w["prior"]) for ln in LANES for w in q[ln]))
        # no sol/t4 for unsettled B
        check("no t4 for B", B not in t4_items)

        # B. concurrency: A sol, D t4, B gemini retry can all be issued together
        barrier = threading.Barrier(2, timeout=10)  # Addendum 7d: t4 shares cx lane; 2 lanes (ag, cx) in flight
        n_calls = {"n": 0}
        nlock = threading.Lock()
        def call_fn(stage, j):
            # first wave only: all 3 lanes must enter the call together
            with nlock:
                n_calls["n"] += 1
                first_wave = n_calls["n"] <= 2
            if first_wave:
                try:
                    barrier.wait()
                except Exception as e:
                    failures.append(f"barrier: {type(e).__name__}: {e}")
            if stage == "sol":
                # keep D-like abstain so we don't accidentally hide t4 mid-run; A can be sol ok
                dec = "neutral"; conf = "high"
                rec = _sol_ok({"cache_key": j["cache_key"], "model": j["model"], "item_id": j["item_id"]},
                              decision=dec, conf=conf)
                rec["dry_run"] = True
                return rec
            if stage == "t4":
                return {"cache_key": j["cache_key"], "status": "ok", "requested_model": j["model"],
                        "item_id": j["item_id"], "http_status": 200, "returned_model": E.EXPECT[E.T4],
                        "annotation": _ann(absents), "dry_run": True}
            # voter retry
            return {**_ok_voter(j, pos), "dry_run": True}

        stop = threading.Event()
        rc = run_scheduler(td, live=False, key="", call_fn=call_fn, stopflag=stop,
                           log_path=td / "parallel_log.jsonl", gap_init=20.0,
                           sleep_fn=lambda s: None, cooldown_s=0, design_7e1=True)
        # Addendum 7e1: remote t4 queue — export, simulated remote results, import (idempotent, tag-checked)
        import import_remote_t4 as IRT
        jp = td / "_remote_t4_payload" / "jobs_t4.jsonl"; rp = td / "_remote_t4" / "results.jsonl"; mp = td / "_remote_t4" / "imported_ids.jsonl"
        tj = read_jsonl(jp)
        check("t4 jobs exported for D", any(j["item_id"] == D for j in tj), f"{[j['item_id'] for j in tj]}")
        check("t4 jobs not exported for B/C", not any(j["item_id"] in (B, C) for j in tj))
        check("t4 job tags", all(j["cli_model"] == "claude-sonnet-5-5" and j["effort"] == "medium" and j["requested_model"] == E.T4
                                 and j["user_message"] == json.dumps({"sentence": j["sentence"]}, ensure_ascii=False) for j in tj))
        check("one job per key (no duplicate outstanding attempts)", len({j["cache_key"] for j in tj}) == len(tj))
        jn = Journal(td)
        check("t4 intents written as outstanding", all((j["cache_key"], j["attempt"]) in jn.orphan_atts["t4"] for j in tj))
        def _res(j, **kw):
            r = {"job_id": j["job_id"], "item_id": j["item_id"], "cache_key": j["cache_key"], "attempt": j["attempt"],
                 "requested_model": E.T4, "cli_model": "claude-sonnet-5-5", "effort": "medium", "prompt_sha256": j["prompt_sha256"],
                 "status": "content_ready", "returned_model": "claude-sonnet-5-5", "returned_model_source": "modelUsage_key",
                 "content": json.dumps({"aspects": [{"aspect": x, "decision": "absent", "evidence": ""} for x in E.ASPECTS]}, ensure_ascii=False), "ts": time.time()}
            r.update(kw); return r
        rp.parent.mkdir(parents=True, exist_ok=True)
        lines = [_res(j) for j in tj] + [_res(tj[0], job_id="bogus:a1")]
        rp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
        st1 = IRT.import_new(td, rp, jp, mp); st2 = IRT.import_new(td, rp, jp, mp)
        check("t4 import ok", st1["imported"] == len(tj) and st1["rejected"] == 1, st1)
        check("t4 import idempotent", st2["imported"] == 0 and st2["rejected"] == 0, st2)
        t4c = [r for r in read_jsonl(td / "t4_calls.jsonl") if r.get("route_addendum") == "7e1"]
        check("t4 imported records ok + tagged", t4c and all(r["status"] == "ok" and r["effort"] == "medium" and r["annotation"] for r in t4c), str([r.get("status") for r in t4c]))
        # tag mismatch and model mismatch handling on a fresh mini-journal
        with tempfile.TemporaryDirectory() as td2:
            td2 = Path(td2); shutil.copy(td / "t4_intent.jsonl", td2 / "t4_intent.jsonl"); (td2 / "t4_calls.jsonl").write_text("")
            rp2 = td2 / "r.jsonl"; mp2 = td2 / "m.jsonl"
            rp2.write_text(json.dumps(_res(tj[0], effort="low")) + "\n")
            st3 = IRT.import_new(td2, rp2, jp, mp2)
            check("t4 effort!=medium rejected", st3["rejected"] == 1 and st3["imported"] == 0, st3)
            rp2.write_text(json.dumps(_res(tj[0], job_id=tj[0]["job_id"], returned_model="claude-opus-5-5")) + "\n"); mp2.write_text("")
            IRT.import_new(td2, rp2, jp, mp2)
            r3 = read_jsonl(td2 / "t4_calls.jsonl")
            check("t4 wrong returned model -> model_mismatch", r3 and r3[-1]["status"] == "model_mismatch", str(r3[-1:]))
        events = [json.loads(l) for l in (td / "parallel_log.jsonl").read_text().splitlines() if l.strip()]
        issues = [e for e in events if e.get("event") == "issue"]
        # first three issues should cover 3 lanes before any complete, or inflight_lanes reaches 3
        saw3 = any(len(e.get("inflight_lanes") or []) >= 2 for e in issues)
        check("issued ag and cx lanes concurrently; nothing on banned/remote lanes (7e1)", saw3 and not any(e.get("lane") in ("banned", "remote_t4") or e.get("stage") == "t4" for e in issues),
              f"issues={[ (e.get('lane'), e.get('inflight_lanes')) for e in issues[:6] ]}")
        check("scheduler completed synthetic run", rc == 0, f"rc={rc}")
        # no ok key called twice
        calls_after = Journal(td)
        for s in STAGES:
            for key, recs in calls_after.groups[s].items():
                oks = [r for r in recs if r.get("status") == "ok"]
                # first ok should be the last if we stop at ok; never more than 1 ok, and no call after first ok
                check(f"at most one ok for {s} {key[:8]}", len(oks) <= 1, f"n_ok={len(oks)}")
                if oks:
                    first_ok = next(i for i, r in enumerate(recs) if r.get("status") == "ok")
                    check(f"no call after first ok {s} {key[:8]}", first_ok == len(recs) - 1)
        E.ITEMS = real_items

    # C. plan on frozen real-journal copy (read-only)
    E.ITEMS = getattr(E, "ITEMS", E.ITEMS)
    E.C = Path(copy_dir)
    jnl = Journal(copy_dir)
    q, settled, sj = build_queues(jnl)
    summ = plan_summary(q, jnl, settled)
    print("FROZEN_PLAN", json.dumps(summ, ensure_ascii=False), flush=True)
    all_jobs = [w for ln in LANES for w in q[ln]]
    ok_called = []
    for w in all_jobs:
        recs = jnl.groups[w["stage"]].get(w["cache_key"], [])
        if any(r.get("status") == "ok" for r in recs):
            ok_called.append((w["stage"], w["item_id"], w["model"]))
    check("frozen plan never re-queues an ok key", not ok_called, str(ok_called[:5]))
    # unmatched attempts not re-issued
    reissue_orphan = []
    for w in all_jobs:
        if (w["cache_key"], w["attempt"]) in jnl.orphan_atts[w["stage"]]:
            reissue_orphan.append((w["stage"], w["item_id"], w["attempt"]))
    check("frozen plan does not re-issue unmatched intent attempts", not reissue_orphan, str(reissue_orphan))
    # Sol gated
    v_by = collections.defaultdict(list)
    for j in E.voter_jobs():
        v_by[j["item_id"]].append(j)
    for w in all_jobs:
        if w["stage"] == "sol":
            check(f"sol {w['item_id']} voters settled", w["item_id"] in settled)
        if w["stage"] == "t4":
            check(f"t4 {w['item_id']} voters settled", w["item_id"] in settled)
            sj_item = sj.get(w["item_id"])
            if sj_item:
                check(f"t4 {w['item_id']} sol settled", job_settled(jnl, "sol", sj_item["cache_key"]))
    check("frozen plan has cx2 and cx3 voter work (7e4)", summ["lanes"]["cx2"]["n"] > 0 and summ["lanes"]["cx3"]["n"] > 0, summ)
    if summ["settled_items"] > 0:  # 7e: right after the voter-3 swap nothing is settled yet, so no Sol/t4 work is expected
        check("frozen plan has cx work (sol ready to run beside ag)", summ["lanes"]["cx"]["n"] > 0, summ)
    check("frozen plan has no banned model (7e)", not any(k.split("|")[-1].startswith(BANNED) for ln in LANES for k in summ["lanes"][ln]["by"]), summ)
    check("frozen plan: no t4 on any local lane (7e1)", not any("|t4|" in k for ln in LANES for k in summ["lanes"][ln]["by"]), summ)
    check("frozen plan: ag and tl lanes empty (7e4)", summ["lanes"]["ag"]["n"] == 0 and summ["lanes"]["tl"]["n"] == 0, summ)
    check("frozen plan: cx2 only gpt-5.6-luna, cx3 only gpt-5.6-terra (7e4)", all(k.split("|")[-1] == "cx/gpt-5.6-luna" for k in summ["lanes"]["cx2"]["by"]) and all(k.split("|")[-1] == "cx/gpt-5.6-terra" for k in summ["lanes"]["cx3"]["by"]), summ)
    check("frozen plan: every voter job is cx/* (7e4)", all(k.split("|")[-1].startswith("cx/") for ln in LANES for k in summ["lanes"][ln]["by"] if "|voters|" in k), summ)
    check("frozen plan: no Claude/oc/Gemini-high voter (7e2)", not any(("claude" in k or "|oc/" in k or "flash-high" in k) for ln in LANES for k in summ["lanes"][ln]["by"]), summ)
    # retries have attempt 2 or 3 and prior failures only
    for w in all_jobs:
        if w["kind"] == "retry":
            check("retry attempt in 2..3", w["attempt"] in (2, 3))
            check("retry has prior non-ok", w["prior"] and all(r.get("status") != "ok" for r in w["prior"]))

    # Addendum 7e5 checks
    check("7e5: sol model cx/gpt-6-sol medium", E.S.MODEL == "cx/gpt-6-sol" and E.S.REASONING_EFFORT == "medium" and E.SOL_EXPECT == "gpt-6-sol")
    check("7e5: every sol job body uses cx/gpt-6-sol", all(w["model"] == "cx/gpt-6-sol" and w["job"]["body"]["model"] == "cx/gpt-6-sol" for w in all_jobs if w["stage"] == "sol"))
    check("7e5: no sol job key has any call record (no 6.1 reuse)", not any(jnl.groups["sol"].get(w["cache_key"]) for w in all_jobs if w["stage"] == "sol" and w["kind"] == "first"))
    class _S:
        pass
    try:
        E.sol_call(None, {"model": "cx/gpt-6.1-sol", "body": {"model": "cx/gpt-6.1-sol"}}, "")
        check("7e5: sol_call refuses 6.1", False)
    except RuntimeError:
        check("7e5: sol_call refuses 6.1", True)
    _orig_post = E.S.post
    try:
        E.S.post = lambda s, j, k: {"status": "ok", "returned_model": "gpt-6.1-sol", "review": {"aspects": []}}
        r = E.sol_call(None, {"model": "cx/gpt-6-sol", "body": {"model": "cx/gpt-6-sol"}}, "")
        check("7e5: wrong returned Sol model -> model_mismatch", r["status"] == "model_mismatch" and "review" not in r, r)
        E.S.post = lambda s, j, k: {"status": "ok", "returned_model": "gpt-6-sol", "review": {"aspects": []}}
        r = E.sol_call(None, {"model": "cx/gpt-6-sol", "body": {"model": "cx/gpt-6-sol"}}, "")
        check("7e5: gpt-6-sol returned -> ok", r["status"] == "ok" and r["reviewer_addendum"] == "7e5", r)
    finally:
        E.S.post = _orig_post

    if failures:
        print(f"SELFTEST_FAIL n={len(failures)}", flush=True)
        for f in failures:
            print(" -", f, flush=True)
        return 1
    print("SELFTEST_OK", flush=True)
    return 0


def counts_only():
    """Status counts, no labels."""
    E.C = LIVE_C
    jnl = Journal(LIVE_C)
    q, settled, sj = build_queues(jnl)
    return {"plan": plan_summary(q, jnl, settled), "time": now_iso()}


def main():
    if "--self-test" in sys.argv:
        copy = Path(sys.argv[sys.argv.index("--self-test") + 1]) if "--cache-dir" not in sys.argv else Path(sys.argv[sys.argv.index("--cache-dir") + 1])
        if "--self-test" in sys.argv and "--cache-dir" not in sys.argv:
            # default: require --cache-dir
            if len(sys.argv) > sys.argv.index("--self-test") + 1 and not sys.argv[sys.argv.index("--self-test") + 1].startswith("-"):
                copy = Path(sys.argv[sys.argv.index("--self-test") + 1])
            else:
                raise SystemExit("need --self-test /path/to/cache/copy")
        return self_test(copy)
    if "--plan" in sys.argv:
        print(json.dumps(counts_only(), ensure_ascii=False, indent=1))
        return 0
    if "--dry-run" in sys.argv:
        if "--cache-dir" not in sys.argv:
            raise SystemExit("need --dry-run --cache-dir /path/to/copy")
        copy = Path(sys.argv[sys.argv.index("--cache-dir") + 1])
        return self_test(copy)
    if "--live" in sys.argv and "--gemini-9router" in sys.argv and "--voter3-deepseek" not in sys.argv:
        raise SystemExit("Addendum 7e: --gemini-9router now runs voter 3 = DeepSeek; pass --voter3-deepseek to confirm")
    if "--live" not in sys.argv:
        raise SystemExit("need --live, --plan, --dry-run, or --self-test")
    if "--design-7e2" in sys.argv or "--design-7e4" in sys.argv:
        raise SystemExit("Addendum 7e5: --design-7e2/--design-7e4 are retired (Sol reviewer changed to cx/gpt-6-sol); use --design-7e5")
    design = "--design-7e5" in sys.argv
    if "--wall-deadline" not in sys.argv:
        raise SystemExit("Addendum 7e3: the live scheduler must run with --wall-deadline (hard per-call wall-clock deadline)")
    if not design:
        raise SystemExit("Addendum 7e5: the live scheduler must run with --design-7e5 (no --ag-from-remote / --gemini-9router)")
    if "--ag-from-remote" in sys.argv or "--gemini-9router" in sys.argv:
        raise SystemExit("Addendum 7e1: --design-7e1 excludes --ag-from-remote / --gemini-9router (Claude/Gemini are not voters)")
    assert all(v.startswith("cx/") and not v.startswith(BANNED) and "claude" not in v for v in E.VOTERS) and len(E.VOTERS) == 3, E.VOTERS
    if E.S.MODEL != "cx/gpt-6-sol" or E.S.MODEL in E.SOL_REFUSED or E.SOL_EXPECT != "gpt-6-sol" or E.S.REASONING_EFFORT != "medium":
        raise SystemExit("Addendum 7e5: Sol must be cx/gpt-6-sol medium")
    key = os.environ.get("NINE_ROUTER_API_KEY", "")
    if not key:
        raise SystemExit("key not set")
    # refuse to start if another evaluator owns the journals
    import subprocess
    out = subprocess.check_output(["pgrep", "-af", "chain_eval|retry_failed|run_eval2|parallel_eval"], text=True)
    others = [l for l in out.splitlines() if l.strip() and str(os.getpid()) not in l.split()[0]
              and "pgrep" not in l and "self-test" not in l]
    if others:
        raise SystemExit("other eval process still running:\n" + "\n".join(others))
    import fcntl
    lf = open(LOCKF, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("parallel.lock already held")
    lf.write(str(os.getpid())); lf.flush()
    stopflag = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stopflag.set())
    signal.signal(signal.SIGINT, lambda *a: stopflag.set())
    E.C = LIVE_C
    sess = R.CapSess()
    if "--wall-deadline" in sys.argv:
        # Addendum 7e3: enforce the specified per-call timeouts (120 s voters, 240 s Sol) as a hard wall-clock deadline
        import types
        import deadline_http as DH
        sess.s = DH.DeadlineSession()
        P.requests = types.SimpleNamespace(post=DH.DeadlineSession().post)  # ag re-probes too

    def call_fn(stage, j):
        if stage == "voters":
            rec = E.voter_call(sess, j, key)
        elif stage == "sol":
            rec = E.sol_call(sess, j, key)
        else:
            rec = E.t4_call(sess, j, key)
        rec["item_id"] = j["item_id"]
        rec["requested_model"] = j["model"]
        if rec.get("status") != "ok" and getattr(sess.tl, "err", None):
            rec["error_detail"] = sess.tl.err
        rec["ts"] = time.time()
        return rec

    def status_fn(state, **kw):
        write_status(state, **kw)

    return run_scheduler(LIVE_C, live=True, key=key, call_fn=call_fn, stopflag=stopflag, status_fn=status_fn,
                         ag_from_remote="--ag-from-remote" in sys.argv,
                         gemini_9router="--gemini-9router" in sys.argv,
                         hold_lanes=tuple(x for x in (sys.argv[sys.argv.index("--hold-lanes") + 1].split(",") if "--hold-lanes" in sys.argv else []) if x),
                         design_7e1=design)


if __name__ == "__main__":
    sys.exit(main())
