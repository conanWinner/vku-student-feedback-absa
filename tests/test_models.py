import unittest

import numpy as np
import torch
from transformers import BertConfig, BertModel

from absa.aspects import ASPECT_DESCRIPTIONS, aspect_texts
from absa.data import ASPECTS, IGNORE_INDEX, NUM_ASPECTS, NUM_POLARITIES, POLARITY2ID
from absa.models.bilstm_cnn import BiLSTMCNN, build_vocab, class_weights, to_class_labels
from absa.models.multitask import PRESETS, MultiTaskABSA, mean_pooling


def tiny_encoder():
    return BertModel(BertConfig(
        vocab_size=50, hidden_size=32, num_hidden_layers=1, num_attention_heads=2,
        intermediate_size=32, max_position_embeddings=32,
    ))


def build(name, **kwargs):
    torch.manual_seed(0)
    preset = PRESETS[name]
    return MultiTaskABSA(
        tiny_encoder(), NUM_ASPECTS, NUM_POLARITIES,
        pos_weight=torch.ones(NUM_ASPECTS), sentiment_class_weight=torch.tensor([1.0, 2.0, 1.0]),
        aspect_branch=preset["aspect_branch"], sentiment_branch=preset["sentiment_branch"], **kwargs,
    )


def batch():
    ids = torch.tensor([[1, 2, 3, 4], [5, 6, 0, 0]])
    mask = torch.tensor([[1, 1, 1, 1], [1, 1, 0, 0]])
    aspect = torch.zeros(2, NUM_ASPECTS)
    sentiment = torch.full((2, NUM_ASPECTS), IGNORE_INDEX)
    aspect[0, 1], sentiment[0, 1] = 1, POLARITY2ID["positive"]
    aspect[1, 3], sentiment[1, 3] = 1, POLARITY2ID["negative"]
    return ids, mask, aspect, sentiment


class MeanPoolingTest(unittest.TestCase):
    def test_ignores_padding(self):
        hidden = torch.tensor([[[1.0], [3.0], [100.0]]])
        self.assertEqual(mean_pooling(hidden, torch.tensor([[1, 1, 0]])).item(), 2.0)


class MultiTaskTest(unittest.TestCase):
    def test_every_preset_trains_and_has_the_expected_shape(self):
        for name in PRESETS:
            with self.subTest(name):
                model = build(name)
                loss, prob, sentiment = model(*batch())
                self.assertEqual(prob.shape, (2, NUM_ASPECTS))
                self.assertEqual(sentiment.shape, (2, NUM_ASPECTS, NUM_POLARITIES))
                self.assertTrue(((prob >= 0) & (prob <= 1)).all())
                loss.backward()
                self.assertGreater(next(model.encoder.parameters()).grad.abs().sum().item(), 0)

    def test_presets_change_exactly_the_intended_parts(self):
        names = {name: {n.split(".")[0] for n, _ in build(name).named_parameters()} - {"encoder"} for name in PRESETS}
        self.assertEqual(names["e2"], {"aspect_head", "sentiment_head"})
        self.assertEqual(names["e3"], {"aspect_head", "sentiment_head", "aspect_embedding", "cross_attention"})
        self.assertEqual(names["e5"], {"aspect_weight", "aspect_bias", "sentiment_head", "aspect_embedding", "cross_attention"})
        self.assertEqual(names["e5"], names["e4"])

    def test_aspect_loss_reaches_queries_only_when_detection_uses_them(self):
        ids, mask, aspect, _ = batch()
        no_sentiment = torch.full((2, NUM_ASPECTS), IGNORE_INDEX)
        no_sentiment[0, 1] = 0  # the cross-entropy needs at least one target
        for name, reaches in (("e3", False), ("e5", True)):
            with self.subTest(name):
                model = build(name, beta=0.0)
                model(ids, mask, aspect, no_sentiment)[0].backward()
                grad = model.aspect_embedding.weight.grad
                self.assertEqual(grad is not None and grad.abs().sum().item() > 0, reaches)

    def test_absent_aspects_do_not_affect_sentiment_loss(self):
        ids, mask, aspect, sentiment = batch()
        model = build("e3").eval()
        hook_input = {}
        model.sentiment_head.register_forward_hook(lambda _m, _i, out: hook_input.update(out=out))
        with torch.no_grad():
            model(ids, mask, aspect, sentiment)
            logits = hook_input["out"]
            target = sentiment.reshape(-1)
            kept = target != IGNORE_INDEX
            expected = torch.nn.functional.cross_entropy(
                logits.reshape(-1, NUM_POLARITIES)[kept], target[kept], weight=model.sentiment_class_weight
            )
            actual = torch.nn.functional.cross_entropy(
                logits.reshape(-1, NUM_POLARITIES), target, weight=model.sentiment_class_weight, ignore_index=IGNORE_INDEX
            )
        self.assertAlmostEqual(expected.item(), actual.item(), places=5)

    def test_padding_does_not_change_predictions(self):
        for name in PRESETS:
            with self.subTest(name):
                model = build(name).eval()
                short_ids, short_mask = torch.tensor([[1, 2, 3]]), torch.tensor([[1, 1, 1]])
                long_ids, long_mask = torch.tensor([[1, 2, 3, 0, 0]]), torch.tensor([[1, 1, 1, 0, 0]])
                with torch.no_grad():
                    a = model(short_ids, short_mask)
                    b = model(long_ids, long_mask)
                self.assertTrue(torch.allclose(a[1], b[1], atol=1e-4))
                self.assertTrue(torch.allclose(a[2], b[2], atol=1e-4))

    def test_set_queries_copies_values_and_stays_trainable(self):
        model = build("e4")
        queries = torch.arange(NUM_ASPECTS * 32, dtype=torch.float).view(NUM_ASPECTS, 32)
        model.set_queries(queries)
        self.assertTrue(torch.equal(model.aspect_embedding.weight.data, queries))
        self.assertTrue(model.aspect_embedding.weight.requires_grad)

    def test_invalid_branch_combination_is_rejected(self):
        with self.assertRaises(ValueError):
            MultiTaskABSA(tiny_encoder(), NUM_ASPECTS, NUM_POLARITIES, torch.ones(NUM_ASPECTS), torch.ones(3),
                          aspect_branch="query", sentiment_branch="mean")


