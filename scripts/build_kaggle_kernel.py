"""Build a private Kaggle notebook that embeds `src/absa` and runs one job.

A Kaggle notebook is a single uploaded file, so the source is embedded instead of
being published as a separate dataset. The output folder holds the notebook and
`kernel-metadata.json`:

    python scripts/build_kaggle_kernel.py g2-reproduction --owner thngonquang
    kaggle kernels push -p kaggle/g2-reproduction

Pushing starts the run on Kaggle and uses GPU quota.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Dataset hash of `data/Final_Data` at commit e89f1ce (16,124 sentences), for gate G2.
OLD_DATA_HASH = "a947ca4a9e5ed36625eb97abe9e63f2f4f5b66e66f109b31e665890cb3e05899"

SEEDS = (42, 43, 44)
BAMIBERT = "Qualcomm-AI-Research/BamiBERT"
# Hugging Face commits, as recorded by the pilot and still current on 2026-11-01.
PHOBERT_PIN = " --revision 01daacda68afe13d83023d16ec647239e344a1e6"
BAMIBERT_PIN = f" --encoder {BAMIBERT} --revision 57bc1340debbe4e348ec549047a763caebe4a977"


def p0_task(model: str, seed: int, name: str, extra: str = "") -> list[str]:
    """Train, then score validation. Test stays unscored until the configuration is locked."""
    return [
        f"python -m absa.train --model {model} --seed {seed}{extra} --data-dir {{data}} --output-dir results/runs --run-name {name}_seed{seed}",
        f"python -m absa.evaluate results/runs/{name}_seed{seed}",
    ]


JOBS = {
    "g2-reproduction": {
        "title": "VKU ABSA G2 Reproduction",
        "dataset_sources": ["conanwinner1/vku-feedback"],
        "model_sources": ["conanwinner1/w2vec/pyTorch/default/1"],
        "expected_data_hash": OLD_DATA_HASH,
        "tasks": [
            [
                "python -m absa.train --model e3 --seed 42 --beta 1.5 --selection legacy --data-dir {data} --output-dir results/g2 --run-name e3_seed42_legacy",
                "python -m absa.evaluate results/g2/e3_seed42_legacy --test",
            ],
            [
                "python -m absa.train --model bilstm_cnn --seed 42 --selection legacy --word2vec {word2vec} --data-dir {data} --output-dir results/g2 --run-name e1_seed42_legacy",
                "python -m absa.evaluate results/g2/e1_seed42_legacy --test",
            ],
        ],
    },
    # One seed on the old dataset: checks that E4 and BamiBERT run, and how long they take.
    # Validation only. These runs are not results for the paper.
    "pilot": {
        "title": "VKU ABSA Pilot E4 BamiBERT",
        "dataset_sources": ["conanwinner1/vku-feedback"],
        "expected_data_hash": OLD_DATA_HASH,
        "extra_packages": ["transformers<=5.5.0"],
        "tasks": [
            p0_task("e4", 42, "e4_phobert"),
            p0_task("e2", 42, "e2_bamibert", f" --encoder {BAMIBERT}"),
            p0_task("e4", 42, "e4_bamibert", f" --encoder {BAMIBERT}"),
        ],
    },
    # The 21 core runs of docs/04-experiment-protocol.md. Needs --dataset and --data-hash:
    # it only runs on the human-reviewed data, identified by its hash.
    "p0": {
        "title": "VKU ABSA P0 Core",
        "dataset_sources": None,
        "model_sources": ["conanwinner1/w2vec/pyTorch/default/1"],
        "expected_data_hash": None,
        "extra_packages": ["transformers<=5.5.0"],  # same version for every encoder
        "tasks": [
            *[p0_task(m, s, f"{m}_phobert", PHOBERT_PIN) for m in ("e2", "e3", "e5", "e4") for s in SEEDS],
            *[p0_task(m, s, f"{m}_bamibert", BAMIBERT_PIN) for m in ("e2", "e4") for s in SEEDS],
            *[p0_task("bilstm_cnn", s, "e1_bilstm-cnn", " --word2vec {word2vec}") for s in SEEDS],
        ],
    },
}

SETUP_CELL = """\
import glob, json, os, subprocess, sys
WORK = "/kaggle/working"
os.chdir(WORK)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "underthesea", "gensim", *EXTRA_PACKAGES], check=True)
print(subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True).stdout.count("\\n"), "packages")
print(subprocess.run(f"{sys.executable} -c 'import torch, transformers; print(torch.__version__, transformers.__version__)'", shell=True, capture_output=True, text=True).stdout)
print(subprocess.run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True, capture_output=True, text=True).stdout)
"""

RUN_CELL = """\
sys.path.insert(0, os.path.join(WORK, "src"))
os.environ["PYTHONPATH"] = os.path.join(WORK, "src")
os.environ["ABSA_COMMIT"] = {code_version!r}
from absa.data import dataset_hash

