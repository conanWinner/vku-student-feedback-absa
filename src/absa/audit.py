"""Annotation audit (RQ1): draw the blind sample, then score the two filled sheets.

    python -m absa.audit sample
    python -m absa.audit score

Annotators receive only `audit_annotator_A.csv` or `audit_annotator_B.csv`. In each aspect
column they write `pos`, `neg` or `neu` if the sentence mentions that aspect, and leave it
blank otherwise. `audit_key.csv` holds the current labels and must not be shown to them.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import numpy as np

from .aspects import ASPECT_DESCRIPTIONS
from .data import ASPECTS, IGNORE_INDEX, POLARITIES, load_split

CODE_TO_POLARITY = {"neg": 0, "neu": 1, "pos": 2}
POLARITY_TO_CODE = {POLARITIES.index(name): code for code, name in (("neg", "negative"), ("neu", "neutral"), ("pos", "positive"))}
SAMPLE_SEED = 20261101


def draw_sample(samples, size: int = 300, per_aspect: int = 30, seed: int = SAMPLE_SEED, exclude: set[str] = frozenset()):
    """Stratified sample: rarest aspects first until each has `per_aspect`, then uniform fill."""
    rng = random.Random(seed)
    pool = [s for s in samples if s.uid not in exclude]
    rng.shuffle(pool)
    chosen, chosen_ids = [], set()
    counts = {a: 0 for a in range(len(ASPECTS))}
    available = {a: sum(s.aspect[a] > 0 for s in pool) for a in counts}
    if min(available.values()) < per_aspect:
        raise ValueError(f"not enough sentences per aspect: {available}")

    for a in sorted(counts, key=available.get):
        for s in pool:
            if counts[a] >= per_aspect:
                break
            if s.uid not in chosen_ids and s.aspect[a] > 0:
                chosen.append(s)
                chosen_ids.add(s.uid)
                for b in counts:
                    counts[b] += int(s.aspect[b] > 0)
    if len(chosen) > size:
        raise ValueError(f"{len(chosen)} sentences are needed for the strata; raise size or lower per_aspect")
    stratified = len(chosen)
    for s in pool:
        if len(chosen) >= size:
            break
        if s.uid not in chosen_ids:
            chosen.append(s)
            chosen_ids.add(s.uid)
    return chosen, stratified


def _write(path: Path, rows, header) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_sheets(samples, out_dir: Path, stratified: int, seed: int = SAMPLE_SEED) -> None:
    """One sheet per annotator with different orders, and one key file for scoring."""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [(f"Q{i:03d}", s) for i, s in enumerate(samples, start=1)]
    for name, order_seed in (("A", seed + 1), ("B", seed + 2)):
        shuffled = items[:]
        random.Random(order_seed).shuffle(shuffled)
        _write(
            out_dir / f"audit_annotator_{name}.csv",
            [[item, s.text, *[""] * len(ASPECTS)] for item, s in shuffled],
            ["item", "text", *ASPECTS],
        )
    _write(
        out_dir / "audit_key.csv",
        [[item, s.uid, "stratified" if i < stratified else "uniform_fill",
          *[POLARITY_TO_CODE.get(int(v), "") for v in s.sentiment]] for i, (item, s) in enumerate(items)],
        ["item", "uid", "stratum", *ASPECTS],
    )
    guide = ["# Hướng dẫn gán nhãn đối chứng", "",
             "Làm độc lập, không trao đổi và không xem nhãn có sẵn.",
             "Với mỗi câu, ở cột khía cạnh được nhắc đến ghi `pos`, `neg` hoặc `neu`; để trống các cột còn lại.",
             "Một câu có thể có nhiều khía cạnh. Mỗi câu phải có ít nhất một khía cạnh; nếu không rõ, dùng `noi_chung`.", "",
             "## Quy tắc", "",
             "- Chỉ ghi một khía cạnh khi câu có bằng chứng rõ; không suy diễn.",
             "- Nếu câu góp ý về một khía cạnh cụ thể, ghi cả khía cạnh đó và `de_xuat`.",
             "- Không dùng `noi_chung` khi đã có khía cạnh cụ thể rõ ràng, trừ khi câu có thêm một nhận xét chung riêng.",
             "- `pos`: khen, hài lòng. `neg`: chê, không hài lòng.",
             "- `neu`: nêu sự việc hoặc góp ý trung lập, không khen chê rõ.", "",
             "## 11 khía cạnh", ""]
    guide += [f"- `{name}`: {ASPECT_DESCRIPTIONS[name]}" for name in ASPECTS]
    (out_dir / "audit_guideline.md").write_text("\n".join(guide) + "\n", encoding="utf-8")


def cohen_kappa(a: np.ndarray, b: np.ndarray) -> float | None:
    """Cohen's kappa for two label sequences. None if chance agreement is 1 (kappa undefined)."""
    labels = np.unique(np.concatenate([a, b]))
    observed = float((a == b).mean())
    expected = sum(float((a == x).mean()) * float((b == x).mean()) for x in labels)
    return None if expected >= 1.0 else (observed - expected) / (1.0 - expected)


