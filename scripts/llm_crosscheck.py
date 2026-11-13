"""Blind LLM cross-check of the released labels on a random sample.

Steps (run in order):
  sample     draw the sentence sample (fixed seed, stratified by split, 51 restored sentences excluded)
  label      ask one model through an OpenAI-compatible endpoint (9router) to label the sample blind
  adjudicate write a sheet where a human resolves every cell on which the sources disagree,
             with the candidate labels shuffled so the source is hidden
  score      agreement of each model with the released labels and with each other, plus
             accuracy of every source on the adjudicated cells

This measures consistency between label sources. It is not inter-annotator agreement,
and it never changes data/Final_Data.

Environment for `label`: ROUTER_BASE_URL (default http://localhost:20128/v1) and
ROUTER_API_KEY (optional). The key is read from the environment and never written out.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from absa.data import ASPECTS, POLARITIES, dataset_hash, load_split  # noqa: E402

DATA_DIR = ROOT / "data" / "Final_Data"
OUT_DIR = ROOT / "results" / "llm_crosscheck"
SHEET = ROOT / "data" / "annotation" / "crosscheck" / "adjudication.csv"
SHEET_KEY = OUT_DIR / "adjudication_key.json"
ADDED = ROOT / "data" / "annotation" / "added_51_review.csv"
LABELS = ("none",) + POLARITIES  # cell value: none or a polarity
SAMPLE_SIZE = 500
SEED = 20261103

# The original gpt-oss prompt (For Train 6.json) with the UIT-VSFC hints and the
# confidence field removed, so the model sees only the sentence.
SYSTEM_PROMPT = """You are an expert Vietnamese ABSA data annotator for student feedback.

Task: assign sentiment to 11 aspects. Each aspect must be one of:
"positive", "negative", "neutral", "none".

A sentence may contain multiple aspects. Sentiment must be assigned per aspect.

Aspects:
ky_nang_giang_day: teaching method, explanation, delivery, easy/hard to understand, teaching speed.
kinh_nghiem: practical experience, real-world examples, practical relevance.
hanh_vi: attitude, behavior, communication, enthusiasm, friendliness, support.
bai_tap: assignments, exercises, practice tasks, projects, amount, difficulty, deadlines.
cham_diem: grades, grading method, criteria, fairness of assessment.
cung_cap_tai_lieu: slides, textbooks, learning materials, syllabus, learning resources.
kien_thuc: professional knowledge, expertise, correctness/usefulness of knowledge.
chuong_trinh_hoc: course, curriculum, subject content, course structure, duration.
thiet_bi_day_hoc: classroom, projector, computer, speaker, mic, fan, light, lab, facilities.
de_xuat: suggestion/request for improvement. Signals: nên, cần, mong, đề nghị, hy vọng, nếu được.
noi_chung: general feedback, too short or too vague for specific aspects.

Rules:
- Assign an aspect only if there is clear evidence in the sentence.
- Do not over-infer.
- Missing aspects = "none".
- Do not use noi_chung if a specific aspect is clearly present, unless there is a separate general comment.
- If there is a suggestion about a specific aspect, label both that aspect and de_xuat.
- positive = praise/satisfaction: tốt, hay, dễ hiểu, nhiệt tình, hữu ích, đầy đủ, công bằng, rõ ràng.
- negative = complaint/dissatisfaction: khó hiểu, thiếu, chưa tốt, quá nhiều, quá ít, không rõ, không công bằng.
- neutral = factual or neutral suggestion, no clear praise/complaint.
- Every sentence has at least one aspect that is not "none".

Return only valid JSON. No markdown. No explanation.

