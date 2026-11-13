import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from absa.data import ASPECT2ID, IGNORE_INDEX, POLARITY2ID, dataset_hash, label_arrays, load_file, load_split

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "Final_Data"


def write_csv(directory, name, rows):
    path = Path(directory) / name
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "text", "sentiment", "aspect"])
        writer.writerows(rows)
    return path


class LoadFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_groups_rows_of_one_sentence(self):
        path = write_csv(self.tmp.name, "train1.csv", [
            [1, "a", "positive", "hanh_vi"],
            [1, "a", "negative", "ky_nang_giang_day"],
            [2, "b", "neutral", "noi_chung"],
        ])
        first, second = load_file(path)
        self.assertEqual(first.uid, "train1:1")
        self.assertEqual(first.aspect.sum(), 2)
        self.assertEqual(first.sentiment[ASPECT2ID["hanh_vi"]], POLARITY2ID["positive"])
        self.assertEqual(first.sentiment[ASPECT2ID["ky_nang_giang_day"]], POLARITY2ID["negative"])
        self.assertEqual(first.sentiment[ASPECT2ID["noi_chung"]], IGNORE_INDEX)
        self.assertEqual(second.text, "b")

    def test_rejects_bad_rows(self):
        cases = {
            "unknown aspect": [[1, "a", "positive", "khong_co"]],
            "unknown sentiment": [[1, "a", "good", "hanh_vi"]],
            "different sentences": [[1, "a", "positive", "hanh_vi"], [1, "b", "positive", "noi_chung"]],
            "conflicting sentiment": [[1, "a", "positive", "hanh_vi"], [1, "a", "negative", "hanh_vi"]],
        }
        for name, rows in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                load_file(write_csv(self.tmp.name, "bad.csv", rows))


class SplitTest(unittest.TestCase):
    def test_same_id_in_two_train_files_stays_two_sentences(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(1, 7):
                write_csv(tmp, f"train{i}.csv", [[1, f"câu {i}", "positive", "hanh_vi"]])
            samples = load_split(tmp, "train")
        self.assertEqual(len(samples), 6)
        self.assertEqual(len({s.uid for s in samples}), 6)
        self.assertEqual(len({s.text for s in samples}), 6)


class RealDataTest(unittest.TestCase):
    """The sentence counts below are the official UIT-VSFC splits."""

    @classmethod
    def setUpClass(cls):
        cls.splits = {s: load_split(DATA_DIR, s) for s in ("train", "validation", "test")}

    def test_sentence_counts_match_uit_vsfc(self):
        counts = {name: len(samples) for name, samples in self.splits.items()}
        self.assertEqual(counts, {"train": 11426, "validation": 1583, "test": 3166})

    def test_no_sentence_crosses_splits(self):
        texts = {name: {s.text.strip() for s in samples} for name, samples in self.splits.items()}
        self.assertFalse(texts["train"] & texts["validation"])
        self.assertFalse(texts["train"] & texts["test"])
        self.assertFalse(texts["validation"] & texts["test"])

    def test_every_sentence_has_a_consistent_label(self):
        for samples in self.splits.values():
            aspect, sentiment = label_arrays(samples)
            self.assertTrue((aspect.sum(axis=1) >= 1).all())
            np.testing.assert_array_equal(aspect == 1, sentiment != IGNORE_INDEX)

    def test_hash_is_stable(self):
        self.assertEqual(dataset_hash(DATA_DIR), dataset_hash(DATA_DIR))


if __name__ == "__main__":
    unittest.main()