def find_one(pattern):
    hits = glob.glob(pattern, recursive=True)
    if not hits:
        raise FileNotFoundError(pattern)
    return hits[0]

data = os.path.dirname(find_one("/kaggle/input/**/train1.csv"))
word2vec = next(iter(glob.glob("/kaggle/input/**/baomoi.vn.model.bin", recursive=True)), "")
actual = dataset_hash(data)
print("data dir:", data)
print("dataset hash:", actual)
if actual != {expected!r}:
    raise ValueError(f"dataset hash mismatch, expected {expected}")

tasks = [[c.format(data=data, word2vec=word2vec) for c in task] for task in {tasks!r}]
with open("tasks.json", "w", encoding="utf-8") as f:
    json.dump(tasks, f)
subprocess.run([sys.executable, "-m", "absa.run_jobs", "tasks.json"], check=True)
"""


def source_files() -> dict[str, str]:
    """Relative path -> content for everything under src/absa."""
    return {
        str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "src" / "absa").rglob("*.py"))
    }


def code_version(files: dict[str, str]) -> str:
    """Git commit plus a digest of the embedded source, so uncommitted code stays traceable."""
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return f"{commit}+src-{digest}"


def bundle_cell(files: dict[str, str]) -> str:
    return (
        "from pathlib import Path\n"
        f"FILES = {files!r}\n"
        "for name, text in FILES.items():\n"
        "    path = Path(WORK) / name\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.write_text(text, encoding='utf-8')\n"
        "print(len(FILES), 'source files written')\n"
    )


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}


def build(job_name: str, owner: str, dataset: str | None = None, data_hash: str | None = None) -> Path:
    job = JOBS[job_name]
    dataset_sources = [dataset] if dataset else job["dataset_sources"]
    expected = data_hash or job["expected_data_hash"]
    if not dataset_sources or not expected:
        raise SystemExit(f"job {job_name} needs --dataset and --data-hash")
    files = source_files()
    run_cell = RUN_CELL.format(code_version=code_version(files), expected=expected, tasks=job["tasks"])
    notebook = {
        "cells": [
            code_cell(f"EXTRA_PACKAGES = {job.get('extra_packages', [])!r}\n" + SETUP_CELL),
            code_cell(bundle_cell(files)),
            code_cell(run_cell),
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out_dir = ROOT / "kaggle" / job_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "notebook.ipynb").write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    metadata = {
        "id": f"{owner}/{'-'.join(job['title'].lower().split())}",  # Kaggle derives the slug from the title
        "title": job["title"],
        "code_file": "notebook.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": dataset_sources,
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": job.get("model_sources", []),
    }
    (out_dir / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=JOBS)
    parser.add_argument("--owner", required=True, help="the logged-in Kaggle account")
    parser.add_argument("--dataset", help="Kaggle dataset, overrides the job's default")
    parser.add_argument("--data-hash", help="expected dataset hash; the run stops on a mismatch")
    args = parser.parse_args()
    print(build(args.job, args.owner, args.dataset, args.data_hash))