class AspectDescriptionTest(unittest.TestCase):
    def test_one_description_per_aspect_in_order(self):
        self.assertEqual(set(ASPECT_DESCRIPTIONS), set(ASPECTS))
        self.assertEqual(aspect_texts()[0], ASPECT_DESCRIPTIONS[ASPECTS[0]])


class BiLSTMTest(unittest.TestCase):
    def test_label_mapping_matches_the_notebook(self):
        sentiment = torch.tensor([[IGNORE_INDEX, POLARITY2ID["positive"], POLARITY2ID["neutral"], POLARITY2ID["negative"]]])
        self.assertEqual(to_class_labels(sentiment).tolist(), [[0, 1, 2, 3]])

    def test_vocab_reserves_special_tokens(self):
        vocab = build_vocab([["a", "b"], ["a"]])
        self.assertEqual(vocab, {"<PAD>": 0, "<UNK>": 1, "a": 2, "b": 3})

    def test_class_weights_formula(self):
        sentiment = np.full((4, NUM_ASPECTS), IGNORE_INDEX)
        sentiment[0, 0] = POLARITY2ID["positive"]
        weights = class_weights(sentiment)
        self.assertAlmostEqual(weights[0, 1].item(), np.sqrt(4 / (4 * 1)))  # positive seen once
        self.assertAlmostEqual(weights[0, 0].item(), np.sqrt(4 / (4 * 3)))  # none seen three times
        self.assertEqual(weights[0, 2].item(), 1.0)  # neutral never seen

    def test_outputs_fit_the_shared_evaluation(self):
        torch.manual_seed(0)
        _, sentiment = batch()[2:]
        model = BiLSTMCNN(10, torch.ones(NUM_ASPECTS, 4), embedding_dim=8, hidden_size=4, num_filters=4, fc_hidden=4)
        ids = torch.randint(0, 10, (2, 12))
        loss, prob, logits = model(ids, sentiment_labels=sentiment)
        self.assertEqual(logits.shape, (2, NUM_ASPECTS, NUM_POLARITIES))
        self.assertTrue(set(prob.unique().tolist()) <= {0.0, 1.0})
        loss.backward()

    def test_polarity_logits_are_in_polarity_order(self):
        model = BiLSTMCNN(10, torch.ones(NUM_ASPECTS, 4), embedding_dim=8, hidden_size=4, num_filters=4, fc_hidden=4).eval()
        with torch.no_grad():
            model.output.weight.zero_()
            model.output.bias.zero_()
            # Make aspect 0 predict "negative" (class 3).
            model.output.bias[3] = 5.0
            _, prob, logits = model(torch.randint(0, 10, (1, 12)))
        self.assertEqual(prob[0, 0].item(), 1.0)
        self.assertEqual(logits[0, 0].argmax().item(), POLARITY2ID["negative"])
        self.assertEqual(prob[0, 1].item(), 0.0)  # ties resolve to none


if __name__ == "__main__":
    unittest.main()
