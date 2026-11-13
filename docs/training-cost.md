# Training cost

Per-seed best epoch, mean training time, and peak GPU memory for the 24 runs in the FJCAI paper. Times are indicative: the runs shared one session on two GPUs. Neural models used an NVIDIA T4.

| Model | Best epoch per seed | Minutes | GPU GB |
|---|---|---:|---:|
| E0 TF-IDF + SVM | -- | <1 | -- |
| E1 BiLSTM-CNN | 14, 17, 15 | 1.5 | 0.21 |
| E2 PhoBERT | 8, 8, 8 | 14.2 | 2.77 |
| E3 PhoBERT | 6, 6, 7 | 14.6 | 2.82 |
| E5 PhoBERT | 6, 7, 7 | 14.6 | 2.82 |
| E4 PhoBERT | 8, 8, 8 | 14.6 | 2.82 |
| E2 BamiBERT | 6, 8, 5 | 14.5 | 2.41 |
| E4 BamiBERT | 4, 5, 7 | 13.7 | 2.46 |

The manuscript points here instead of printing this table. The conference submission does not include a separate supplementary file.
