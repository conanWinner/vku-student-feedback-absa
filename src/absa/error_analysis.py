"""Error analysis on test for the paper. Only run after the configuration is locked.

    python -m absa.error_analysis results/runs --data-dir data/Final_Data

Writes `results/error_analysis_test.json`. The groups and models are fixed by
docs/04-experiment-protocol.md and docs/11-g3b-lock.md, and nothing here selects a model.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import numpy as np

from .data import ASPECTS, IGNORE_INDEX, POLARITIES, label_arrays, load_split
from .diagnose import aspect_errors
from .evaluate import _load, _thresholds
from .metrics import pair_counts, predict_aspects
from .summarize import group_runs

MODELS = ("e1_bilstm-cnn", "e2_phobert", "e5_phobert")
CONTRAST = re.compile(r"\b(nhưng|tuy nhiên)\b", re.IGNORECASE)
EXAMPLES_PER_SIDE = 4


def f1(counts: np.ndarray) -> float:
    tp, fp, fn = counts.sum(axis=0)
    return float(2 * tp / max(2 * tp + fp + fn, 1))


def sentence_groups(texts: list[str], gold_aspect: np.ndarray, gold_sentiment: np.ndarray) -> dict[str, np.ndarray]:
    present = gold_aspect.astype(bool)
    multi = present.sum(axis=1) > 1
    polarities = [set(row[mask].tolist()) for row, mask in zip(gold_sentiment, present)]
    return {
        "all": np.ones(len(texts), dtype=bool),
        "single_aspect": ~multi,
        "multi_aspect": multi,
        "conflicting_polarity": np.array([len(p) > 1 for p in polarities]),
        "contrast_word": np.array([bool(CONTRAST.search(t)) for t in texts]),
    }


def polarity_scores(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment) -> dict:
    """Over gold pairs of each polarity: pair recall, and sentiment accuracy when aspects are given."""
    gold = gold_aspect.astype(bool)
    scores = {}
    for index, name in enumerate(POLARITIES):
        mask = gold & (gold_sentiment == index)
        right = pred_sentiment == index
        scores[name] = {
            "pairs": int(mask.sum()),
            "pair_recall": float((mask & pred_aspect.astype(bool) & right).sum() / max(mask.sum(), 1)),
            "sentiment_acc_on_gold": float((mask & right).sum() / max(mask.sum(), 1)),
        }
    return scores


def _run_outputs(run: Path, data_dir: str) -> tuple[np.ndarray, np.ndarray, dict]:
    result, predictions, data_dir = _load(run, data_dir)
    _, threshold, _ = _thresholds(result, predictions, data_dir)
    samples = load_split(data_dir, "test")
    if [s.uid for s in samples] != predictions["test_uid"].tolist():
        raise ValueError(f"{run}: predictions do not match the test sentences")
    return predict_aspects(predictions["test_aspect_prob"], threshold), predictions["test_sentiment"].astype(np.int64), {"threshold": threshold}


def _labels(aspect_row: np.ndarray, sentiment_row: np.ndarray) -> list[str]:
    return [f"{ASPECTS[a]}:{POLARITIES[sentiment_row[a]]}" for a in np.flatnonzero(aspect_row)]


def analyze(runs_dir: str | Path, data_dir: str) -> dict:
    groups_of_runs = group_runs(runs_dir)
    samples = load_split(data_dir, "test")
    texts = [s.text for s in samples]
    gold_aspect, gold_sentiment = label_arrays(samples)
    groups = sentence_groups(texts, gold_aspect, gold_sentiment)
    train_support = label_arrays(load_split(data_dir, "train"))[0].sum(axis=0).astype(int).tolist()

    report = {"split": "test", "group_sizes": {k: int(v.sum()) for k, v in groups.items()}, "train_support": dict(zip(ASPECTS, train_support)), "models": {}}
    all_correct = {}
    outputs = {}
    for model in MODELS:
        by_group, by_polarity, by_aspect, correct = [], [], [], []
        outputs[model] = []
        for run in groups_of_runs[model]:
            pred_aspect, pred_sentiment, _ = _run_outputs(run, data_dir)
            outputs[model].append((pred_aspect, pred_sentiment))
            counts = pair_counts(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment)
            by_group.append({name: f1(counts[mask].sum(axis=1)) for name, mask in groups.items()})
            by_polarity.append(polarity_scores(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment))
            by_aspect.append(aspect_errors(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment))
            correct.append(counts[:, :, 1:].sum(axis=(1, 2)) == 0)
        all_correct[model] = np.stack(correct)
        report["models"][model] = {
            "group_pair_f1": {g: float(np.mean([row[g] for row in by_group])) for g in groups},
            "polarity": {
                p: {k: float(np.mean([row[p][k] for row in by_polarity])) for k in by_polarity[0][p]} for p in POLARITIES
            },
            "aspect_errors_mean": {
                a: {k: float(np.mean([row[a][k] for row in by_aspect])) for k in by_aspect[0][a]} for a in ASPECTS
            },
        }

    # Sentences on which every seed of one model is fully right and every seed of the other is not.
    e2_right, e5_right = all_correct["e2_phobert"].all(axis=0), all_correct["e5_phobert"].all(axis=0)
    e2_wrong, e5_wrong = (~all_correct["e2_phobert"]).all(axis=0), (~all_correct["e5_phobert"]).all(axis=0)
    sides = {"e5_right_e2_wrong": e5_right & e2_wrong, "e2_right_e5_wrong": e2_right & e5_wrong}
    report["disagreement_counts"] = {k: int(v.sum()) for k, v in sides.items()}
    report["examples"] = {}
    for side, mask in sides.items():
        chosen = sorted(random.Random(0).sample(np.flatnonzero(mask).tolist(), min(EXAMPLES_PER_SIDE, int(mask.sum()))))
        wrong_model = "e2_phobert" if side == "e5_right_e2_wrong" else "e5_phobert"
        report["examples"][side] = [
            {
                "uid": samples[i].uid,
                "text": texts[i],
                "gold": _labels(gold_aspect[i], np.where(gold_sentiment[i] == IGNORE_INDEX, 0, gold_sentiment[i])),
                f"{wrong_model}_seed42": _labels(outputs[wrong_model][0][0][i], outputs[wrong_model][0][1][i]),
            }
            for i in chosen
        ]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs_dir")
    parser.add_argument("--data-dir", default="data/Final_Data")
    args = parser.parse_args()
    report = analyze(args.runs_dir, args.data_dir)
    output = Path(args.runs_dir).parent / "error_analysis_test.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))
