"""Text preprocessing. Each encoder declares which mode it needs."""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """NFC-normalize, trim, and drop leading dots or dashes."""
    text = unicodedata.normalize("NFC", str(text).strip())
    return re.sub(r"^[\s.\-]+", "", text)


def preprocess(text: str, mode: str) -> str:
    """`underthesea`: word-segmented, as in the PhoBERT notebook. `raw`: normalized only."""
    text = normalize(text)
    if mode == "raw":
        return text
    if mode == "underthesea":
        from underthesea import word_tokenize  # slow to import; only PhoBERT needs it

        return word_tokenize(text, format="text")
    raise ValueError(f"unknown preprocessing mode: {mode!r}")
