"""Load `data/Final_Data` into one multi-label sample per sentence.

Ids are unique only within a file: the train files each restart from 1, so rows
must be grouped per file before the files are concatenated.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Same order as the existing notebooks, so label indices stay comparable.
ASPECTS = (
    "ky_nang_giang_day",
    "hanh_vi",
    "de_xuat",
    "bai_tap",
    "chuong_trinh_hoc",
    "kien_thuc",
    "kinh_nghiem",
    "cung_cap_tai_lieu",
    "thiet_bi_day_hoc",
    "cham_diem",
    "noi_chung",
)
POLARITIES = ("negative", "neutral", "positive")
NUM_ASPECTS = len(ASPECTS)
NUM_POLARITIES = len(POLARITIES)
ASPECT2ID = {name: i for i, name in enumerate(ASPECTS)}
POLARITY2ID = {name: i for i, name in enumerate(POLARITIES)}
IGNORE_INDEX = -100

SPLIT_FILES = {
    "train": tuple(f"train{i}.csv" for i in range(1, 7)),
    "validation": ("validation.csv",),
    "test": ("test.csv",),
}


@dataclass(frozen=True)
class Sample:
    """One sentence. `uid` is unique across the whole dataset, `id` is not."""

    uid: str
    text: str
    aspect: np.ndarray  # (NUM_ASPECTS,) float32 multi-hot
    sentiment: np.ndarray  # (NUM_ASPECTS,) int64, IGNORE_INDEX where the aspect is absent


def load_file(path: str | Path) -> list[Sample]:
    """Group one CSV by `id`. Bad rows raise instead of being skipped silently."""
    path = Path(path)
    groups: dict[int, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            groups.setdefault(int(row["id"]), []).append(row)

    samples = []
    for sent_id in sorted(groups):
        rows = groups[sent_id]
        where = f"{path.name} id={sent_id}"
        if len({r["text"] for r in rows}) != 1:
            raise ValueError(f"{where}: one id holds different sentences")

        aspect = np.zeros(NUM_ASPECTS, dtype=np.float32)
        sentiment = np.full(NUM_ASPECTS, IGNORE_INDEX, dtype=np.int64)
        for row in rows:
            name, polarity = row["aspect"].strip(), row["sentiment"].strip()
            if name not in ASPECT2ID:
                raise ValueError(f"{where}: unknown aspect {name!r}")
            if polarity not in POLARITY2ID:
                raise ValueError(f"{where}: unknown sentiment {polarity!r}")
            a, p = ASPECT2ID[name], POLARITY2ID[polarity]
            if sentiment[a] not in (IGNORE_INDEX, p):
                raise ValueError(f"{where}: conflicting sentiment for {name}")
            aspect[a], sentiment[a] = 1.0, p

        samples.append(Sample(f"{path.stem}:{sent_id}", rows[0]["text"], aspect, sentiment))
    return samples


def load_split(data_dir: str | Path, split: str) -> list[Sample]:
    """Load a split, grouping each file on its own before concatenating."""
    samples: list[Sample] = []
    for name in SPLIT_FILES[split]:
        samples.extend(load_file(Path(data_dir) / name))
    return samples


def label_arrays(samples: list[Sample]) -> tuple[np.ndarray, np.ndarray]:
    """Stack samples into aspect (N, A) and sentiment (N, A) arrays."""
    return np.stack([s.aspect for s in samples]), np.stack([s.sentiment for s in samples])


def dataset_hash(data_dir: str | Path) -> str:
    """SHA-256 over all split files, to record which data a run actually used."""
    digest = hashlib.sha256()
    for split in ("train", "validation", "test"):
        for name in SPLIT_FILES[split]:
            digest.update(name.encode())
            digest.update((Path(data_dir) / name).read_bytes())
    return digest.hexdigest()
