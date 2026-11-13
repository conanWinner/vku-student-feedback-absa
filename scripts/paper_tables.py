"""Write the LaTeX tables of the paper from files in `results/`, so no number is typed by hand.

    python -m absa.dataset_stats --data-dir data/Final_Data
    python -m absa.summarize results/runs --data-dir data/Final_Data --split test
    python -m absa.error_analysis results/runs --data-dir data/Final_Data
    python scripts/paper_tables.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "tables"

ASPECTS = {
    "ky_nang_giang_day": ("Teaching Skill", "lesson organization and teaching methods"),
    "hanh_vi": ("Behavior", "lecturer's attitude and communication"),
    "de_xuat": ("Suggestion", "students' suggestions and wishes"),
    "bai_tap": ("Assignment", "assignments, their number and types"),
    "chuong_trinh_hoc": ("Curriculum", "curriculum and courses"),
    "kien_thuc": ("Knowledge", "lecturer's subject knowledge"),
    "kinh_nghiem": ("Experience", "practical experience in lectures"),
    "cung_cap_tai_lieu": ("Material Provision", "textbooks and learning materials"),
    "thiet_bi_day_hoc": ("Teaching Equipment", "classrooms, projectors, fans, lights"),
    "cham_diem": ("Grading", "grading activities"),
    "noi_chung": ("General", "other or general comments"),
}


MODELS = {
    "e0_tfidf-svm": "E0 TF-IDF + SVM",
    "e1_bilstm-cnn": "E1 BiLSTM-CNN",
    "e2_phobert": "E2 PhoBERT",
    "e3_phobert": "E3 PhoBERT",
    "e5_phobert": "\\textbf{E5 PhoBERT}",
    "e4_phobert": "E4 PhoBERT",
    "e2_bamibert": "E2 BamiBERT",
    "e4_bamibert": "E4 BamiBERT",
}
SHORT = {name: name.split("_")[0].upper() + (" Bami" if "bamibert" in name else "") for name in MODELS}
VERDICTS = {
    "improvement": "Improvement",
    "small_difference": "Small difference",
    "insufficient_evidence": "Insufficient evidence",
    "worse": "Worse",
}


def score(stat: dict) -> str:
    return f"{100 * stat['mean']:.2f} $\\pm$ {100 * stat['std']:.2f}"


def table_results(summary: dict) -> str:
    rows = []
    for key, name in MODELS.items():
        table = summary["models"][key]
        main = table["global"]
        rows.append(f"{name} & {score(main['aspect_f1_micro'])} & {score(main['pair_f1_micro'])} & {score(table['per_aspect']['pair_f1_micro'])} \\\\")
    return "\n".join([
        "\\begin{tabular}{lccc}", "\\toprule",
        "Model & Task A & Task B & Task B, per-aspect $\\tau$ \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


def table_comparisons(validation: dict, test: dict) -> str:
    rows = []
    for val, tst in zip(validation["comparisons"], test["comparisons"]):
        if (val["a"], val["b"]) != (tst["a"], tst["b"]):
            raise ValueError("validation and test list different comparisons")
        mark = "$^\\dagger$" if tst["role"] == "added_at_lock" else ""
        rows.append(
            f"{SHORT[tst['a']]} $-$ {SHORT[tst['b']]}{mark} & {100 * val['diff']:+.2f} & {100 * tst['diff']:+.2f} "
            f"& [{100 * tst['ci_low']:+.2f}, {100 * tst['ci_high']:+.2f}] & {VERDICTS[tst['verdict']]} \\\\"
        )
    return "\n".join([
        "\\begin{tabular}{lrrcl}", "\\toprule",
        "Comparison & Val. & Test & Test 95\\% CI & Test reading \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


def table_per_aspect(summary: dict, analysis: dict) -> str:
    rows = []
    for key, (name, _) in ASPECTS.items():
        cells = [f"{100 * summary['models'][m]['global']['per_aspect_pair_f1'][key]['mean']:.1f}" for m in ("e1_bilstm-cnn", "e2_phobert", "e5_phobert")]
        errors = analysis["models"]["e5_phobert"]["aspect_errors_mean"][key]
        rows.append(
            f"{name} & {number(analysis['train_support'][key])} & {' & '.join(cells)} "
            f"& {errors['false_positive']:.0f} & {errors['missed']:.0f} & {errors['wrong_sentiment']:.0f} \\\\"
        )
    return "\n".join([
        "\\begin{tabular}{lrrrrrrr}", "\\toprule",
        "Aspect & Train & E1 & E2 & E5 & FP & Miss & Sent. \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


ANALYSIS_MODELS = ("e1_bilstm-cnn", "e2_phobert", "e5_phobert")
GROUPS = {
    "all": "All sentences",
    "single_aspect": "Single aspect",
    "multi_aspect": "Multiple aspects",
    "conflicting_polarity": "Conflicting polarities",
    "contrast_word": "Contrast word",
}
POLARITY_MARKS = {"positive": "+", "negative": "$-$", "neutral": "0"}
# English glosses are written by hand; sentences and labels come from error_analysis_test.json.
GLOSSES = {
    "test:431": "reasonable schedule, relaxed attitude",
    "test:1750": "the classroom equipment needs upgrading",
    "test:2355": "I wish the lecturer would let students write code themselves before giving concrete code, so they can use their reasoning better",
    "test:2571": "the lecturer's way of teaching",
    "test:315": "the lecturer is cheerful and teaches enthusiastically",
    "test:1759": "we do not even know the face, so what is being taught?",
    "test:1929": "classes keep being cancelled without notice",
    "test:3088": "teaches well, explains well, helps students absorb new knowledge easily",
}


def table_groups(analysis: dict) -> str:
    models = analysis["models"]
    rows = []
    for key, name in GROUPS.items():
        cells = [f"{100 * models[m]['group_pair_f1'][key]:.2f}" for m in ANALYSIS_MODELS]
        rows.append(f"{name} & {number(analysis['group_sizes'][key])} & {' & '.join(cells)} \\\\")
    return "\n".join([
        "\\begin{tabular}{lrrrr}", "\\toprule",
        "Sentence group & Sentences & E1 & E2 & E5 \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


def table_polarity(analysis: dict) -> str:
    models = analysis["models"]
    rows = []
    for polarity in ("positive", "negative", "neutral"):
        recall = [f"{100 * models[m]['polarity'][polarity]['pair_recall']:.1f}" for m in ANALYSIS_MODELS]
        accuracy = [f"{100 * models[m]['polarity'][polarity]['sentiment_acc_on_gold']:.1f}" for m in ANALYSIS_MODELS]
        pairs = int(models["e5_phobert"]["polarity"][polarity]["pairs"])
        rows.append(f"{polarity.capitalize()} & {number(pairs)} & {' & '.join(recall)} & {' & '.join(accuracy)} \\\\")
    return "\n".join([
        "\\begin{tabular}{lrrrrrrr}", "\\toprule",
        " & & \\multicolumn{3}{c}{Pair recall} & \\multicolumn{3}{c}{Accuracy, gold aspects} \\\\",
        "Polarity & Pairs & E1 & E2 & E5 & E1 & E2 & E5 \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


def table_cost(runs_dir: Path) -> str:
    rows = []
    for key, name in MODELS.items():
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(runs_dir.glob(f"{key}_seed*/result.json"))]
        if len(runs) != 3:
            raise ValueError(f"{key}: expected 3 runs, found {len(runs)}")
        if key == "e0_tfidf-svm":
            rows.append(f"{name} & -- & $<$1 & -- \\\\")
            continue
        epochs = ", ".join(str(r["best_epoch"]) for r in runs)
        minutes = sum(r["train_seconds"] for r in runs) / len(runs) / 60
        memory = max(r["peak_gpu_memory_mb"] for r in runs) / 1024
        rows.append(f"{name} & {epochs} & {minutes:.1f} & {memory:.2f} \\\\")
    return "\n".join([
        "\\begin{tabular}{lccc}", "\\toprule",
        "Model & Best epoch per seed & Minutes & GPU GB \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


def _pairs(labels: list[str]) -> str:
    if not labels:
        return "none"
    parts = []
    for label in labels:
        aspect, polarity = label.split(":")
        parts.append(f"\\mbox{{{ASPECTS[aspect][0]} {POLARITY_MARKS[polarity]}}}")
    return "; ".join(parts)


def table_examples(analysis: dict) -> str:
    sections = [
        ("e5_right_e2_wrong", "e2_phobert_seed42", "E5 correct on all seeds, E2 wrong on all seeds (prediction: E2, seed 42)"),
        ("e2_right_e5_wrong", "e5_phobert_seed42", "E2 correct on all seeds, E5 wrong on all seeds (prediction: E5, seed 42)"),
    ]
    rows = []
    for side, field, title in sections:
        rows.append(f"\\multicolumn{{3}}{{l}}{{\\textit{{{title}}}}} \\\\")
        for example in analysis["examples"][side]:
            text = example["text"].replace(" ,", ",").replace(" .", ".").strip()
            rows.append(f"{text} (``{GLOSSES[example['uid']]}'') & {_pairs(example['gold'])} & {_pairs(example[field])} \\\\")
    return "\n".join([
        "\\begin{tabularx}{\\textwidth}{@{}>{\\raggedright\\arraybackslash}X >{\\raggedright\\arraybackslash}p{0.23\\textwidth} >{\\raggedright\\arraybackslash}p{0.23\\textwidth}@{}}", "\\toprule",
        "Sentence & Gold & Prediction \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabularx}", "",
    ])


def number(value: int) -> str:
    return f"{value:,}"


def table_aspects(stats: dict) -> str:
    rows = []
    per_aspect = stats["all"]["per_aspect"]
    for key, (name, description) in ASPECTS.items():
        row = per_aspect[key]
        total = sum(row.values())
        rows.append(f"{name} & {description} & {number(row['positive'])} & {number(row['negative'])} & {number(row['neutral'])} & {number(total)} \\\\")
    polarity = stats["all"]["polarity"]
    total = (f"Total & & {number(polarity['positive'])} & {number(polarity['negative'])} & {number(polarity['neutral'])} & {number(stats['all']['pairs'])} \\\\")
    return "\n".join([
        "\\begin{tabular}{llrrrr}", "\\toprule",
        "Aspect & Scope & Pos. & Neg. & Neu. & Total \\\\", "\\midrule", *rows, "\\midrule", total, "\\bottomrule", "\\end{tabular}", "",
    ])


def table_splits(stats: dict) -> str:
    rows = []
    for name, row in [("Train", stats["splits"]["train"]), ("Validation", stats["splits"]["validation"]), ("Test", stats["splits"]["test"]), ("All", stats["all"])]:
        rows.append(f"{name} & {number(row['sentences'])} & {number(row['pairs'])} & {row['pairs_per_sentence']:.2f} & {number(row['multi_aspect_sentences'])} & {row['mean_tokens']:.1f} \\\\")
    return "\n".join([
        "\\begin{tabular}{lrrrrr}", "\\toprule",
        "Split & Sentences & Pairs & Pairs/sent. & Multi-aspect & Tokens \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}", "",
    ])


if __name__ == "__main__":
    stats = json.loads((ROOT / "results" / "dataset_stats.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "aspects.tex").write_text(table_aspects(stats), encoding="utf-8")
    (OUT / "splits.tex").write_text(table_splits(stats), encoding="utf-8")
    validation = json.loads((ROOT / "results" / "summary_validation.json").read_text(encoding="utf-8"))
    test = json.loads((ROOT / "results" / "summary_test.json").read_text(encoding="utf-8"))
    analysis = json.loads((ROOT / "results" / "error_analysis_test.json").read_text(encoding="utf-8"))
    for hash_ in (validation["dataset_hash"], test["dataset_hash"]):
        if hash_ != stats["dataset_hash"]:
            raise ValueError("results and dataset statistics come from different datasets")
    (OUT / "results.tex").write_text(table_results(test), encoding="utf-8")
    (OUT / "comparisons.tex").write_text(table_comparisons(validation, test), encoding="utf-8")
    (OUT / "per_aspect.tex").write_text(table_per_aspect(test, analysis), encoding="utf-8")
    (OUT / "groups.tex").write_text(table_groups(analysis), encoding="utf-8")
    (OUT / "polarity.tex").write_text(table_polarity(analysis), encoding="utf-8")
    (OUT / "cost.tex").write_text(table_cost(ROOT / "results" / "runs"), encoding="utf-8")
    (OUT / "examples.tex").write_text(table_examples(analysis), encoding="utf-8")
    print("wrote", OUT, f"(dataset {stats['dataset_hash'][:8]})")
