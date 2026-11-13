"""Addendum 7e1: import remote stage-3 (Claude Code CLI, claude-sonnet-5-5, --effort medium) results into cache/t4_calls.jsonl.
Validates job match, model/effort tags, returned model and the official annotation schema. Append-only; each job imported once;
an already-ok key is never imported again. Human labels are never loaded. Not gold."""
from __future__ import annotations
import json, sys, threading, time
from pathlib import Path

import run_eval as E
from review_pilot.schema import validate_annotation
from review_pilot.config import GUIDELINE_VERSION
from review_pilot.client import _json_object

RETURNED_EXPECT = E.EXPECT[E.T4]  # claude-sonnet-5-5
NONVOTE_STATUSES = ("transport_error", "cli_error", "rate_limit", "parse_error")


def classify(remote: dict, job: dict) -> dict:
    rec = {
        "cache_key": job["cache_key"], "requested_model": E.T4, "item_id": job["item_id"], "attempt": job["attempt"],
        "job_id": job["job_id"], "stage": "t4", "prompt_sha256": job["prompt_sha256"], "guideline_version": GUIDELINE_VERSION,
        "endpoint": "cli:claude-code", "route": E.T4_ROUTE, "cli_model": remote.get("cli_model"), "effort": remote.get("effort"),
        "status": remote.get("status") or "parse_error", "http_status": None,
        "returned_model": remote.get("returned_model"), "returned_model_source": remote.get("returned_model_source"),
        "usage": remote.get("usage"), "num_turns": remote.get("num_turns"), "annotation": None,
        "error": remote.get("error"), "raw_sha256": remote.get("raw_sha256"), "latency_s": remote.get("latency_s"),
        "isolation": remote.get("isolation"), "ts": remote.get("ts") or time.time(), "route_addendum": "7e1",
    }
    if job["attempt"] > 1:
        rec["addendum"] = 5
    if rec["status"] in ("transport_error", "cli_error", "rate_limit"):
        return rec
    content = remote.get("content")
    if not isinstance(content, str) or not content.strip():
        rec["status"] = "parse_error"; rec["error"] = rec["error"] or "empty_content"
        return rec
    if rec["returned_model"] != RETURNED_EXPECT:
        rec["status"] = "model_mismatch"; rec["error"] = f"returned:{rec['returned_model']}:source:{rec['returned_model_source']}"
        return rec
    try:
        parsed = _json_object(content)
    except json.JSONDecodeError:
        rec["status"] = "parse_error"; rec["error"] = "malformed_json"
        return rec
    annotation, error = validate_annotation(job["sentence"], parsed)
    if error:
        rec["status"] = "schema_error"; rec["error"] = error
        return rec
    rec["status"] = "ok"; rec["annotation"] = annotation; rec["error"] = None
    return rec


def import_new(cache, results_path, jobs_path, mark_path, lock=None):
    cache, results_path, jobs_path, mark_path = map(Path, (cache, results_path, jobs_path, mark_path))
    if not results_path.exists():
        return {"imported": 0, "rejected": 0, "missing_file": True}
    jobs = {j["job_id"]: j for j in E.read(jobs_path)}
    seen = {r.get("job_id") for r in E.read(mark_path)}
    groups = E.grouped_calls(cache / "t4_calls.jsonl")
    sent = {it["item_id"]: it["sentence"] for it in E.ITEMS}
    ctx = lock or threading.Lock()
    n_imp = n_ok = n_rej = n_skip = 0
    for remote in E.read(results_path):
        jid = remote.get("job_id")
        if jid in seen:
            continue
        job = jobs.get(jid)
        why = None
        if job is None:
            why = "rejected_unknown_job"
        elif (remote.get("cache_key"), remote.get("attempt"), remote.get("item_id")) != (job["cache_key"], job["attempt"], job["item_id"]):
            why = "rejected_job_mismatch"
        elif sent.get(job["item_id"]) != job["sentence"] or remote.get("sentence_sha256") not in (None, E.hashlib.sha256(job["sentence"].encode()).hexdigest()):
            why = "rejected_sentence_mismatch"
        elif remote.get("requested_model") != E.T4 or remote.get("cli_model") != E.T4_CLI_MODEL or remote.get("effort") != E.T4_EFFORT:
            why = "rejected_tag_mismatch"
        elif remote.get("prompt_sha256") != job["prompt_sha256"] or not str(job["prompt_sha256"]).startswith("74d0fd7d"):
            why = "rejected_prompt_sha"
        if why:
            with ctx:
                E.app(mark_path, {"job_id": jid, "status": why, "ts": time.time()})
            seen.add(jid); n_rej += 1
            continue
        key, att = job["cache_key"], job["attempt"]
        usable = E.usable_call_records(groups.get(key, []))
        if any(r.get("status") == "ok" for r in usable):
            with ctx:
                E.app(mark_path, {"job_id": jid, "status": "skipped_already_ok", "ts": time.time()})
            seen.add(jid); n_skip += 1
            continue
        if any((r.get("attempt") or 1) == att for r in groups.get(key, [])):
            with ctx:
                E.app(mark_path, {"job_id": jid, "status": "skipped_attempt_present", "ts": time.time()})
            seen.add(jid); n_skip += 1
            continue
        rec = classify(remote, job)
        rec["imported_from"] = results_path.name
        with ctx:
            E.app(cache / "t4_calls.jsonl", rec)
            E.app(mark_path, {"job_id": jid, "status": rec["status"], "ts": time.time()})
        groups.setdefault(key, []).append(rec)
        seen.add(jid); n_imp += 1; n_ok += rec["status"] == "ok"
    return {"imported": n_imp, "ok": n_ok, "rejected": n_rej, "skipped": n_skip, "missing_file": False}


if __name__ == "__main__":
    d = E.OUT
    print(json.dumps(import_new(E.C, d / "remote_t4" / "results.jsonl", d / "remote_t4_payload" / "jobs_t4.jsonl",
                                d / "remote_t4" / "imported_ids.jsonl"), indent=1))