def read_sheet(path: Path) -> dict[str, np.ndarray]:
    """item -> polarity id per aspect, IGNORE_INDEX where blank. Invalid or unfinished sheets raise."""
    table = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            values = []
            for name in ASPECTS:
                cell = row[name].strip().lower()
                if cell and cell not in CODE_TO_POLARITY:
                    raise ValueError(f"{path.name} {row['item']}: invalid value {cell!r} in {name}")
                values.append(CODE_TO_POLARITY.get(cell, IGNORE_INDEX))
            if all(v == IGNORE_INDEX for v in values):
                raise ValueError(f"{path.name} {row['item']}: no aspect filled in")
            table[row["item"]] = np.array(values)
    return table


def agreement(a: np.ndarray, b: np.ndarray) -> dict:
    """Agreement between two label matrices of shape (N, A)."""
    per_aspect, both = {}, []
    for i, name in enumerate(ASPECTS):
        present_a, present_b = a[:, i] != IGNORE_INDEX, b[:, i] != IGNORE_INDEX
        per_aspect[name] = {"kappa_presence": cohen_kappa(present_a, present_b), "n_a": int(present_a.sum()), "n_b": int(present_b.sum())}
        shared = present_a & present_b
        both.append((a[shared, i], b[shared, i]))
    defined = [v["kappa_presence"] for v in per_aspect.values() if v["kappa_presence"] is not None]
    sent_a, sent_b = np.concatenate([x for x, _ in both]), np.concatenate([y for _, y in both])
    return {
        "n_sentences": len(a),
        "mean_kappa_presence": float(np.mean(defined)) if defined else None,
        "kappa_sentiment_on_shared_aspects": cohen_kappa(sent_a, sent_b) if sent_a.size else None,
        "n_shared_pairs": int(sent_a.size),
        "exact_match_sentence": float((a == b).all(axis=1).mean()),
        "per_aspect": per_aspect,
    }


def score(sheet_dir: Path) -> dict:
    a = read_sheet(sheet_dir / "audit_annotator_A.csv")
    b = read_sheet(sheet_dir / "audit_annotator_B.csv")
    current = {}
    with (sheet_dir / "audit_key.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            current[row["item"]] = np.array([CODE_TO_POLARITY.get(row[n], IGNORE_INDEX) for n in ASPECTS])
    items = sorted(current)
    if set(a) != set(items) or set(b) != set(items):
        raise ValueError("sheets and key do not hold the same items")
    A, B, C = (np.stack([t[i] for i in items]) for t in (a, b, current))
    return {
        "sampling": "stratified with rare aspects oversampled; not an unweighted estimate of the whole dataset",
        "annotator_A_vs_B": agreement(A, B),
        "annotator_A_vs_dataset": agreement(A, C),
        "annotator_B_vs_dataset": agreement(B, C),
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["sample", "score"])
    parser.add_argument("--data-dir", default="data/Final_Data")
    parser.add_argument("--out-dir", default="data/annotation/audit")
    parser.add_argument("--review-file", default="data/annotation/added_51_review.csv")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)

    if args.command == "sample":
        # The 51 added sentences did not go through the original workflow this audit measures.
        with open(args.review_file, encoding="utf-8-sig", newline="") as f:
            exclude = {f"test:{r['new_id']}" for r in csv.DictReader(f) if r["original_split"] == "test"}
        chosen, stratified = draw_sample(load_split(args.data_dir, "test"), exclude=exclude)
        write_sheets(chosen, out_dir, stratified)
        counts = {name: sum(int(s.aspect[i] > 0) for s in chosen) for i, name in enumerate(ASPECTS)}
        print(json.dumps({"sentences": len(chosen), "stratified": stratified, "excluded_added": len(exclude), "per_aspect": counts}, indent=2))
    else:
        report = score(out_dir)
        (out_dir / "audit_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: v for k, v in report["annotator_A_vs_B"].items() if k != "per_aspect"}, indent=2))


if __name__ == "__main__":
    main()