Schema:
{
  "ky_nang_giang_day": "...",
  "kinh_nghiem": "...",
  "hanh_vi": "...",
  "bai_tap": "...",
  "cham_diem": "...",
  "cung_cap_tai_lieu": "...",
  "kien_thuc": "...",
  "chuong_trinh_hoc": "...",
  "thiet_bi_day_hoc": "...",
  "de_xuat": "...",
  "noi_chung": "..."
}"""
PROMPT_SHA = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


def released() -> dict[str, dict]:
    """uid -> {split, text, cells}, cells = one LABELS value per aspect."""
    out = {}
    for split in ("train", "validation", "test"):
        for s in load_split(DATA_DIR, split):
            cells = {a: (POLARITIES[s.sentiment[i]] if s.aspect[i] else "none") for i, a in enumerate(ASPECTS)}
            out[s.uid] = {"split": split, "text": s.text, "cells": cells}
    return out


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


# ---------------------------------------------------------------- sample
def cmd_sample(args) -> None:
    data = released()
    with ADDED.open(encoding="utf-8") as f:
        added = {f"{Path(r['file']).stem}:{r['new_id']}" for r in csv.DictReader(f)}
    assert len(added) == 51 and added <= data.keys()
    rng = random.Random(SEED)
    pool = {sp: sorted(u for u, d in data.items() if d["split"] == sp and u not in added) for sp in ("train", "validation", "test")}
    total = sum(len(v) for v in pool.values())
    quota = {sp: round(SAMPLE_SIZE * len(v) / total) for sp, v in pool.items()}
    quota["train"] += SAMPLE_SIZE - sum(quota.values())
    uids = [u for sp in pool for u in rng.sample(pool[sp], quota[sp])]
    rng.shuffle(uids)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {"seed": SEED, "size": len(uids), "quota": quota, "excluded": "51 restored sentences (Claude-proposed labels)",
           "dataset_sha256": dataset_hash(DATA_DIR), "uids": uids}
    (OUT_DIR / "sample.json").write_text(json.dumps(out, indent=1))
    print(f"sample: {len(uids)} sentences {quota}")


def load_sample() -> list[str]:
    return json.loads((OUT_DIR / "sample.json").read_text())["uids"]


# ---------------------------------------------------------------- label
def parse_cells(content: str) -> dict[str, str] | None:
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    cells = {a: str(obj.get(a, "none")).strip().lower() for a in ASPECTS}
    return cells if all(v in LABELS for v in cells.values()) else None


def call(base: str, key: str | None, model: str, text: str, timeout: int) -> dict:
    body = {"model": model, "temperature": 0, "stream": False, "messages": [
        {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f'sentence="{text}"'}]}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{base.rstrip('/')}/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    if not raw.lstrip().startswith("data:"):
        return json.loads(raw)
    # Some providers stream even when asked not to: join the deltas.
    content, model_returned = [], None
    for line in raw.splitlines():
        if not line.startswith("data:") or line.strip() == "data: [DONE]":
            continue
        chunk = json.loads(line[5:])
        model_returned = chunk.get("model") or model_returned
        for ch in chunk.get("choices", []):
            content.append((ch.get("delta") or {}).get("content") or "")
    return {"model": model_returned, "choices": [{"message": {"content": "".join(content)}}]}


def cmd_label(args) -> None:
    base = os.environ.get("ROUTER_BASE_URL", "http://localhost:20128/v1")
    key = os.environ.get("ROUTER_API_KEY") or None
    data, uids = released(), load_sample()
    if args.limit:
        uids = uids[: args.limit]
    path = OUT_DIR / f"labels_{slug(args.model)}.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["cells"] is not None:
                done.add(rec["uid"])
    todo = [u for u in uids if u not in done]
    print(f"{args.model}: {len(done)} done, {len(todo)} to label, endpoint {base}")

    def one(uid: str) -> dict:
        rec = {"uid": uid, "model_requested": args.model, "prompt_sha256": PROMPT_SHA, "temperature": 0}
        for attempt in range(args.retries):
            try:
                resp = call(base, key, args.model, data[uid]["text"], args.timeout)
                content = resp["choices"][0]["message"]["content"] or ""
                rec.update(model_returned=resp.get("model"), content=content, cells=parse_cells(content),
                           time=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), attempts=attempt + 1)
                if rec["cells"] is not None:
                    return rec
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                rec.update(error=f"{type(e).__name__}: {str(e)[:200]}", cells=None)
            time.sleep(2 * (attempt + 1))
        return rec

    with path.open("a", encoding="utf-8") as f, cf.ThreadPoolExecutor(args.workers) as ex:
        for i, rec in enumerate(ex.map(one, todo), 1):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if rec["cells"] is None:
                print(f"  failed {rec['uid']}: {rec.get('error') or rec.get('content', '')[:80]}")
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}")
    returned = {json.loads(l).get("model_returned") for l in path.read_text(encoding="utf-8").splitlines()}
    print(f"models returned by the endpoint: {sorted(map(str, returned))}")


def load_labels(model: str) -> dict[str, dict[str, str]]:
    out = {}
    for line in (OUT_DIR / f"labels_{slug(model)}.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["cells"] is not None:
            out[rec["uid"]] = rec["cells"]
    return out


# ---------------------------------------------------------------- adjudicate
def cmd_adjudicate(args) -> None:
    data, uids = released(), load_sample()
    models = {m: load_labels(m) for m in args.models}
    uids = [u for u in uids if all(u in v for v in models.values())]
    rng = random.Random(SEED + 1)
    rows, key = [], {}
    for uid in uids:
        for a in ASPECTS:
            sources = {"released": data[uid]["cells"][a], **{m: models[m][uid][a] for m in args.models}}
            if len(set(sources.values())) == 1:
                continue
            options = sorted(set(sources.values()))
            rng.shuffle(options)
            cell = f"{uid}|{a}"
            key[cell] = sources
            rows.append({"cell": cell, "text": data[uid]["text"], "aspect": a,
                         **{f"option_{i + 1}": o for i, o in enumerate(options)}, "human": "", "note": ""})
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    if SHEET.exists() and not args.force:
        sys.exit(f"{SHEET} exists; pass --force to overwrite it")
    with SHEET.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["cell", "text", "aspect", "option_1", "option_2", "option_3", "human", "note"])
        w.writeheader()
        w.writerows(rows)
    SHEET_KEY.write_text(json.dumps({"models": args.models, "cells": key}, indent=1))
    print(f"{len(rows)} disagreeing cells in {len({r['cell'].split('|')[0] for r in rows})} sentences -> {SHEET}")
    print("Fill `human` with none/positive/negative/neutral (any value, not only the options). Source is hidden.")


# ---------------------------------------------------------------- score
def kappa(x: list[str], y: list[str]) -> float:
    idx = {v: i for i, v in enumerate(LABELS)}
    m = np.zeros((len(LABELS), len(LABELS)))
    for a, b in zip(x, y):
        m[idx[a], idx[b]] += 1
    n = m.sum()
    po = np.trace(m) / n
    pe = (m.sum(0) * m.sum(1)).sum() / n**2
    return float((po - pe) / (1 - pe)) if pe < 1 else 1.0


def compare(a: dict, b: dict, uids: list[str]) -> dict:
    xa = [a[u][s] for u in uids for s in ASPECTS]
    xb = [b[u][s] for u in uids for s in ASPECTS]
    pa = {(u, s, a[u][s]) for u in uids for s in ASPECTS if a[u][s] != "none"}
    pb = {(u, s, b[u][s]) for u in uids for s in ASPECTS if b[u][s] != "none"}
    da = {x[:2] for x in pa}
    db = {x[:2] for x in pb}
    f1 = lambda p, q: 2 * len(p & q) / (len(p) + len(q)) if p or q else 1.0  # symmetric F1
    return {"cells": len(xa), "cell_kappa": round(kappa(xa, xb), 4),
            "pair_f1": round(100 * f1(pa, pb), 2), "aspect_f1": round(100 * f1(da, db), 2),
            "sentence_exact": round(100 * float(np.mean([all(a[u][s] == b[u][s] for s in ASPECTS) for u in uids])), 2)}


def cmd_score(args) -> None:
    data, uids = released(), load_sample()
    srcs = {"released": {u: data[u]["cells"] for u in uids}}
    for m in args.models:
        srcs[m] = load_labels(m)
    common = [u for u in uids if all(u in v for v in srcs.values())]
    names = list(srcs)
    out = {"sample": len(uids), "scored": len(common), "prompt_sha256": PROMPT_SHA,
           "dataset_sha256": dataset_hash(DATA_DIR), "pairs": {}}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            out["pairs"][f"{names[i]} vs {names[j]}"] = compare(srcs[names[i]], srcs[names[j]], common)
    if SHEET.exists() and SHEET_KEY.exists():
        key = json.loads(SHEET_KEY.read_text())["cells"]
        with SHEET.open(encoding="utf-8") as f:
            filled = {}
            for r in csv.DictReader(f):
                v = r["human"].strip().lower()
                if v in ("1", "2", "3"):  # the number of an option column is accepted as well
                    v = r[f"option_{v}"].strip().lower() or f"empty option_{v}"
                if v:
                    filled[r["cell"]] = v
        bad = {c: v for c, v in filled.items() if v not in LABELS}
        if bad:
            sys.exit(f"invalid `human` values: {list(bad.items())[:5]}")
        if filled:
            # Reference labels: the human value on adjudicated cells, the shared value elsewhere.
            # Only sentences whose disagreeing cells are all adjudicated are scored.
            open_uids = {c.split("|")[0] for c in key if c not in filled}
            done = [u for u in common if u not in open_uids]
            ref = {u: {s: filled.get(f"{u}|{s}", srcs["released"][u][s]) for s in ASPECTS} for u in done}
            changed = [c for c, v in filled.items() if c.split("|")[0] in ref and key[c]["released"] != v]
            kinds = {"aspect_added": 0, "aspect_removed": 0, "polarity_changed": 0}
            for c in changed:
                old, new = key[c]["released"], filled[c]
                kinds["aspect_added" if old == "none" else "aspect_removed" if new == "none" else "polarity_changed"] += 1
            out["adjudication"] = {
                "adjudicated_cells": len(filled), "disagreeing_cells": len(key), "sentences_scored": len(done),
                "released_cells_changed": len(changed), "released_change_kinds": kinds,
                "released_sentences_changed": len({c.split("|")[0] for c in changed}),
                "vs_reference": {name: compare(srcs[name], ref, done) for name in names}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps(out, indent=1))
    write_table(out, args.models)
    print(json.dumps(out, indent=1))


DISPLAY = {"released": "Released", "ag/gemini-3.8-flash": "Gemini", "ag/claude-sonnet-4-6": "Claude"}


def write_table(out: dict, models: list[str]) -> None:
    """paper/tables/crosscheck.tex from summary.json."""
    def row(label: str, r: dict) -> str:
        return (f"{label} & {r['cell_kappa']:.3f} & {r['pair_f1']:.1f} & {r['aspect_f1']:.1f} "
                f"& {r['sentence_exact']:.1f} \\\\")
    name = lambda m: DISPLAY.get(m, m)
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Comparison & $\kappa$ & Pair F1 & Aspect F1 & Exact \\", r"\midrule"]
    lines += [row(" vs ".join(name(x) for x in k.split(" vs ")), v) for k, v in out["pairs"].items()]
    adj = out.get("adjudication")
    if adj and adj["adjudicated_cells"] == adj["disagreeing_cells"]:  # partial results stay out of the paper
        lines.append(r"\midrule")
        lines += [row(f"{name(k)} vs adjudicated", v) for k, v in out["adjudication"]["vs_reference"].items()]
    lines += [r"\bottomrule", r"\end{tabular}"]
    path = ROOT / "paper" / "tables" / "crosscheck.tex"
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    q = sub.add_parser("label")
    q.add_argument("--model", required=True, help="model id exactly as 9router lists it")
    q.add_argument("--limit", type=int, default=0, help="label only the first N sentences (smoke test)")
    q.add_argument("--workers", type=int, default=4)
    q.add_argument("--retries", type=int, default=3)
    q.add_argument("--timeout", type=int, default=120)
    for name in ("adjudicate", "score"):
        q = sub.add_parser(name)
        q.add_argument("--models", nargs="+", required=True)
        if name == "adjudicate":
            q.add_argument("--force", action="store_true")
    a = p.parse_args()
    {"sample": cmd_sample, "label": cmd_label, "adjudicate": cmd_adjudicate, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
