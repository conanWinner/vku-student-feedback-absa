"""Import Addendum 7 local-CLI voter results into the box journal.
Validates with the official schema. Never duplicates an ok cache_key.
Sensitivity records are not imported into the scoring journal."""
from __future__ import annotations
import collections, hashlib, json, os, sys, threading, time
from pathlib import Path

import run_eval as E
sys.path.insert(0, str(Path("/workspace/relabel-pilot-v3-20261108/relabel_pilot_bundle_v3")))
from review_pilot.schema import validate_annotation
from review_pilot.guideline import prompt_sha256
from review_pilot.config import GUIDELINE_VERSION
from review_pilot.client import _json_object

REMOTE_DIR = E.OUT / "remote_ag"
RESULTS = REMOTE_DIR / "results.jsonl"
IMPORTED_MARK = REMOTE_DIR / "imported_ids.jsonl"
QUARANTINE_MARK = REMOTE_DIR / "quarantine_agy_7b.jsonl"
PSHA = prompt_sha256()
CLAUDE_EXPECT = "claude-sonnet-5-5"


def _already():
    p = IMPORTED_MARK
    if not p.exists():
        return set()
    return {(r.get("cache_key"), r.get("attempt") or 1, r.get("kind"))
            for r in E.read(p)}


def _quarantined():
    if not QUARANTINE_MARK.exists():
        return set()
    return {(r.get("cache_key"), r.get("attempt") or 1) for r in E.read(QUARANTINE_MARK)}


def _has_ok(groups, key):
    recs = E.usable_call_records(groups.get(key, []))
    return any(r.get("status") == "ok" for r in recs)


def _is_excluded_remote(remote):
    if remote.get("excluded") or remote.get("voided") or remote.get("quarantine") or remote.get("status") in ("voided", "unused"):
        return True
    return (remote.get("cache_key"), remote.get("attempt") or 1) in _quarantined()


def classify(remote: dict, sentence: str) -> dict:
    """Build a journal-shaped voter record from a remote result. Official validator only."""
    rec = {
        "cache_key": remote["cache_key"],
        "requested_model": remote["requested_model"],
        "prompt_sha256": remote.get("prompt_sha256") or PSHA,
        "guideline_version": GUIDELINE_VERSION,
        "endpoint": "cli:" + (remote.get("cli") or remote.get("route") or "unknown"),
        "route": remote.get("route") or remote.get("cli"),
        "cli_model": remote.get("cli_model"),
        "status": remote.get("status") or "parse_error",
        "http_status": None,
        "returned_model": remote.get("returned_model"),
        "returned_model_source": remote.get("returned_model_source"),
        "finish_reason": None,
        "usage": remote.get("usage"),
        "annotation": None,
        "error": remote.get("error"),
        "raw_sha256": remote.get("raw_sha256"),
        "circuit": None,
        "item_id": remote["item_id"],
        "ts": remote.get("ts") or time.time(),
        "attempt": remote.get("attempt") or 1,
        "addendum": 7,
        "kind": remote.get("kind"),
        "latency_s": remote.get("latency_s"),
    }
    if remote.get("retry_of"):
        rec["retry_of"] = remote["retry_of"]
    # transport / cli failures stay non-votes
    if rec["status"] in ("transport_error", "cli_error", "rate_limit"):
        return rec
    content = remote.get("content")
    if rec["status"] in ("parse_error",) and not content:
        return rec
    if not isinstance(content, str) or not content.strip():
        rec["status"] = "parse_error"
        rec["error"] = rec["error"] or "empty_content"
        return rec
    # returned-model check (Addendum 7)
    model = rec.get("returned_model")
    src = rec.get("returned_model_source")
    req = rec["requested_model"]
    if req == "ag/claude-sonnet-5-5-low":
        if model != CLAUDE_EXPECT:
            rec["status"] = "model_mismatch"
            rec["error"] = f"returned:{model}:source:{src}"
            rec["annotation_unused"] = None
            return rec
    elif req == "ag/gemini-3.8-flash-high":
        if src != "cli_model_flag" and isinstance(model, str) and model and ("gemini-3.8-flash-high" not in model and model != "gemini-3.8-flash-n"):
            rec["status"] = "model_mismatch"
            rec["error"] = f"returned:{model}:source:{src}"
            return rec
        # missing model id is allowed if source is cli_model_flag (documented evidence)
    try:
        parsed = _json_object(content)
    except json.JSONDecodeError:
        rec["status"] = "parse_error"
        rec["error"] = "malformed_json"
        return rec
    annotation, error = validate_annotation(sentence, parsed)
    if error:
        rec["status"] = "schema_error"
        rec["error"] = error
        return rec
    rec["status"] = "ok"
    rec["annotation"] = annotation
    rec["error"] = None
    return rec


