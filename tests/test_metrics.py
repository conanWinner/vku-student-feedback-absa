import unittest

import numpy as np

from absa.data import ASPECT2ID, IGNORE_INDEX, NUM_ASPECTS
from absa.metrics import (
    aspect_counts,
    evaluate,
    pair_counts,
    paired_bootstrap,
    select_global_threshold,
    select_per_aspect_thresholds,
)

NEG, NEU, POS = 0, 1, 2
A, B = ASPECT2ID["hanh_vi"], ASPECT2ID["kien_thuc"]


def gold(*rows):
    """Each row is a dict {aspect index: polarity}."""
    aspect = np.zeros((len(rows), NUM_ASPECTS), dtype=np.float32)
    sentiment = np.full((len(rows), NUM_ASPECTS), IGNORE_INDEX, dtype=np.int64)
    for i, row in enumerate(rows):
        for a, polarity in row.items():
            aspect[i, a], sentiment[i, a] = 1, polarity
    return aspect, sentiment


def prediction(*rows):
    """Each row is a dict {aspect index: polarity}. Other aspects get a low probability."""
    prob = np.full((len(rows), NUM_ASPECTS), 0.1)
    sentiment = np.full((len(rows), NUM_ASPECTS), NEU, dtype=np.int64)
    for i, row in enumerate(rows):
        for a, polarity in row.items():
            prob[i, a], sentiment[i, a] = 0.9, polarity
    return prob, sentiment


def notebook_pair_counts(gold_aspect, gold_sentiment, pred_aspect, pred_sentiment):
    """The Task B loop from phobert_multitask.ipynb (cell 35), kept for comparison."""
    all_gold = np.zeros_like(gold_aspect, dtype=int)
    all_gold[gold_aspect == 1] = gold_sentiment[gold_aspect == 1] + 1
    all_pred = np.zeros_like(pred_aspect, dtype=int)
    all_pred[pred_aspect == 1] = pred_sentiment[pred_aspect == 1] + 1
    tp = fp = fn = 0
    for y, p in zip(all_gold.ravel(), all_pred.ravel()):
        tp += y != 0 and p == y
        fn += y != 0 and p != y
        fp += p != 0 and p != y
    return tp, fp, fn


class PairCountTest(unittest.TestCase):
    def test_wrong_sentiment_is_one_fp_and_one_fn(self):
        g_asp, g_sen = gold({A: POS})
        prob, sen = prediction({A: NEG})
        counts = pair_counts(g_asp, g_sen, prob > 0.5, sen).sum(axis=(0, 1))
        self.assertEqual(counts.tolist(), [0, 1, 1])
        # Task A still counts the aspect as found.
        self.assertEqual(aspect_counts(g_asp, prob > 0.5).sum(axis=(0, 1)).tolist(), [1, 0, 0])

    def test_extra_and_missing_aspects(self):
        g_asp, g_sen = gold({A: POS})
        prob, sen = prediction({B: POS})
        counts = pair_counts(g_asp, g_sen, prob > 0.5, sen).sum(axis=(0, 1))
        self.assertEqual(counts.tolist(), [0, 1, 1])

    def test_matches_notebook_loop_on_random_data(self):
        rng = np.random.default_rng(0)
        g_asp = (rng.random((200, NUM_ASPECTS)) < 0.2).astype(np.float32)
        g_sen = np.where(g_asp == 1, rng.integers(0, 3, g_asp.shape), IGNORE_INDEX)
        p_asp = (rng.random(g_asp.shape) < 0.2).astype(int)
        p_sen = rng.integers(0, 3, g_asp.shape)
        ours = pair_counts(g_asp, g_sen, p_asp, p_sen).sum(axis=(0, 1)).tolist()
        self.assertEqual(ours, list(notebook_pair_counts(g_asp, g_sen, p_asp, p_sen)))


