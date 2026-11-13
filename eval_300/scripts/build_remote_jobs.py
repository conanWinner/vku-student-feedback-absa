"""Build the Addendum 7 job file for the user machine. No API keys. IDs + prompts only."""
from __future__ import annotations
import json, sys
from pathlib import Path
import run_eval as E
from parallel_eval import Journal, build_queues, next_attempt, MAX_ATTEMPTS
from review_pilot.guideline import prompt_sha256, user_message, SYSTEM_PROMPT

OUT = Path(__file__).resolve().parent
PSHA = prompt_sha256()
CLI = {
    "ag/claude-sonnet-5-5-low": ("claude-code", "claude-sonnet-5-5"),
    "ag/gemini-3.8-flash-high": ("agy", "gemini-3.8-flash-high"),
}


def prior_obj(recs):
    if not recs:
        return None
    orig = recs[0]
    return {
        "cache_key": orig.get("cache_key"),
        "status": orig.get("status"),
        "error": orig.get("error"),
        "ts": orig.get("ts"),
        "http_status": orig.get("http_status"),
        "n_prior": len(recs),
        "prior_routes": [r.get("route") or r.get("endpoint") for r in recs],
    }


def job_from(j, attempt, kind, recs):
    cli, cli_model = CLI[j["model"]]
    sent = j["sentence"]
    rec = {
        "item_id": j["item_id"],
        "cache_key": j["cache_key"],
        "requested_model": j["model"],
        "cli": cli,
        "cli_model": cli_model,
        "kind": kind,
        "attempt": attempt,
        "sentence": sent,
        "user_message": user_message(sent),
        "prompt_sha256": PSHA,
    }
    if kind == "retry":
        rec["prior"] = prior_obj(recs)
    return rec


def main():
    E.C = E.OUT / "cache"
    jnl = Journal(E.C)
    q, settled, sj = build_queues(jnl)
    scoring = []
    for w in q["ag"]:
        if w["model"] not in CLI:
            continue
        scoring.append(job_from(w["job"], w["attempt"], w["kind"], w["prior"]))
    sample = json.loads((OUT / "sensitivity_sample_addendum7.json").read_text())
    by_item = {it["item_id"]: it for it in E.ITEMS}
    vjobs = {(j["item_id"], j["model"]): j for j in E.voter_jobs()}
    sensitivity = []
    for model, ids in sample["item_ids"].items():
        for iid in ids:
            j = vjobs[(iid, model)]
            recs = jnl.groups["voters"].get(j["cache_key"], [])
            # sensitivity is a new route probe, not a scoring retry; attempt starts at 1 in a separate kind
            sensitivity.append(job_from(j, 1, "sensitivity", recs))
    data = {
        "addendum": 7,
        "prompt_sha256": PSHA,
        "guideline_version": "guideline-vi-2026-11-08-v2",
        "note": "No API keys. Scoring jobs are remaining ag-lane work only. Sensitivity jobs are NOT for scoring.",
        "jobs": scoring,
        "sensitivity_jobs": sensitivity,
        "counts": {
            "scoring": len(scoring),
            "scoring_by": {},
            "sensitivity": len(sensitivity),
        },
    }
    from collections import Counter
    data["counts"]["scoring_by"] = dict(Counter(f"{j['kind']}|{j['requested_model']}|a{j['attempt']}" for j in scoring))
    data["counts"]["sensitivity_by"] = dict(Counter(j["requested_model"] for j in sensitivity))
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (OUT / "remote_ag_payload" / "jobs.json")
    # sanity: no keys
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if "NINE_ROUTER" in text or "mongodb" in text.lower() or "MONGO" in text:
        raise SystemExit("refusing to write a jobs file that looks like it contains a secret")
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"wrote": str(out), "counts": data["counts"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
