"""Error diagnosis on validation (RQ2). Never reads the test predictions.

    python -m absa.diagnose RUN_DIR --data-dir data/Final_Data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .data import ASPECTS, IGNORE_INDEX, label_arrays, load_split
from .metrics import pair_counts, predict_aspects, select_global_threshold


def aspect_errors(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment) -> dict:
    """Per aspect: wrong detections (FP), misses (FN), and detected with the wrong sentiment."""
    gold, pred = gold_aspect.astype(bool), pred_aspect.astype(bool)
    wrong_sentiment = gold & pred & (gold_sentiment != pred_sentiment)
    return {
        name: {
            "support": int(gold[:, a].sum()),
            "false_positive": int((pred[:, a] & ~gold[:, a]).sum()),
            "missed": int((gold[:, a] & ~pred[:, a]).sum()),
            "wrong_sentiment": int(wrong_sentiment[:, a].sum()),
        }
        for a, name in enumerate(ASPECTS)
    }


def miss_confusion(gold_aspect, pred_aspect) -> np.ndarray:
    """M[i, j]: sentences where gold aspect i was missed while spurious aspect j was predicted."""
    gold, pred = gold_aspect.astype(bool), pred_aspect.astype(bool)
    return ((gold & ~pred).astype(int).T @ (pred & ~gold).astype(int))


def cooccurrence(aspect: np.ndarray) -> np.ndarray:
    """C[i, j]: training sentences holding both aspects. The diagonal is each aspect's count."""
    present = aspect.astype(int)
    return present.T @ present


def diagnose(run_dir: Path, data_dir: str) -> dict:
    predictions = np.load(run_dir / "predictions.npz")
    samples = load_split(data_dir, "validation")
    if [s.uid for s in samples] != predictions["validation_uid"].tolist():
        raise ValueError(f"predictions do not match the validation sentences in {data_dir}")
    gold_aspect, gold_sentiment = label_arrays(samples)
    prob, sentiment = predictions["validation_aspect_prob"], predictions["validation_sentiment"]
    threshold = select_global_threshold(gold_aspect, gold_sentiment, prob, sentiment)
    pred_aspect = predict_aspects(prob, threshold)

    confusion = miss_confusion(gold_aspect, pred_aspect)
    train_aspect, _ = label_arrays(load_split(data_dir, "train"))
    together = cooccurrence(train_aspect)
    pairs = [
        {"missed": ASPECTS[i], "predicted_instead": ASPECTS[j], "count": int(confusion[i, j]),
         "train_cooccurrence": int(together[i, j])}
        for i in range(len(ASPECTS)) for j in range(len(ASPECTS)) if i != j and confusion[i, j] > 0
    ]
    pairs.sort(key=lambda x: -x["count"])

    counts = pair_counts(gold_aspect, gold_sentiment, pred_aspect, sentiment).sum(axis=0)
    multi = gold_aspect.sum(axis=1) > 1
    by_length = {}
    per_sentence = pair_counts(gold_aspect, gold_sentiment, pred_aspect, sentiment).sum(axis=1)
    for name, mask in (("single_aspect", ~multi), ("multi_aspect", multi)):
        tp, fp, fn = per_sentence[mask].sum(axis=0)
        by_length[name] = {"sentences": int(mask.sum()), "pair_f1": float(2 * tp / max(2 * tp + fp + fn, 1))}

    return {
        "split": "validation",
        "threshold": threshold,
        "per_aspect": aspect_errors(gold_aspect, gold_sentiment, pred_aspect, sentiment),
        "per_aspect_pair_f1": {
            name: float(2 * counts[a, 0] / max(2 * counts[a, 0] + counts[a, 1] + counts[a, 2], 1))
            for a, name in enumerate(ASPECTS)
        },
        "by_number_of_aspects": by_length,
        "confused_pairs": pairs,
        "confusion_matrix": confusion.tolist(),
        "train_support": dict(zip(ASPECTS, np.diag(together).tolist())),
        "ignore_index": IGNORE_INDEX,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--data-dir", default="data/Final_Data")
    args = parser.parse_args()
    report = diagnose(args.run_dir, args.data_dir)
    (args.run_dir / "diagnosis_validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("threshold", "by_number_of_aspects")}, indent=2))
    for name, row in report["per_aspect"].items():
        print(f"{name:<20} train={report['train_support'][name]:>5} pair_f1={report['per_aspect_pair_f1'][name]:.3f} {row}")
    for pair in report["confused_pairs"][:15]:
        print(pair)
