"""Score a finished run. Thresholds always come from validation.

    python -m absa.evaluate results/runs/e4_phobert-base_seed42
    python -m absa.evaluate results/runs/e4_phobert-base_seed42 --test   # only after locking

Compare two models across seeds (requires --test scoring to be allowed):

    python -m absa.evaluate --compare results/runs/e4_*_seed4? --against results/runs/e2_*_seed4?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .data import label_arrays, load_split
from .metrics import evaluate, pair_counts, paired_bootstrap, predict_aspects, select_global_threshold, select_per_aspect_thresholds


def _labels(data_dir, split, uids, limit):
    samples = load_split(data_dir, split)
    if limit:
        samples = samples[:limit]
    if [s.uid for s in samples] != uids.tolist():
        raise ValueError(f"{split}: predictions do not match the sentences in {data_dir}")
    return label_arrays(samples)


def _load(run_dir: Path, data_dir: str | None):
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    return result, np.load(run_dir / "predictions.npz"), data_dir or result["config"]["data_dir"]


def _thresholds(result, predictions, data_dir):
    limit = result["config"]["limit"]
    gold = _labels(data_dir, "validation", predictions["validation_uid"], limit)
    prob, sentiment = predictions["validation_aspect_prob"], predictions["validation_sentiment"]
    return gold, select_global_threshold(*gold, prob, sentiment), select_per_aspect_thresholds(*gold, prob, sentiment)


def evaluate_run(run_dir: str | Path, data_dir: str | None = None, with_test: bool = False) -> dict:
    run_dir = Path(run_dir)
    result, predictions, data_dir = _load(run_dir, data_dir)
    gold, global_t, per_aspect_t = _thresholds(result, predictions, data_dir)
    decoders = {"fixed_0.5": 0.5, "global": global_t, "per_aspect": per_aspect_t}
    prob, sentiment = predictions["validation_aspect_prob"], predictions["validation_sentiment"]

    report = {
        "run_name": result["run_name"],
        "thresholds": {"global": global_t, "per_aspect": per_aspect_t.tolist()},
        "validation": {name: evaluate(*gold, prob, sentiment, t) for name, t in decoders.items()},
    }
    if with_test:
        test_gold = _labels(data_dir, "test", predictions["test_uid"], result["config"]["limit"])
        report["test"] = {
            name: evaluate(*test_gold, predictions["test_aspect_prob"], predictions["test_sentiment"], t)
            for name, t in decoders.items()
        }
    name = "evaluation_test.json" if with_test else "evaluation_validation.json"
    (run_dir / name).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _sentence_counts(run_dir: Path, data_dir: str | None) -> np.ndarray:
    """Per-sentence test TP, FP, FN at the run's validation-selected global threshold."""
    result, predictions, data_dir = _load(run_dir, data_dir)
    _, global_t, _ = _thresholds(result, predictions, data_dir)
    test_gold = _labels(data_dir, "test", predictions["test_uid"], result["config"]["limit"])
    pred_aspect = predict_aspects(predictions["test_aspect_prob"], global_t)
    return pair_counts(*test_gold, pred_aspect, predictions["test_sentiment"]).sum(axis=1)


def compare(runs_a: list[str], runs_b: list[str], data_dir: str | None = None, n_boot: int = 1000) -> dict:
    """Paired bootstrap of test `pair_f1_micro`. Both models must have run the same seeds."""
    a, b = sorted(map(Path, runs_a)), sorted(map(Path, runs_b))
    seeds_a = [json.loads((r / "result.json").read_text(encoding="utf-8"))["config"]["seed"] for r in a]
    seeds_b = [json.loads((r / "result.json").read_text(encoding="utf-8"))["config"]["seed"] for r in b]
    if seeds_a != seeds_b:
        raise ValueError(f"models must use the same seeds: {seeds_a} vs {seeds_b}")
    counts_a = np.stack([_sentence_counts(r, data_dir) for r in a])
    counts_b = np.stack([_sentence_counts(r, data_dir) for r in b])
    return {"seeds": seeds_a, **paired_bootstrap(counts_a, counts_b, n_boot=n_boot)}


def _print_summary(report: dict) -> None:
    for split in ("validation", "test"):
        for name, metrics in report.get(split, {}).items():
            print(
                f"{split:<10} {name:<10} aspect_f1={metrics['aspect_f1_micro']:.4f} "
                f"pair_f1={metrics['pair_f1_micro']:.4f} pair_macro={metrics['pair_f1_macro']:.4f} "
                f"sent_acc_gold={metrics['sentiment_acc_on_gold']:.4f}"
            )
    print("global threshold:", report["thresholds"]["global"])


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--test", action="store_true", help="score the test set; only after the configuration is locked")
    parser.add_argument("--compare", nargs="+", help="run directories of model A")
    parser.add_argument("--against", nargs="+", help="run directories of model B")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    if args.compare:
        print(json.dumps(compare(args.compare, args.against, args.data_dir), indent=2))
    else:
        _print_summary(evaluate_run(args.run_dir, args.data_dir, args.test))


if __name__ == "__main__":
    main()
