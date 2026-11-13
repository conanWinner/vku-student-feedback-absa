import unittest

import numpy as np

from absa.data import ASPECT2ID, ASPECTS, IGNORE_INDEX, NUM_ASPECTS
from absa.diagnose import aspect_errors, cooccurrence, miss_confusion

A, B = ASPECT2ID["kien_thuc"], ASPECT2ID["kinh_nghiem"]


class DiagnoseTest(unittest.TestCase):
    def test_miss_confusion_counts_a_miss_with_a_spurious_prediction(self):
        gold, pred = np.zeros((2, NUM_ASPECTS)), np.zeros((2, NUM_ASPECTS))
        gold[0, A], pred[0, B] = 1, 1  # A missed, B predicted instead
        gold[1, A], pred[1, A] = 1, 1  # correct, adds nothing
        confusion = miss_confusion(gold, pred)
        self.assertEqual(confusion[A, B], 1)
        self.assertEqual(confusion.sum(), 1)

    def test_aspect_errors_separates_error_types(self):
        gold = np.zeros((3, NUM_ASPECTS))
        sent = np.full((3, NUM_ASPECTS), IGNORE_INDEX)
        pred = np.zeros((3, NUM_ASPECTS), dtype=bool)
        pred_sent = np.zeros((3, NUM_ASPECTS), dtype=int)
        gold[0, A], sent[0, A], pred[0, A], pred_sent[0, A] = 1, 2, True, 0  # wrong sentiment
        gold[1, A], sent[1, A] = 1, 2  # missed
        pred[2, A] = True  # false positive
        row = aspect_errors(gold, sent, pred, pred_sent)[ASPECTS[A]]
        self.assertEqual(row, {"support": 2, "false_positive": 1, "missed": 1, "wrong_sentiment": 1})

    def test_cooccurrence_diagonal_is_the_aspect_count(self):
        aspect = np.zeros((3, NUM_ASPECTS))
        aspect[0, [A, B]] = 1
        aspect[1, A] = 1
        together = cooccurrence(aspect)
        self.assertEqual(together[A, A], 2)
        self.assertEqual(together[A, B], 1)


if __name__ == "__main__":
    unittest.main()