class EvaluateTest(unittest.TestCase):
    def test_hand_computed_example(self):
        # Sentence 1: A correct, B detected with the wrong sentiment.
        # Sentence 2: B missed, A predicted wrongly.
        g_asp, g_sen = gold({A: POS, B: NEG}, {B: NEU})
        prob, sen = prediction({A: POS, B: POS}, {A: NEG})
        sen[1, B] = NEU  # the sentiment head is right about B even though detection missed it
        m = evaluate(g_asp, g_sen, prob, sen)

        # Task A: TP 2, FP 1, FN 1.
        self.assertAlmostEqual(m["aspect_p_micro"], 2 / 3)
        self.assertAlmostEqual(m["aspect_r_micro"], 2 / 3)
        self.assertAlmostEqual(m["aspect_f1_micro"], 2 / 3)
        # Task B: TP 1, FP 2, FN 2.
        self.assertAlmostEqual(m["pair_f1_micro"], 1 / 3)
        # Sentiment on gold aspects: A right, B wrong, B right.
        self.assertAlmostEqual(m["sentiment_acc_on_gold"], 2 / 3)
        self.assertEqual(m["per_aspect"]["kien_thuc"]["support"], 2)
        self.assertAlmostEqual(m["per_aspect"]["hanh_vi"]["pair_p"], 1 / 2)
        self.assertAlmostEqual(m["per_aspect"]["hanh_vi"]["pair_r"], 1.0)

    def test_perfect_prediction(self):
        g_asp, g_sen = gold({A: POS}, {B: NEG})
        prob, sen = prediction({A: POS}, {B: NEG})
        m = evaluate(g_asp, g_sen, prob, sen)
        self.assertEqual(m["aspect_f1_micro"], 1.0)
        self.assertEqual(m["pair_f1_micro"], 1.0)

    def test_nothing_predicted_gives_zero_not_error(self):
        g_asp, g_sen = gold({A: POS})
        prob, sen = prediction({})
        self.assertEqual(evaluate(g_asp, g_sen, prob, sen)["pair_f1_micro"], 0.0)

    def test_sentence_order_does_not_change_scores(self):
        rng = np.random.default_rng(1)
        g_asp = (rng.random((50, NUM_ASPECTS)) < 0.2).astype(np.float32)
        g_sen = np.where(g_asp == 1, rng.integers(0, 3, g_asp.shape), IGNORE_INDEX)
        prob, sen = rng.random(g_asp.shape), rng.integers(0, 3, g_asp.shape)
        order = rng.permutation(50)
        a = evaluate(g_asp, g_sen, prob, sen)
        b = evaluate(g_asp[order], g_sen[order], prob[order], sen[order])
        self.assertEqual(a["pair_f1_micro"], b["pair_f1_micro"])
        self.assertEqual(a["aspect_f1_macro"], b["aspect_f1_macro"])


class ThresholdTest(unittest.TestCase):
    def test_global_threshold_comes_from_the_grid_and_separates_classes(self):
        g_asp, g_sen = gold({A: POS}, {})
        prob = np.zeros((2, NUM_ASPECTS))
        prob[0, A], prob[1, A] = 0.8, 0.45  # only thresholds >= 0.45 avoid the false positive
        sen = np.full((2, NUM_ASPECTS), POS)
        self.assertEqual(select_global_threshold(g_asp, g_sen, prob, sen), 0.45)

    def test_per_aspect_thresholds_are_independent(self):
        g_asp, g_sen = gold({A: POS}, {B: POS}, {})
        prob = np.zeros((3, NUM_ASPECTS))
        prob[0, A], prob[2, A] = 0.8, 0.6
        prob[1, B], prob[2, B] = 0.8, 0.3
        sen = np.full((3, NUM_ASPECTS), POS)
        chosen = select_per_aspect_thresholds(g_asp, g_sen, prob, sen)
        self.assertEqual(chosen[A], 0.6)
        self.assertEqual(chosen[B], 0.3)
        # The array form is accepted by evaluate.
        self.assertEqual(evaluate(g_asp, g_sen, prob, sen, chosen)["pair_f1_micro"], 1.0)


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(2)
        self.counts = rng.integers(0, 3, (3, 400, 3))

    def test_identical_models_have_zero_difference(self):
        r = paired_bootstrap(self.counts, self.counts, n_boot=100)
        self.assertEqual((r["diff"], r["ci_low"], r["ci_high"]), (0.0, 0.0, 0.0))

    def test_clearly_better_model_excludes_zero(self):
        better = np.zeros_like(self.counts)
        better[..., 0] = self.counts.sum(axis=-1)  # everything becomes a true positive
        r = paired_bootstrap(better, self.counts, n_boot=100)
        self.assertGreater(r["ci_low"], 0)
        self.assertLessEqual(r["ci_low"], r["diff"])
        self.assertLessEqual(r["diff"], r["ci_high"])

    def test_same_seed_gives_same_interval(self):
        other = np.roll(self.counts, 1, axis=1)
        self.assertEqual(paired_bootstrap(other, self.counts, 50, 7), paired_bootstrap(other, self.counts, 50, 7))

    def test_rejects_mismatched_seeds(self):
        with self.assertRaises(ValueError):
            paired_bootstrap(self.counts, self.counts[:2])


if __name__ == "__main__":
    unittest.main()
