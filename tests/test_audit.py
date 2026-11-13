import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from absa.audit import agreement, cohen_kappa, draw_sample, read_sheet, score, write_sheets
from absa.data import ASPECTS, IGNORE_INDEX, NUM_ASPECTS, Sample, load_split

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "Final_Data"


def read_order(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r["item"] for r in csv.DictReader(f)]


class KappaTest(unittest.TestCase):
    def test_known_value(self):
        # Observed 0.75; chance 0.5 * 0.5 + 0.5 * 0.5 = 0.5.
        a = np.array([1, 1, 0, 0])
        b = np.array([1, 0, 0, 0])
        self.assertAlmostEqual(cohen_kappa(a, b), (0.75 - 0.5) / 0.5)

    def test_perfect_agreement_and_undefined_case(self):
        self.assertEqual(cohen_kappa(np.array([0, 1]), np.array([0, 1])), 1.0)
        self.assertIsNone(cohen_kappa(np.array([1, 1]), np.array([1, 1])))


class SampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_split = load_split(DATA_DIR, "test")

    def test_real_sample_meets_the_protocol(self):
        excluded = {"test:3161", "test:3162"}
        chosen, stratified = draw_sample(self.test_split, exclude=excluded)
        self.assertEqual(len(chosen), 300)
        self.assertEqual(len({s.uid for s in chosen}), 300)
        self.assertFalse({s.uid for s in chosen} & excluded)
        self.assertLessEqual(stratified, 300)
        counts = np.stack([s.aspect for s in chosen]).sum(axis=0)
        self.assertTrue((counts >= 30).all(), counts)

    def test_same_seed_gives_same_sample(self):
        a, _ = draw_sample(self.test_split, seed=1)
        b, _ = draw_sample(self.test_split, seed=1)
        self.assertEqual([s.uid for s in a], [s.uid for s in b])

    def test_sheets_never_contain_labels(self):
        chosen, stratified = draw_sample(self.test_split)
        with tempfile.TemporaryDirectory() as tmp:
            write_sheets(chosen, Path(tmp), stratified)
            for name in "AB":
                with (Path(tmp) / f"audit_annotator_{name}.csv").open(encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 300)
                self.assertNotIn("uid", rows[0])
                self.assertTrue(all(r[a] == "" for r in rows for a in ASPECTS))
            orders = [list(read_order(Path(tmp) / f"audit_annotator_{n}.csv")) for n in "AB"]
            self.assertNotEqual(orders[0], orders[1])
            self.assertEqual(sorted(orders[0]), sorted(orders[1]))


def sentence(uid, aspect_id, polarity):
    aspect = np.zeros(NUM_ASPECTS, dtype=np.float32)
    sentiment = np.full(NUM_ASPECTS, IGNORE_INDEX, dtype=np.int64)
    aspect[aspect_id], sentiment[aspect_id] = 1, polarity
    return Sample(uid, f"câu {uid}", aspect, sentiment)


class ScoreTest(unittest.TestCase):
    def fill(self, path, value_for_item):
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            for r in rows:
                r["hanh_vi"] = value_for_item(r["item"])
                writer.writerow(r)

    def test_end_to_end_scoring(self):
        samples = [sentence(f"test:{i}", 1, 2) for i in range(4)]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_sheets(samples, out, stratified=4)
            self.fill(out / "audit_annotator_A.csv", lambda _: "pos")
            self.fill(out / "audit_annotator_B.csv", lambda item: "neg" if item == "Q001" else "pos")
            report = score(out)
        self.assertEqual(report["annotator_A_vs_dataset"]["exact_match_sentence"], 1.0)
        self.assertEqual(report["annotator_A_vs_B"]["exact_match_sentence"], 0.75)
        self.assertEqual(report["annotator_A_vs_B"]["n_shared_pairs"], 4)

    def test_bad_cells_and_unfinished_rows_are_rejected(self):
        samples = [sentence("test:1", 1, 2)]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_sheets(samples, out, stratified=1)
            sheet = out / "audit_annotator_A.csv"
            with self.assertRaises(ValueError):
                read_sheet(sheet)  # still empty
            self.fill(sheet, lambda _: "tot")
            with self.assertRaises(ValueError):
                read_sheet(sheet)

    def test_agreement_counts_only_shared_aspects_for_sentiment(self):
        a = np.full((2, NUM_ASPECTS), IGNORE_INDEX)
        b = a.copy()
        a[0, 0], b[0, 0] = 2, 2
        a[1, 1], b[1, 2] = 0, 0
        r = agreement(a, b)
        self.assertEqual(r["n_shared_pairs"], 1)
        self.assertEqual(r["exact_match_sentence"], 0.5)


if __name__ == "__main__":
    unittest.main()
