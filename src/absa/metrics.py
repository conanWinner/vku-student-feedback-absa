"""Evaluation metrics, threshold selection, and paired bootstrap (docs/04-experiment-protocol.md).

Task A is aspect detection. Task B counts a prediction as correct only if both the
aspect and its sentiment are right, so a wrong sentiment on a correctly detected
aspect is one false positive and one false negative.
"""

from __future__ import annotations

import numpy as np

from .data import ASPECTS, IGNORE_INDEX, NUM_POLARITIES

# Rounded so that values compare and serialize cleanly.
THRESHOLD_GRID = tuple(round(0.20 + 0.05 * i, 2) for i in range(11))  # 0.20 .. 0.70


def _prf(tp, fp, fn) -> tuple[float, float, float]:
    """Precision, recall and F1 as fractions. An empty denominator gives 0."""
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def predict_aspects(aspect_prob: np.ndarray, threshold) -> np.ndarray:
    """Binary aspect predictions. `threshold` is one value or one value per aspect."""
    return aspect_prob > np.asarray(threshold)


def pair_counts(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment) -> np.ndarray:
    """Task B TP, FP, FN per sentence and aspect, shape (N, A, 3)."""
    gold = gold_aspect.astype(bool)
    pred = pred_aspect.astype(bool)
    correct = gold & pred & (gold_sentiment == pred_sentiment)
    return np.stack([correct, pred & ~correct, gold & ~correct], axis=-1).astype(np.int64)


def aspect_counts(gold_aspect, pred_aspect) -> np.ndarray:
    """Task A TP, FP, FN per sentence and aspect, shape (N, A, 3)."""
    gold = gold_aspect.astype(bool)
    pred = pred_aspect.astype(bool)
    return np.stack([gold & pred, pred & ~gold, gold & ~pred], axis=-1).astype(np.int64)


def _summarize(counts: np.ndarray, prefix: str) -> tuple[dict, list[tuple[float, float, float]]]:
    per_aspect = [_prf(*counts[:, a].sum(axis=0)) for a in range(counts.shape[1])]
    p, r, f1 = _prf(*counts.sum(axis=(0, 1)))
    summary = {
        f"{prefix}_p_micro": p,
        f"{prefix}_r_micro": r,
        f"{prefix}_f1_micro": f1,
        f"{prefix}_f1_macro": float(np.mean([x[2] for x in per_aspect])),
    }
    return summary, per_aspect


def evaluate(gold_aspect, gold_sentiment, aspect_prob, pred_sentiment, threshold=0.5) -> dict:
    """All protocol metrics for one model at one threshold (scalar or per aspect).

    Args:
        gold_aspect: (N, A) multi-hot gold aspects.
        gold_sentiment: (N, A) gold polarity ids, IGNORE_INDEX where absent.
        aspect_prob: (N, A) predicted aspect probabilities.
        pred_sentiment: (N, A) argmax polarity id for every aspect.
    """
    pred_aspect = predict_aspects(aspect_prob, threshold)
    aspect_summary, aspect_per = _summarize(aspect_counts(gold_aspect, pred_aspect), "aspect")
    pair_summary, pair_per = _summarize(
        pair_counts(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment), "pair"
    )

    # Sentiment alone, on the aspects that truly exist. Independent of detection errors.
    present = gold_sentiment != IGNORE_INDEX
    gold_s, pred_s = gold_sentiment[present], pred_sentiment[present]
    class_f1 = [
        _prf(((gold_s == c) & (pred_s == c)).sum(), ((gold_s != c) & (pred_s == c)).sum(),
             ((gold_s == c) & (pred_s != c)).sum())[2]
        for c in range(NUM_POLARITIES)
    ]
    support = gold_aspect.astype(bool).sum(axis=0)
    return {
        **aspect_summary,
        **pair_summary,
        "sentiment_acc_on_gold": float((gold_s == pred_s).mean()) if gold_s.size else 0.0,
        "sentiment_f1_macro_on_gold": float(np.mean(class_f1)),
        "per_aspect": {
            name: {
                "support": int(support[a]),
                "aspect_p": aspect_per[a][0],
                "aspect_r": aspect_per[a][1],
                "aspect_f1": aspect_per[a][2],
                "pair_p": pair_per[a][0],
                "pair_r": pair_per[a][1],
                "pair_f1": pair_per[a][2],
            }
            for a, name in enumerate(ASPECTS)
        },
    }


def select_global_threshold(gold_aspect, gold_sentiment, aspect_prob, pred_sentiment) -> float:
    """Grid value with the best `pair_f1_micro`; ties go to the lowest. Call on validation only."""
    scores = [
        _prf(*pair_counts(gold_aspect, gold_sentiment, predict_aspects(aspect_prob, t), pred_sentiment).sum(axis=(0, 1)))[2]
        for t in THRESHOLD_GRID
    ]
    return THRESHOLD_GRID[int(np.argmax(scores))]


def select_per_aspect_thresholds(gold_aspect, gold_sentiment, aspect_prob, pred_sentiment) -> np.ndarray:
    """Best grid value for each aspect's pair F1; ties go to the lowest. Call on validation only."""
    best = np.zeros(gold_aspect.shape[1])
    for a in range(gold_aspect.shape[1]):
        scores = [
            _prf(*pair_counts(gold_aspect[:, [a]], gold_sentiment[:, [a]],
                              aspect_prob[:, [a]] > t, pred_sentiment[:, [a]]).sum(axis=(0, 1)))[2]
            for t in THRESHOLD_GRID
        ]
        best[a] = THRESHOLD_GRID[int(np.argmax(scores))]
    return best


def _micro_f1(tp: np.ndarray, fp: np.ndarray, fn: np.ndarray) -> np.ndarray:
    denominator = 2 * tp + fp + fn
    return np.divide(2 * tp, denominator, out=np.zeros_like(denominator, dtype=float), where=denominator > 0)


def paired_bootstrap(counts_a: np.ndarray, counts_b: np.ndarray, n_boot: int = 1000, seed: int = 0) -> dict:
    """95% CI of the micro-F1 difference A - B, averaged over seeds.

    Each resample draws the same sentence indices for both models and recomputes F1
    from counts. The interval is conditional on the seeds that were run.

    Args:
        counts_a: Per-sentence (TP, FP, FN) of model A, shape (seeds, N, 3).
        counts_b: The same for model B, with seeds in the same order.
    """
    if counts_a.shape != counts_b.shape:
        raise ValueError("both models must have the same seeds and sentences")

    def f1_gap(a: np.ndarray, b: np.ndarray) -> float:
        total_a, total_b = a.sum(axis=1), b.sum(axis=1)  # (seeds, 3)
        return float((_micro_f1(*total_a.T) - _micro_f1(*total_b.T)).mean())

    n = counts_a.shape[1]
    rng = np.random.default_rng(seed)
    gaps = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        gaps[i] = f1_gap(counts_a[:, idx], counts_b[:, idx])
    low, high = np.percentile(gaps, [2.5, 97.5])
    return {"diff": f1_gap(counts_a, counts_b), "ci_low": float(low), "ci_high": float(high), "n_boot": n_boot}