def sentences_by_item():
    return {it["item_id"]: it["sentence"] for it in E.ITEMS}


def import_new(results_path=None, lock=None, only_models=None):
    """only_models (Addendum 7c): import only these requested_models; other scoring lines are marked excluded."""
    results_path = Path(results_path or RESULTS)
    if not results_path.exists():
        return {"imported": 0, "skipped": 0, "ok": 0, "fail": 0, "missing_file": True}
    E.C = E.OUT / "cache"
    groups = E.grouped_calls(E.C / "voters_calls.jsonl")
    seen = _already()
    sent = sentences_by_item()
    n_imp = n_skip = n_ok = n_fail = 0
    ctx = lock or threading.Lock()
    for remote in E.read(results_path):
        key = remote.get("cache_key")
        att = remote.get("attempt") or 1
        kind = remote.get("kind")
        mark = (key, att, kind)
        if mark in seen:
            n_skip += 1
            continue
        if _is_excluded_remote(remote):
            E.app(IMPORTED_MARK, {"cache_key": key, "attempt": att, "kind": kind, "status": "quarantined_7b", "ts": time.time()})
            seen.add(mark)
            n_skip += 1
            continue
        if only_models is not None and kind != "sensitivity" and remote.get("requested_model") not in only_models:
            E.app(IMPORTED_MARK, {"cache_key": key, "attempt": att, "kind": kind, "status": "excluded_7c_route_abandoned",
                                  "requested_model": remote.get("requested_model"), "ts": time.time()})
            seen.add(mark)
            n_skip += 1
            continue
        if kind == "sensitivity":
            # never into the scoring journal; just mark seen
            E.app(IMPORTED_MARK, {"cache_key": key, "attempt": att, "kind": kind, "status": "sensitivity_not_scored", "ts": time.time()})
            seen.add(mark)
            n_skip += 1
            continue
        if key and _has_ok(groups, key):
            E.app(IMPORTED_MARK, {"cache_key": key, "attempt": att, "kind": kind, "status": "skipped_already_ok", "ts": time.time()})
            seen.add(mark)
            n_skip += 1
            continue
        # already have this attempt in the journal (e.g. 9router attempt)
        existing = groups.get(key, [])
        if any((r.get("attempt") or 1) == att and r.get("addendum") == 7 for r in existing):
            E.app(IMPORTED_MARK, {"cache_key": key, "attempt": att, "kind": kind, "status": "skipped_attempt_present", "ts": time.time()})
            seen.add(mark)
            n_skip += 1
            continue
        iid = remote.get("item_id")
        if iid not in sent:
            n_skip += 1
            continue
        rec = classify(remote, sent[iid])
        rec["imported_from"] = str(results_path.name)
        intent = {
            "item_id": iid, "cache_key": key, "model": rec["requested_model"],
            "status": "issued_retry" if rec.get("attempt", 1) > 1 else "issued",
            "attempt": rec.get("attempt") or 1, "addendum": 7, "route": rec.get("route"),
        }
        with ctx:
            # skip if a 9router first-attempt orphan/record already used this attempt number
            # still append addendum-7 retry/first as a new attempt line (same cache_key, new attempt)
            E.app(E.C / "voters_intent.jsonl", intent)
            E.app(E.C / "voters_calls.jsonl", rec)
            E.app(IMPORTED_MARK, {"cache_key": key, "attempt": att, "kind": kind, "status": rec["status"], "ts": time.time()})
        groups.setdefault(key, []).append(rec)
        seen.add(mark)
        n_imp += 1
        if rec["status"] == "ok":
            n_ok += 1
        else:
            n_fail += 1
    return {"imported": n_imp, "skipped": n_skip, "ok": n_ok, "fail": n_fail, "missing_file": False}


def main():
    r = import_new()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
