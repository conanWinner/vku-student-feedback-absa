"""Train one experiment on one seed and save validation and test probabilities.

Test probabilities are written but never scored here: `absa.evaluate --test` scores them
after the configuration is locked (docs/04-experiment-protocol.md).

    python -m absa.train --model e4 --encoder vinai/phobert-base --seed 42
    python -m absa.train --model bilstm_cnn --word2vec baomoi.vn.model.bin --seed 42

To reproduce the old notebooks (gate G2), add `--selection legacy` and, for E3, `--beta 1.5`.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import random
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from .aspects import aspect_texts
from .data import NUM_ASPECTS, NUM_POLARITIES, dataset_hash, label_arrays, load_split
from .metrics import evaluate
from .models.bilstm_cnn import BiLSTMCNN, build_vocab, class_weights, load_word2vec
from .models.multitask import PRESETS, MultiTaskABSA, encode_descriptions
from .preprocess import preprocess

# Preprocessing is part of the model. Other encoders must pass --preprocess explicitly.
ENCODER_PREPROCESS = {"vinai/phobert-base": "underthesea", "Qualcomm-AI-Research/BamiBERT": "raw"}
SPLITS = ("train", "validation", "test")
MAX_LENGTH = 128


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def sqrt_pos_weight(aspect: np.ndarray) -> torch.Tensor:
    """Square root of the negative/positive ratio, clipped to [1, 20], as in the notebook."""
    positive = aspect.sum(axis=0)
    ratio = (len(aspect) - positive) / (positive + 1e-8)
    return torch.tensor(np.clip(np.sqrt(ratio), 1.0, 20.0), dtype=torch.float)


class EncodedDataset(Dataset):
    def __init__(self, input_ids, aspect, sentiment):
        self.input_ids, self.aspect, self.sentiment = input_ids, aspect, sentiment

    def __len__(self):
        return len(self.input_ids)

    def __getitem__(self, i):
        return self.input_ids[i], self.aspect[i], self.sentiment[i]


def collate(pad_id: int, pad_to: int | None = None):
    """Pad to the longest in the batch, or to `pad_to` (the LSTM runs over padding, so length matters)."""

    def fn(items):
        ids, aspect, sentiment = zip(*items)
        length = pad_to or max(len(x) for x in ids)
        input_ids = torch.full((len(ids), length), pad_id, dtype=torch.long)
        mask = torch.zeros((len(ids), length), dtype=torch.long)
        for row, x in enumerate(ids):
            input_ids[row, : len(x)] = torch.tensor(x, dtype=torch.long)
            mask[row, : len(x)] = 1
        return {
            "input_ids": input_ids,
            "attention_mask": mask,
            "aspect_labels": torch.as_tensor(np.stack(aspect), dtype=torch.float),
            "sentiment_labels": torch.as_tensor(np.stack(sentiment), dtype=torch.long),
        }

    return fn


@torch.no_grad()
def predict(model, loader, device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    probabilities, sentiments = [], []
    for batch in loader:
        _, aspect_prob, sentiment_logits = model(
            batch["input_ids"].to(device), batch["attention_mask"].to(device)
        )
        probabilities.append(aspect_prob.cpu().numpy())
        sentiments.append(sentiment_logits.argmax(dim=-1).cpu().numpy())
    return np.concatenate(probabilities), np.concatenate(sentiments)


def score(metrics: dict, selection: str, model_name: str) -> float:
    if selection == "pair":
        return metrics["pair_f1_micro"]
    if model_name == "bilstm_cnn":  # legacy: billstm_cnn.ipynb selected on aspect F1
        return metrics["aspect_f1_micro"]
    return (metrics["aspect_f1_micro"] * metrics["sentiment_f1_macro_on_gold"]) ** 0.5


def code_version() -> str | None:
    """Commit of this code. Kaggle has no git history, so it reads ABSA_COMMIT there."""
    if os.environ.get("ABSA_COMMIT"):
        return os.environ["ABSA_COMMIT"]
    try:
        root = Path(__file__).resolve().parent
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        return commit + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def prepare_transformer(args, samples, device):
    from transformers import AutoModel, AutoTokenizer

    mode = args.preprocess or ENCODER_PREPROCESS.get(args.encoder)
    if mode is None:
        raise SystemExit(f"--preprocess is required for {args.encoder}; check its model card")
    tokenizer = AutoTokenizer.from_pretrained(args.encoder, revision=args.revision)
    encoder = AutoModel.from_pretrained(args.encoder, revision=args.revision)

    encoded, truncation = {}, {}
    for split in SPLITS:
        texts = [preprocess(s.text, mode) for s in samples[split]]
        ids = tokenizer(texts, truncation=False, add_special_tokens=True)["input_ids"]
        truncation[split] = sum(len(x) > MAX_LENGTH for x in ids) / max(len(ids), 1)
        encoded[split] = tokenizer(texts, truncation=True, max_length=MAX_LENGTH)["input_ids"]

    aspect, _ = label_arrays(samples["train"])
    preset = PRESETS[args.model]
    model = MultiTaskABSA(
        encoder, NUM_ASPECTS, NUM_POLARITIES,
        pos_weight=sqrt_pos_weight(aspect),
        sentiment_class_weight=torch.tensor([1.0, 2.0, 1.0]),
        aspect_branch=preset["aspect_branch"],
        sentiment_branch=preset["sentiment_branch"],
        alpha=args.alpha, beta=args.beta, dropout=0.3,
    ).to(device)
    if preset["query_init"] == "descriptions":
        texts = [preprocess(t, mode) for t in aspect_texts()]
        model.set_queries(encode_descriptions(encoder, tokenizer, texts, device, MAX_LENGTH))

    no_decay = ("bias", "LayerNorm.weight")
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for n, p in model.named_parameters() if not any(x in n for x in no_decay)], "weight_decay": 0.01},
            {"params": [p for n, p in model.named_parameters() if any(x in n for x in no_decay)], "weight_decay": 0.0},
        ],
        lr=args.lr or 2e-5, eps=1e-8,
    )
    settings = {"batch_size": 16, "eval_batch_size": 32, "epochs": 8, "patience": 2, "lr": args.lr or 2e-5, "preprocess": mode}
    extra = {"truncation_rate": truncation, "model_commit": getattr(encoder.config, "_commit_hash", None)}
    return model, optimizer, encoded, collate(tokenizer.pad_token_id), settings, extra


def prepare_bilstm(args, samples, device):
    tokens = {split: [preprocess(s.text, "underthesea").lower().split() for s in samples[split]] for split in SPLITS}
    vocab = build_vocab(tokens["train"])
    pretrained, coverage = None, None
    if args.word2vec:
        pretrained, coverage = load_word2vec(vocab, args.word2vec, seed=args.seed)
    _, sentiment = label_arrays(samples["train"])
    model = BiLSTMCNN(len(vocab), class_weights(sentiment), pretrained_embeddings=pretrained).to(device)
    lr = args.lr or 5e-4
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-3)
    encoded = {split: [[vocab.get(t, 1) for t in row][:MAX_LENGTH] for row in rows] for split, rows in tokens.items()}
    truncation = {split: sum(len(r) > MAX_LENGTH for r in rows) / max(len(rows), 1) for split, rows in tokens.items()}
    settings = {"batch_size": 32, "eval_batch_size": 64, "epochs": 30, "patience": 5, "lr": lr, "preprocess": "underthesea+lower"}
    extra = {
        "truncation_rate": truncation, "vocab_size": len(vocab),
        "word2vec": args.word2vec, "word2vec_coverage": coverage,
    }
    return model, optimizer, encoded, collate(0, pad_to=MAX_LENGTH), settings, extra


def run(args) -> Path:
    set_seed(args.seed)
    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    samples = {split: load_split(args.data_dir, split) for split in SPLITS}
    if args.limit:
        samples = {split: rows[: args.limit] for split, rows in samples.items()}

    is_bilstm = args.model == "bilstm_cnn"
    prepare = prepare_bilstm if is_bilstm else prepare_transformer
    model, optimizer, encoded, collate_fn, settings, extra = prepare(args, samples, device)
    epochs = args.epochs or settings["epochs"]

    def loader(split, shuffle=False, batch_size=None):
        aspect, sentiment = label_arrays(samples[split])
        return DataLoader(
            EncodedDataset(encoded[split], aspect, sentiment),
            batch_size=batch_size or settings["eval_batch_size"],
            shuffle=shuffle,
            collate_fn=collate_fn,
            generator=torch.Generator().manual_seed(args.seed),
        )

    train_loader = loader("train", shuffle=True, batch_size=settings["batch_size"])
    val_loader, test_loader = loader("validation"), loader("test")
    val_aspect, val_sentiment = label_arrays(samples["validation"])

    if is_bilstm:
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=2)
    else:
        from transformers import get_linear_schedule_with_warmup

        total = len(train_loader) * epochs
        scheduler = get_linear_schedule_with_warmup(optimizer, int(total * 0.1), total)

    backbone = ("word2vec" if args.word2vec else "random-embeddings") if is_bilstm else args.encoder.split("/")[-1]
    run_name = args.run_name or f"{args.model}_{backbone}_seed{args.seed}"
    out_dir = Path(args.output_dir) / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    started = time.time()
    best_score, best_epoch, best_state, stale, history = -1.0, 0, None, 0, []

    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            loss, _, _ = model(**batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            if not is_bilstm:
                scheduler.step()
            optimizer.zero_grad()
            losses.append(loss.item())

        probs, sentiments = predict(model, val_loader, device)
        metrics = evaluate(val_aspect, val_sentiment, probs, sentiments, 0.5)
        current = score(metrics, args.selection, args.model)
        if is_bilstm:
            scheduler.step(current)
        history.append({
            "epoch": epoch, "train_loss": float(np.mean(losses)), "val_score": current,
            "val_aspect_f1_micro": metrics["aspect_f1_micro"], "val_pair_f1_micro": metrics["pair_f1_micro"],
            "seconds": time.time() - started,
        })
        print(json.dumps(history[-1]), flush=True)

        if current > best_score:
            best_score, best_epoch, stale = current, epoch, 0
            best_state = copy.deepcopy({k: v.cpu() for k, v in model.state_dict().items()})
        else:
            stale += 1
            if stale >= settings["patience"]:
                break

    model.load_state_dict(best_state)
    model.to(device)
    val_probs, val_sentiments = predict(model, val_loader, device)
    test_probs, test_sentiments = predict(model, test_loader, device)
    np.savez_compressed(
        out_dir / "predictions.npz",
        validation_uid=np.array([s.uid for s in samples["validation"]]),
        validation_aspect_prob=val_probs.astype(np.float32),
        validation_sentiment=val_sentiments.astype(np.int8),
        test_uid=np.array([s.uid for s in samples["test"]]),
        test_aspect_prob=test_probs.astype(np.float32),
        test_sentiment=test_sentiments.astype(np.int8),
    )
    if args.save_checkpoint:
        torch.save(best_state, out_dir / "best_model.pt")

    result = {
        "run_name": run_name,
        "config": {**{k: v for k, v in vars(args).items()}, **settings, "epochs": epochs},
        "code_commit": code_version(),
        "dataset_hash": dataset_hash(args.data_dir),
        "limited_smoke_run": bool(args.limit),
        "num_sentences": {split: len(rows) for split, rows in samples.items()},
        **extra,
        "best_epoch": best_epoch,
        "best_val_score": best_score,
        "history": history,
        "train_seconds": time.time() - started,
        "peak_gpu_memory_mb": torch.cuda.max_memory_allocated(device) / 2**20 if device.type == "cuda" else None,
        "versions": {
            "python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__,
            "transformers": __import__("transformers").__version__ if not is_bilstm else None,
        },
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {out_dir}", flush=True)
    return out_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, choices=[*PRESETS, "bilstm_cnn"])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--encoder", default="vinai/phobert-base")
    parser.add_argument("--revision", default=None, help="pin the encoder revision")
    parser.add_argument("--preprocess", default=None, choices=["underthesea", "raw"])
    parser.add_argument("--word2vec", default=None, help="BiLSTM-CNN only; random embeddings if omitted")
    parser.add_argument("--data-dir", default="data/Final_Data")
    parser.add_argument("--output-dir", default="results/runs")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--beta", type=float, default=1.0, help="protocol value is 1.0; 1.5 only to reproduce E3")
    parser.add_argument("--selection", default="pair", choices=["pair", "legacy"])
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None, help="smoke test: use only the first N sentences per split")
    parser.add_argument("--device", default=None)
    parser.add_argument("--save-checkpoint", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
