"""Aggregate runs into the protocol's tables and comparisons. Validation unless told otherwise.

    python -m absa.summarize results/runs --data-dir data/Final_Data
    python -m absa.summarize results/runs --data-dir data/Final_Data --split test   # only after locking

Run folders are named `<model>_seed<seed>`. Writes `results/summary_<split>.json` and prints
Markdown tables.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from .evaluate import compare, evaluate_run

DECODERS = ("global", "per_aspect", "fixed_0.5")
BASELINES = ("e0_tfidf-svm", "e1_bilstm-cnn")
BEST_BASELINE = "best_baseline"
# Main comparisons of docs/04-experiment-protocol.md, as (A, B): the difference is A - B.
COMPARISONS = (
    ("e3_phobert", "e2_phobert"),
    ("e5_phobert", "e3_phobert"),
    ("e4_phobert", "e5_phobert"),
    ("e4_phobert", "e2_phobert"),
    ("e4_phobert", BEST_BASELINE),
    ("e4_bamibert", "e2_bamibert"),
)
# Added at gate G3b, before test was scored, because the main model became E5 (docs/11-g3b-lock.md).
ADDED_AT_LOCK = (
    ("e5_phobert", "e2_phobert"),
    ("e5_phobert", BEST_BASELINE),
)
PRACTICAL_DIFFERENCE = 0.005  # 0.5 F1 points, fixed in the protocol


def interpret(diff: float, ci_low: float, ci_high: float) -> str:
    """The protocol's wording for one comparison of A - B."""
    if ci_low <= 0 <= ci_high:
        return "insufficient_evidence"
    if abs(diff) < PRACTICAL_DIFFERENCE:
        return "small_difference"
    return "improvement" if diff > 0 else "worse"


def group_runs(runs_dir: str | Path) -> dict[str, list[Path]]:
    """Model name -> its run folders, sorted by folder name."""
    groups = defaultdict(list)
    for path in sorted(Path(runs_dir).iterdir()):
        match = re.fullmatch(r"(.+)_seed\d+", path.name)
        if match and (path / "result.json").exists():
            groups[match.group(1)].append(path)
    return dict(groups)


def _check_same_dataset(groups: dict[str, list[Path]]) -> str:
    hashes = {json.loads((r / "result.json").read_text(encoding="utf-8"))["dataset_hash"] for runs in groups.values() for r in runs}
    if len(hashes) != 1:
        raise ValueError(f"runs come from different datasets: {sorted(hashes)}")
    return hashes.pop()


def _check_same_encoder_revision(groups: dict[str, list[Path]]) -> None:
    """Runs on one encoder must share its weights. Runs without an encoder record no `model_commit`."""
    commits = defaultdict(set)
    for runs in groups.values():
        for run in runs:
            result = json.loads((run / "result.json").read_text(encoding="utf-8"))
            if "model_commit" in result:
                commits[result["config"]["encoder"]].add(result["model_commit"])
    for encoder, found in commits.items():
        if len(found) != 1 or None in found:
            raise ValueError(f"{encoder}: runs must record one revision, found {sorted(map(str, found))}")


def _mean_std(values: list[float]) -> dict:
    return {"mean": float(np.mean(values)), "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0, "n": len(values)}


def model_table(reports: list[dict], split: str) -> dict:
    """Mean and sample std over seeds, for each decoder and metric."""
    table = {}
    for decoder in DECODERS:
        rows = [report[split][decoder] for report in reports]
        table[decoder] = {
            metric: _mean_std([row[metric] for row in rows])
            for metric in ("aspect_f1_micro", "pair_f1_micro", "pair_f1_macro", "sentiment_acc_on_gold")
        }
        table[decoder]["per_aspect_pair_f1"] = {
            name: _mean_std([row["per_aspect"][name]["pair_f1"] for row in rows]) for name in rows[0]["per_aspect"]
        }
    return table


def summarize(runs_dir: str | Path, data_dir: str | None = None, split: str = "validation", n_boot: int = 1000) -> dict:
    groups = group_runs(runs_dir)
    dataset = _check_same_dataset(groups)
    _check_same_encoder_revision(groups)
    models = {
        name: model_table([evaluate_run(r, data_dir, with_test=split == "test") for r in runs], split)
        for name, runs in groups.items()
    }
    available = [b for b in BASELINES if b in models]
    # The best baseline is always the one on validation, whichever split is being reported.
    if split == "validation":
        best = max(available, key=lambda b: models[b]["global"]["pair_f1_micro"]["mean"], default=None)
    else:
        scores = {b: np.mean([evaluate_run(r, data_dir)["validation"]["global"]["pair_f1_micro"] for r in groups[b]]) for b in available}
        best = max(scores, key=scores.get, default=None)

    comparisons = []
    roles = [(pair, "main") for pair in COMPARISONS] + [(pair, "added_at_lock") for pair in ADDED_AT_LOCK]
    for (a, b), role in roles:
        b = best if b == BEST_BASELINE else b
        if a not in groups or b not in groups:
            comparisons.append({"a": a, "b": b, "role": role, "status": "missing_runs"})
            continue
        result = compare(groups[a], groups[b], data_dir, n_boot=n_boot, split=split)
        comparisons.append({"a": a, "b": b, "role": role, **result, "verdict": interpret(result["diff"], result["ci_low"], result["ci_high"])})
    return {"split": split, "dataset_hash": dataset, "best_baseline": best, "models": models, "comparisons": comparisons}


def to_markdown(summary: dict) -> str:
    def cell(stat):
        return f"{100 * stat['mean']:.2f} ± {100 * stat['std']:.2f}"

    lines = [f"Split: {summary['split']}. Dataset: {summary['dataset_hash'][:8]}. Best baseline: {summary['best_baseline']}.", "",
             "| Model | Seeds | Task A | Task B | Task B, per-aspect thresholds | Task B, threshold 0.5 |", "|---|---|---|---|---|---|"]
    for name, table in sorted(summary["models"].items()):
        main = table["global"]
        lines.append(
            f"| {name} | {main['pair_f1_micro']['n']} | {cell(main['aspect_f1_micro'])} | {cell(main['pair_f1_micro'])} "
            f"| {cell(table['per_aspect']['pair_f1_micro'])} | {cell(table['fixed_0.5']['pair_f1_micro'])} |"
        )
    lines += ["", "| A - B | Role | Difference | 95% CI | Verdict |", "|---|---|---|---|---|"]
    for row in summary["comparisons"]:
        if "verdict" in row:
            lines.append(f"| {row['a']} - {row['b']} | {row['role']} | {100 * row['diff']:+.2f} | [{100 * row['ci_low']:+.2f}, {100 * row['ci_high']:+.2f}] | {row['verdict']} |")
        else:
            lines.append(f"| {row['a']} - {row['b']} | {row['role']} | | | {row['status']} |")
    return "\n".join(lines)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs_dir")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    summary = summarize(args.runs_dir, args.data_dir, args.split, args.n_boot)
    output = Path(args.output or Path(args.runs_dir).parent / f"summary_{args.split}.json")
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(to_markdown(summary))
    print(f"\nsaved {output}")


if __name__ == "__main__":
    main()
