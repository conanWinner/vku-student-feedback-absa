"""BiLSTM-CNN baseline (E1), ported from `billstm_cnn.ipynb`.

Each aspect has a 4-way output: none, positive, neutral, negative. An aspect counts
as present when the argmax is not `none`, so no threshold applies: `aspect_prob` is
returned as 0 or 1 to fit the shared evaluation code.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..data import IGNORE_INDEX, NUM_ASPECTS, POLARITIES

CLASS_NAMES = ("none", "positive", "neutral", "negative")
NONE = 0
# Positions in CLASS_NAMES, listed in POLARITIES order: converts 4-way logits to polarity logits.
POLARITY_CLASSES = [CLASS_NAMES.index(p) for p in POLARITIES]


def to_class_labels(sentiment: torch.Tensor) -> torch.Tensor:
    """Polarity ids with IGNORE_INDEX -> 4-way labels with none = 0."""
    labels = torch.zeros_like(sentiment)
    for polarity_id, class_id in enumerate(POLARITY_CLASSES):
        labels[sentiment == polarity_id] = class_id
    return labels


def build_vocab(token_lists: list[list[str]]) -> dict[str, int]:
    """Vocabulary from the training tokens only."""
    vocab = {"<PAD>": 0, "<UNK>": 1}
    for token in Counter(t for tokens in token_lists for t in tokens):
        vocab[token] = len(vocab)
    return vocab


def class_weights(sentiment: np.ndarray) -> torch.Tensor:
    """Per-aspect square-root inverse frequency, shape (A, 4). Unseen classes get 1."""
    counts = np.zeros((NUM_ASPECTS, len(CLASS_NAMES)))
    labels = to_class_labels(torch.as_tensor(sentiment)).numpy()
    for a in range(NUM_ASPECTS):
        for c in range(len(CLASS_NAMES)):
            counts[a, c] = (labels[:, a] == c).sum()
    total = counts.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore"):
        weights = np.sqrt(total / (len(CLASS_NAMES) * counts))
    weights[counts == 0] = 1.0
    return torch.tensor(weights, dtype=torch.float)


class BiLSTMCNN(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        weights: torch.Tensor,
        embedding_dim: int = 300,
        hidden_size: int = 128,
        num_filters: int = 128,
        kernel_sizes: tuple[int, ...] = (2, 3, 4),
        fc_hidden: int = 128,
        dropout: float = 0.6,
        pretrained_embeddings: np.ndarray | None = None,
    ):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embedding_dim, padding_idx=0)
        if pretrained_embeddings is not None:
            self.embedding.weight.data.copy_(torch.as_tensor(pretrained_embeddings, dtype=torch.float))
            self.embedding.weight.data[0] = 0.0
        self.bilstm = nn.LSTM(embedding_dim, hidden_size, batch_first=True, bidirectional=True)
        self.convs = nn.ModuleList(nn.Conv1d(hidden_size * 2, num_filters, k) for k in kernel_sizes)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(num_filters * len(kernel_sizes), fc_hidden)
        self.output = nn.Linear(fc_hidden, NUM_ASPECTS * len(CLASS_NAMES))
        self.register_buffer("class_weights", weights)

    def forward(self, input_ids, attention_mask=None, aspect_labels=None, sentiment_labels=None):
        lstm_out, _ = self.bilstm(self.embedding(input_ids))
        x = lstm_out.transpose(1, 2)
        pooled = [F.relu(conv(x)).max(dim=2).values for conv in self.convs]
        x = self.dropout(torch.cat(pooled, dim=1))
        x = self.dropout(F.relu(self.fc(x)))
        logits = self.output(x).view(-1, NUM_ASPECTS, len(CLASS_NAMES))

        loss = None
        if sentiment_labels is not None:
            labels = to_class_labels(sentiment_labels)
            loss = sum(
                F.cross_entropy(logits[:, a], labels[:, a], weight=self.class_weights[a]) for a in range(NUM_ASPECTS)
            ) / NUM_ASPECTS

        aspect_prob = (logits.argmax(dim=-1) != NONE).float()
        return loss, aspect_prob, logits[:, :, POLARITY_CLASSES]


def load_word2vec(vocab: dict[str, int], path: str, embedding_dim: int = 300, seed: int = 0) -> tuple[np.ndarray, float]:
    """Word2Vec matrix for the vocabulary; compounds fall back to averaging their syllables."""
    from gensim.models import KeyedVectors  # only this baseline needs gensim

    vectors = KeyedVectors.load_word2vec_format(path, binary=path.endswith(".bin"))
    if vectors.vector_size != embedding_dim:
        raise ValueError(f"expected {embedding_dim}-dim vectors, found {vectors.vector_size}")
    rng = np.random.default_rng(seed)
    matrix = rng.uniform(-0.1, 0.1, (len(vocab), embedding_dim)).astype(np.float32)
    matrix[0] = 0.0
    found = 0
    for word, index in vocab.items():
        if index < 2:
            continue
        if word in vectors:
            matrix[index] = vectors[word]
            found += 1
        else:
            parts = [vectors[p] for p in word.split("_") if p in vectors]
            if parts and "_" in word:
                matrix[index] = np.mean(parts, axis=0)
                found += 1
    return matrix, found / max(len(vocab) - 2, 1)


__all__ = ["BiLSTMCNN", "IGNORE_INDEX", "build_vocab", "class_weights", "load_word2vec", "to_class_labels"]
