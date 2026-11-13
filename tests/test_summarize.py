import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from absa.data import ASPECTS, NUM_ASPECTS, SPLIT_FILES, dataset_hash, load_split
from absa.dataset_stats import split_stats
from absa.diagnose import diagnose
from absa.error_analysis import polarity_scores, sentence_groups
from absa.evaluate import compare, evaluate_run
from absa.summarize import group_runs, interpret, summarize


def write_split(path: Path, n: int, prefix: str) -> None:
    rows = ["id,text,sentiment,aspect"]
    for i in range(n):
        rows.append(f'{i},"{prefix} {i}",positive,{ASPECTS[i % 2]}')
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_run(root: Path, name: str, seed: int, data: Path, hit_rate: float, hash_=None, **fields) -> Path:
    """A run that finds the right aspect of a sentence with probability `hit_rate`."""
    run = root / f"{name}_seed{seed}"
    run.mkdir()
    arrays = {}
    rng = np.random.default_rng(seed)
    for split in ("validation", "test"):
        samples = load_split(data, split)
        prob = np.zeros((len(samples), NUM_ASPECTS), dtype=np.float32)
        for i, sample in enumerate(samples):
            prob[i, int(np.argmax(sample.aspect)) if rng.random() < hit_rate else 5] = 0.9
        arrays[f"{split}_uid"] = np.array([s.uid for s in samples])
        arrays[f"{split}_aspect_prob"] = prob
        arrays[f"{split}_sentiment"] = np.full((len(samples), NUM_ASPECTS), 2, dtype=np.int8)
    np.savez(run / "predictions.npz", **arrays)
    config = {"seed": seed, "data_dir": str(data), "limit": None, "encoder": "vinai/phobert-base"}
    result = {"run_name": run.name, "config": config, "dataset_hash": hash_ or dataset_hash(data), **fields}
    (run / "result.json").write_text(json.dumps(result))
    return run


class InterpretTest(unittest.TestCase):
    def test_follows_the_protocol_table(self):
        self.assertEqual(interpret(0.010, 0.002, 0.018), "improvement")
        self.assertEqual(interpret(0.003, 0.001, 0.005), "small_difference")
        self.assertEqual(interpret(0.010, -0.001, 0.020), "insufficient_evidence")
        self.assertEqual(interpret(-0.010, -0.018, -0.002), "worse")


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.data.mkdir()
        for name in SPLIT_FILES["train"]:
            write_split(self.data / name, 20, "train")
        write_split(self.data / "validation.csv", 200, "val")
        write_split(self.data / "test.csv", 200, "test")
        self.runs = root / "runs"
        self.runs.mkdir()
        for seed in (42, 43, 44):
            write_run(self.runs, "e4_phobert", seed, self.data, 0.95)
            write_run(self.runs, "e2_phobert", seed, self.data, 0.60)

    def tearDown(self):
        self.tmp.cleanup()

    def test_validation_summary_never_writes_test_scores(self):
        summary = summarize(self.runs, str(self.data), n_boot=50)
        self.assertEqual(summary["split"], "validation")
        self.assertEqual(summary["models"]["e4_phobert"]["global"]["pair_f1_micro"]["n"], 3)
        self.assertFalse(list(self.runs.rglob("evaluation_test.json")))
        row = next(c for c in summary["comparisons"] if c["a"] == "e4_phobert" and c["b"] == "e2_phobert")
        self.assertEqual(row["verdict"], "improvement")
        self.assertEqual(row["split"], "validation")

    def test_missing_models_are_reported_not_dropped(self):
        summary = summarize(self.runs, str(self.data), n_boot=10)
        row = next(c for c in summary["comparisons"] if c["a"] == "e5_phobert")
        self.assertEqual(row["status"], "missing_runs")

    def test_compare_defaults_to_validation_and_ignores_test_predictions(self):
        groups = group_runs(self.runs)
        for run in groups["e4_phobert"] + groups["e2_phobert"]:
            arrays = dict(np.load(run / "predictions.npz"))
            arrays["test_uid"] = arrays["test_uid"][:1]  # any read of test would now fail
            np.savez(run / "predictions.npz", **arrays)
        self.assertEqual(compare(groups["e4_phobert"], groups["e2_phobert"], str(self.data), n_boot=10)["split"], "validation")

    def test_runs_from_two_datasets_are_refused(self):
        write_run(self.runs, "e1_bilstm-cnn", 42, self.data, 0.5, hash_="other")
        with self.assertRaises(ValueError):
            summarize(self.runs, str(self.data), n_boot=10)

    def test_changed_labels_with_the_same_ids_are_refused(self):
        run = group_runs(self.runs)["e4_phobert"][0]
        path = self.data / "validation.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("positive", "negative"), encoding="utf-8")
        for score in (
            lambda: evaluate_run(run, str(self.data)),
            lambda: diagnose(run, str(self.data)),
            lambda: summarize(self.runs, str(self.data), n_boot=10),
            lambda: compare([run], [run], str(self.data), n_boot=10),
        ):
            with self.assertRaisesRegex(ValueError, "used dataset"):
                score()

    def test_two_revisions_of_one_encoder_are_refused(self):
        write_run(self.runs, "e5_phobert", 42, self.data, 0.5, model_commit="aaa")
        write_run(self.runs, "e3_phobert", 42, self.data, 0.5, model_commit="bbb")
        with self.assertRaisesRegex(ValueError, "one revision"):
            summarize(self.runs, str(self.data), n_boot=10)

    def test_seed_mismatch_is_refused(self):
        groups = group_runs(self.runs)
        with self.assertRaises(ValueError):
            compare(groups["e4_phobert"], groups["e2_phobert"][:2], str(self.data), n_boot=10)


class DatasetStatsTest(unittest.TestCase):
    def test_counts_pairs_and_polarities(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "test.csv").write_text(
                'id,text,sentiment,aspect\n1,"a b",positive,hanh_vi\n1,"a b",negative,bai_tap\n2,"c",neutral,noi_chung\n', encoding="utf-8"
            )
            stats = split_stats(load_split(tmp, "test"))
        self.assertEqual((stats["sentences"], stats["pairs"], stats["multi_aspect_sentences"]), (2, 3, 1))
        self.assertEqual(stats["polarity"], {"negative": 1, "neutral": 1, "positive": 1})
        self.assertEqual(stats["per_aspect"]["bai_tap"]["negative"], 1)


class ErrorAnalysisTest(unittest.TestCase):
    def test_groups_and_polarity_scores_on_a_small_example(self):
        gold_aspect = np.array([[1, 1], [1, 0], [0, 1]])
        gold_sentiment = np.array([[0, 2], [1, -100], [-100, 2]])
        groups = sentence_groups(["tốt nhưng khó", "ổn", "hay"], gold_aspect, gold_sentiment)
        self.assertEqual(groups["multi_aspect"].tolist(), [True, False, False])
        self.assertEqual(groups["conflicting_polarity"].tolist(), [True, False, False])
        self.assertEqual(groups["contrast_word"].tolist(), [True, False, False])
        pred_aspect = np.array([[1, 0], [1, 0], [0, 1]])
        pred_sentiment = np.array([[0, 2], [2, 0], [0, 2]])
        scores = polarity_scores(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment)
        self.assertEqual(scores["positive"]["pairs"], 2)
        self.assertEqual(scores["positive"]["pair_recall"], 0.5)  # the second aspect of sentence 1 is missed
        self.assertEqual(scores["positive"]["sentiment_acc_on_gold"], 1.0)
        self.assertEqual(scores["neutral"]["sentiment_acc_on_gold"], 0.0)


if __name__ == "__main__":
    unittest.main()
