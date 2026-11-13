"""Multi-task ABSA on a Transformer encoder: experiments E2, E3, E5 and E4.

| Experiment | Aspect branch | Sentiment branch | Query init |
|------------|---------------|------------------|------------|
| E2         | mean pooling  | mean pooling     | -          |
| E3         | mean pooling  | aspect query     | random     |
| E5         | aspect query  | aspect query     | random     |
| E4         | aspect query  | aspect query     | descriptions |

E2 and E3 reproduce the two heads in `phobert_multitask.ipynb`.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from ..data import IGNORE_INDEX

PRESETS = {
    "e2": {"aspect_branch": "mean", "sentiment_branch": "mean", "query_init": None},
    "e3": {"aspect_branch": "mean", "sentiment_branch": "query", "query_init": "random"},
    "e5": {"aspect_branch": "query", "sentiment_branch": "query", "query_init": "random"},
    "e4": {"aspect_branch": "query", "sentiment_branch": "query", "query_init": "descriptions"},
}


def mean_pooling(hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Average token states, ignoring padding."""
    mask = attention_mask.unsqueeze(-1).float()
    return (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)


class MultiTaskABSA(nn.Module):
    def __init__(
        self,
        encoder: nn.Module,
        num_aspects: int,
        num_polarities: int,
        pos_weight: torch.Tensor,
        sentiment_class_weight: torch.Tensor,
        aspect_branch: str = "mean",
        sentiment_branch: str = "mean",
        alpha: float = 1.0,
        beta: float = 1.0,
        dropout: float = 0.3,
        num_heads: int = 8,
    ):
        super().__init__()
        if aspect_branch not in ("mean", "query") or sentiment_branch not in ("mean", "query"):
            raise ValueError("branches must be 'mean' or 'query'")
        if aspect_branch == "query" and sentiment_branch != "query":
            raise ValueError("no experiment uses query attention for aspects only")

        hidden = encoder.config.hidden_size
        self.encoder = encoder
        self.num_aspects, self.num_polarities = num_aspects, num_polarities
        self.aspect_branch, self.sentiment_branch = aspect_branch, sentiment_branch
        self.alpha, self.beta = alpha, beta
        self.dropout = nn.Dropout(dropout)
        self.register_buffer("pos_weight", pos_weight)
        self.register_buffer("sentiment_class_weight", sentiment_class_weight)

        if sentiment_branch == "query":
            self.aspect_embedding = nn.Embedding(num_aspects, hidden)
            self.cross_attention = nn.MultiheadAttention(hidden, num_heads, dropout=dropout, batch_first=True)
            self.sentiment_head = nn.Sequential(
                nn.Linear(hidden * 2, hidden), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden, num_polarities)
            )
        else:
            self.sentiment_head = nn.Linear(hidden, num_aspects * num_polarities)

        if aspect_branch == "query":
            # One linear classifier per aspect, each on that aspect's own vector.
            self.aspect_weight = nn.Parameter(torch.empty(num_aspects, hidden))
            self.aspect_bias = nn.Parameter(torch.zeros(num_aspects))
            nn.init.xavier_uniform_(self.aspect_weight)
        else:
            self.aspect_head = nn.Linear(hidden, num_aspects)

    def set_queries(self, queries: torch.Tensor) -> None:
        """Replace the initial queries (E4). They keep training afterwards."""
        self.aspect_embedding.weight.data.copy_(queries)

    def forward(self, input_ids, attention_mask, aspect_labels=None, sentiment_labels=None):
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        pooled = self.dropout(mean_pooling(hidden, attention_mask))

        if self.sentiment_branch == "query":
            query = self.aspect_embedding.weight.unsqueeze(0).expand(input_ids.size(0), -1, -1)
            sequence = self.dropout(hidden)
            attended, _ = self.cross_attention(
                query, sequence, sequence, key_padding_mask=attention_mask == 0
            )
            sentiment_logits = self.sentiment_head(torch.cat([attended, query], dim=-1))
        else:
            sentiment_logits = self.sentiment_head(pooled).view(-1, self.num_aspects, self.num_polarities)

        if self.aspect_branch == "query":
            aspect_logits = (attended * self.aspect_weight).sum(dim=-1) + self.aspect_bias
        else:
            aspect_logits = self.aspect_head(pooled)

        loss = None
        if aspect_labels is not None:
            aspect_loss = nn.functional.binary_cross_entropy_with_logits(
                aspect_logits, aspect_labels, pos_weight=self.pos_weight
            )
            sentiment_loss = nn.functional.cross_entropy(
                sentiment_logits.reshape(-1, self.num_polarities),
                sentiment_labels.reshape(-1),
                weight=self.sentiment_class_weight,
                ignore_index=IGNORE_INDEX,
            )
            loss = self.alpha * aspect_loss + self.beta * sentiment_loss
        return loss, torch.sigmoid(aspect_logits), sentiment_logits


@torch.no_grad()
def encode_descriptions(encoder, tokenizer, texts: list[str], device, max_length: int = 128) -> torch.Tensor:
    """Mean-pooled encoder vectors of the aspect descriptions, shape (A, H)."""
    was_training = encoder.training
    encoder.eval()
    batch = tokenizer(texts, padding=True, truncation=True, max_length=max_length, return_tensors="pt").to(device)
    hidden = encoder(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]).last_hidden_state
    vectors = mean_pooling(hidden, batch["attention_mask"])
    encoder.train(was_training)
    return vectors
