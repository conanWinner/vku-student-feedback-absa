"""Rebuild data/Final_Data from the released labels and your own copy of UIT-VSFC.

The labels in labels/ carry no sentence text. Each pair points to a UIT-VSFC
sentence by the SHA-256 of its exact text, so the rebuild does not depend on row
order. For each split, pass a file with one sentence per line (UIT-VSFC's
sents.txt) or a CSV with a `sentence` column.

    python scripts/rebuild_final_data.py \
        --train path/to/train/sents.txt \
        --validation path/to/dev/sents.txt \
        --test path/to/test/sents.txt \
        --out data/Final_Data

The script prints the dataset hash; the paper's runs used c13e760b...
"""
import argparse
import csv
import hashlib
import io
import sys
from pathlib import Path

SPLITS = {
    "train": [f"train{i}.csv" for i in range(1, 7)],
    "validation": ["validation.csv"],
    "test": ["test.csv"],
}
EXPECTED_HASH = "c13e760bb2d47295b5dea3ddda4e3d1e65f15846d2afece54ec9531db69643f1"


def read_sentences(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as f:
            return [row["sentence"] for row in csv.DictReader(f)]
    return path.read_text(encoding="utf-8").splitlines()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for split in SPLITS:
        ap.add_argument(f"--{split}", type=Path, required=True)
    ap.add_argument("--labels", type=Path, default=Path(__file__).resolve().parent.parent / "labels")
    ap.add_argument("--out", type=Path, default=Path("data/Final_Data"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    missing = 0
    for split, files in SPLITS.items():
        by_hash = {}
        for s in read_sentences(getattr(args, split)):
            by_hash.setdefault(hashlib.sha256(s.encode("utf-8")).hexdigest(), s)
        for name in files:
            rows = [["id", "text", "sentiment", "aspect"]]
            with (args.labels / name).open(encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    text = by_hash.get(r["text_sha256"])
                    if text is None:
                        missing += 1
                        continue
                    rows.append([r["id"], text, r["sentiment"], r["aspect"]])
            buf = io.StringIO()
            csv.writer(buf, lineterminator="\r\n").writerows(rows)
            data = buf.getvalue().rstrip("\r\n").encode("utf-8")
            (args.out / name).write_bytes(data)
            digest.update(name.encode())
            digest.update(data)

    h = digest.hexdigest()
    print(f"dataset hash {h}")
    if missing:
        print(f"{missing} pairs had no matching sentence; check that the input is UIT-VSFC", file=sys.stderr)
        return 1
    if h != EXPECTED_HASH:
        print("hash differs from the paper's data (c13e760b...)", file=sys.stderr)
        return 1
    print("matches the data used in the paper")
    return 0


if __name__ == "__main__":
    sys.exit(main())
