"""TF-IDF + Linear SVM baseline (E0). Runs on CPU and writes the same files as `absa.train`.

    python -m absa.baseline_tfidf --seed 42
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC

from .data import IGNORE_INDEX, NUM_ASPECTS, dataset_hash, label_arrays, load_split
from .preprocess import normalize
from .train import code_version


def fit_predict(train_texts, train_aspect, train_sentiment, eval_texts: dict, seed: int) -> dict:
    """Train one detector and one sentiment classifier per aspect; predict each split in `eval_texts`.

    The sentiment classifier for an aspect sees only sentences where that aspect exists.
    Decision scores go through a sigmoid so the shared threshold grid applies.
    """
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True, min_df=2)
    x_train = vectorizer.fit_transform(train_texts)
    x_eval = {split: vectorizer.transform(texts) for split, texts in eval_texts.items()}
    probs = {split: np.zeros((x.shape[0], NUM_ASPECTS), dtype=np.float32) for split, x in x_eval.items()}
    sentiments = {split: np.zeros((x.shape[0], NUM_ASPECTS), dtype=np.int8) for split, x in x_eval.items()}

    for a in range(NUM_ASPECTS):
        detector = LinearSVC(C=1.0, class_weight="balanced", random_state=seed)
        detector.fit(x_train, train_aspect[:, a].astype(int))
        present = train_sentiment[:, a] != IGNORE_INDEX
        labels = train_sentiment[present, a]
        classifier = None
        if len(set(labels.tolist())) > 1:
            classifier = LinearSVC(C=1.0, class_weight="balanced", random_state=seed).fit(x_train[present], labels)
        for split, x in x_eval.items():
            probs[split][:, a] = 1.0 / (1.0 + np.exp(-detector.decision_function(x)))
            sentiments[split][:, a] = classifier.predict(x) if classifier else (labels[0] if labels.size else 0)
    return {"probs": probs, "sentiments": sentiments}


def run(args) -> Path:
    started = time.time()
    samples = {split: load_split(args.data_dir, split) for split in ("train", "validation", "test")}
    texts = {split: [normalize(s.text) for s in rows] for split, rows in samples.items()}
    aspect, sentiment = label_arrays(samples["train"])
    output = fit_predict(texts["train"], aspect, sentiment, {k: texts[k] for k in ("validation", "test")}, args.seed)

    run_name = f"e0_tfidf-svm_seed{args.seed}"
    out_dir = Path(args.output_dir) / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_dir / "predictions.npz",
        validation_uid=np.array([s.uid for s in samples["validation"]]),
        validation_aspect_prob=output["probs"]["validation"],
        validation_sentiment=output["sentiments"]["validation"],
        test_uid=np.array([s.uid for s in samples["test"]]),
        test_aspect_prob=output["probs"]["test"],
        test_sentiment=output["sentiments"]["test"],
    )
    result = {
        "run_name": run_name,
        "config": {
            "model": "e0", "seed": args.seed, "data_dir": args.data_dir, "limit": None,
            "ngram_range": [1, 2], "min_df": 2, "C": 1.0, "class_weight": "balanced", "preprocess": "normalize+lower",
        },
        "code_commit": code_version(),
        "dataset_hash": dataset_hash(args.data_dir),
        "num_sentences": {split: len(rows) for split, rows in samples.items()},
        "train_seconds": time.time() - started,
        "versions": {"python": platform.python_version()},
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {out_dir}")
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", default="data/Final_Data")
    parser.add_argument("--output-dir", default="results/runs")
    run(parser.parse_args())
