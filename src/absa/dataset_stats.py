"""Dataset tables for the paper. Labels only: no model or prediction is involved.

    python -m absa.dataset_stats --data-dir data/Final_Data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .data import ASPECTS, POLARITIES, dataset_hash, label_arrays, load_split


def split_stats(samples) -> dict:
    aspect, sentiment = label_arrays(samples)
    present = aspect.astype(bool)
    per_sentence = present.sum(axis=1)
    lengths = [len(s.text.split()) for s in samples]
    return {
        "sentences": len(samples),
        "pairs": int(present.sum()),
        "pairs_per_sentence": float(present.sum() / len(samples)),
        "multi_aspect_sentences": int((per_sentence > 1).sum()),
        "mean_tokens": float(np.mean(lengths)),
        "polarity": {p: int((sentiment[present] == i).sum()) for i, p in enumerate(POLARITIES)},
        "per_aspect": {
            name: {p: int((sentiment[present[:, a], a] == i).sum()) for i, p in enumerate(POLARITIES)}
            for a, name in enumerate(ASPECTS)
        },
    }


def dataset_stats(data_dir: str | Path) -> dict:
    splits = {name: load_split(data_dir, name) for name in ("train", "validation", "test")}
    return {
        "dataset_hash": dataset_hash(data_dir),
        "splits": {name: split_stats(rows) for name, rows in splits.items()},
        "all": split_stats([s for rows in splits.values() for s in rows]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data/Final_Data")
    parser.add_argument("--output", default="results/dataset_stats.json")
    args = parser.parse_args()
    stats = dataset_stats(args.data_dir)
    Path(args.output).write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, row in {**stats["splits"], "all": stats["all"]}.items():
        print(f"{name:<10} sentences={row['sentences']} pairs={row['pairs']} per_sentence={row['pairs_per_sentence']:.3f} "
              f"multi={row['multi_aspect_sentences']} tokens={row['mean_tokens']:.1f} {row['polarity']}")
