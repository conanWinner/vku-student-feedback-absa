# Pre-registered scoring spec: eval_300 (written BEFORE any eval call)

Version: eval300-spec-v1. Date: 2026-11-09 (UTC+7). Guideline: v2 unchanged (prompt SHA 74d0fd7d…, suggestion-only = neutral).

## Inputs
- Sample: `../human_review_db/eval_sample_DRAFT.jsonl`, 300 sentences, seed 20261110.
- Human reference: rows of `../human_review_db/human_reviewed_segments.jsonl` whose (`_collection`, `csv_id`) is in the sample.
  - One reference cell = (sentence, `user_aspect`), with label `user_sentiment`.
  - Expected: 433 cells, 0 within-cell conflicts. A conflicting cell would be dropped and reported.
  - Cell note group = that row's `note`: "Đã check tay" = **checked**; "Giữ nguyên kết quả AI" = **kept_ai**.
- Human labels are NEVER shown to any model and are NOT used for routing.
- Deviation from the pilot: the pilot also routed "unanimous but differs from previous release". The previous release equals these human labels, so that would leak the reference. That rule is dropped here.

## Pipeline
1. **Stage 1 (voters):** 3 blind voters (cx/gpt-6-luna, ag/claude-opus-4-6-thinking, ag/gemini-3.8-flash-high).
   - Prompt and validity checks identical to the pilot.
   - A vote is valid only with status ok. Timeout, truncation, or schema/evidence error = no vote.
2. **Routing:** a sentence goes to Sol unless it has 3 valid votes AND all 11 aspects are unanimous.
3. **Stage 2 (Sol):** cx/gpt-6.1-sol, reasoning_effort "high" requested, pilot reviewer prompt.
   - Voter labels are anonymized and shuffled (shuffle seed 20261109 + item id).
   - A cell is **sol_resolved** if all of these hold:
     - Sol is valid;
     - a strict voter majority exists (≥2 votes and > half of the valid voter votes);
     - Sol equals that majority;
     - Sol confidence is high or medium;
     - Sol's decision is not abstain/ambiguous.
   - If Sol is invalid: cells with 3 valid unanimous voter votes are **unanimous**; all other cells go to stage 3.
   - Otherwise, any cell not sol_resolved goes to stage 3.
   - Cells of sentences not sent to Sol are **unanimous**.
4. **Stage 3 (tie-break):** ag/claude-opus-5-5-high, run blind with the voter prompt, on every sentence that has ≥1 stage-3 cell.
   - Pool the valid votes: 3 voters + Sol + 4th.
   - **tiebreak_resolved** if all of these hold: the top label has ≥3 votes, the top is unique, the label is in {absent, positive, negative, neutral}, and the supporters include Sol or the 4th model.
   - Otherwise the cell is **unresolved**. No label, no fallback to any original label.
5. **Caps:**
   - 1270 calls total, concurrency 2, no retries, no fallback.
   - Stage budgets: voters ≤ 900; Sol ≤ min(300, remaining); tie-break ≤ remaining.
   - Items beyond budget get no call, and their open cells become unresolved.
6. **Circuit breaker:** stop the stage and report if any of these happen:
   - any 401 or 403;
   - 3 consecutive HTTP/transport errors;
   - more than 20% non-ok results among the last 30 results (checked once ≥30 results exist).

## Metrics
Computed per human reference cell (aspect a, human polarity h ∈ {positive, negative, neutral}). Let d be the final system decision for (sentence, a). Unresolved cells have d = "unresolved".
- **detected** = d ∈ {positive, negative, neutral}.
- **Aspect recall** = #detected / n.
- **Polarity accuracy given detection** = #(d == h) / #detected.
- **Exact match** = #(d == h) / n.
- **Main metric:** unresolved counts as a miss (not detected, not exact).
- **Coverage-conditional:** the same three metrics over cells whose d ≠ unresolved. Coverage = that n / total n is also reported.

Each metric gets a Wilson 95% interval (z = 1.96). Intervals are cell-level and ignore within-sentence clustering; this is stated as a caveat.

**Breakdowns:**
- (a) all cells;
- (b) excluding policy cells (below);
- per aspect;
- per note group (checked / kept_ai);
- per resolution stage (unanimous / sol_resolved / tiebreak_resolved / unresolved).

**Secondary:**
- each single voter's exact match on the same cells (invalid vote = miss);
- count of (sentence, aspect) cells where the system marks an aspect present but the human DB has no row. This is reported as a count only, not as an error, because the DB may be incomplete.

## Policy cells (suggestion-only), excluded in breakdown (b)
A cell is a policy cell if human h = negative AND the sentence is suggestion-only by this fixed text rule (lowercased sentence `s`):
- **has_suggestion:** `s` matches regex `(^|\s)(nên|cần|mong|đề nghị|hy vọng|hi vọng|hãy|hạn chế|bổ sung|thêm|nhiều hơn|cụ thể hơn|rõ hơn|chậm lại|giảm|tăng)(\s|$|[,.])`.
  - EXCEPT when the only `nên` match is preceded by a cause clause. Operationally: if `nên` is the only cue and the token before `nên` is not one of {"thầy","cô","giảng viên","gv","em","sinh viên","sv","trường","khoa","môn","mình","chúng em","các thầy","các cô"} and `nên` is not at the start of the sentence, treat it as "so" (not a suggestion).
- **has_criticism:** `s` matches regex `(^|\s)(không|chưa|kém|tệ|chán|khó hiểu|khó|dở|mờ|hư|hỏng|ồn|nóng|buồn ngủ|lan man|thiếu|ít|quá|hơi|nhàm|tẻ nhạt|qua loa|khó chịu|bất công|trễ|muộn|cũ)(\s|$|[,.])`.
- **suggestion-only** = has_suggestion AND NOT has_criticism.
- Because `không`/`chưa` count as criticism, negated requests ("không nên…") are not suggestion-only. The rule is deliberately conservative and is fixed now. Its hit count is reported.
