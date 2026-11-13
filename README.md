# Aspect-level labels for UIT-VSFC student feedback

Labels, code and per-run results for the FJCAI 2027 paper *A Multi-Aspect Dataset, Benchmark and Error Analysis for Vietnamese Student Feedback Aspect-Based Sentiment Analysis*.

The 16,175 sentences of UIT-VSFC are labeled with 11 aspect categories and three polarities (23,910 aspect–sentiment pairs). **This repository contains no sentence text.** UIT-VSFC asks for citation but states no license, so we do not redistribute its text. Obtain UIT-VSFC from its authors and rebuild the labeled files with the script below.

The comments concern identifiable teaching staff. Use the labels for research on feedback in aggregate, not to assess individual lecturers.

## Labels

`labels/` holds one CSV per split file (`train1.csv` … `train6.csv`, `validation.csv`, `test.csv`), one row per aspect–sentiment pair:

| Column | Meaning |
|---|---|
| `id` | sentence id, unique **within one file only** |
| `uit_vsfc_split` | `train`, `validation` or `test` (UIT-VSFC's own split) |
| `uit_vsfc_row` | 0-based row of the sentence in our copy of that UIT-VSFC split |
| `text_sha256` | SHA-256 of the exact UTF-8 sentence text, used to align with UIT-VSFC |
| `sentiment` | `positive`, `negative` or `neutral` |
| `aspect` | one of the 11 aspect codes in `src/absa/aspects.py` |
| `restored` | 1 for the 51 sentences whose labels were proposed by a second LLM and reviewed by one author (see the paper, Section III-B) |

Group by `id` **within each file** before concatenating files; ids repeat across the six training files.

The labels were produced by an LLM (gpt-oss-120b) with partial human review: 10% of pairs were re-checked by reviewers who saw the LLM label. They are not gold labels. See the paper for the review process and the blind LLM re-annotation checks.

## Rebuilding the data

```bash
python scripts/rebuild_final_data.py \
    --train path/to/uit-vsfc/train/sents.txt \
    --validation path/to/uit-vsfc/dev/sents.txt \
    --test path/to/uit-vsfc/test/sents.txt \
    --out data/Final_Data
```

Each input is either a file with one sentence per line or a CSV with a `sentence` column. Sentences are matched by text hash, not row order. The script prints the dataset hash; the paper's runs used `c13e760bb2d47295b5dea3ddda4e3d1e65f15846d2afece54ec9531db69643f1`.

## Code and results

- `src/absa/`: data loading, preprocessing, metrics, models E0–E5, training, scoring and error analysis. Run the tests with `PYTHONPATH=src python -m unittest discover -s tests` after rebuilding the data.
- `scripts/`: Kaggle job packaging, paper tables, and the 500-sentence LLM cross-check.
- `results/runs/`: the 24 runs in the paper (8 configurations × seeds 42, 43, 44), each with its configuration, evaluation and predictions. Model weights were not saved.
- `results/summary_{validation,test}.json`, `results/error_analysis_test.json`: the numbers reported in the paper. Example sentence text was removed from the error analysis.
- `results/llm_crosscheck/`: the 500-sentence cross-check (sample, per-cell labels, summary). Raw model outputs were removed because they quote the sentences.
- `eval_300/`: specs, addenda, scripts and sanitized results of the 300-sentence blind re-annotation.
- `docs/training-cost.md`: best epoch per seed, training time and GPU memory.

## License

Code (`src/`, `scripts/`, `tests/`) is under the MIT License (`LICENSE`). Labels, results and documentation are under CC BY 4.0 (`LICENSE-DATA`). Neither covers the UIT-VSFC text, which this repository does not contain. Please cite the paper and UIT-VSFC when you use the labels.
