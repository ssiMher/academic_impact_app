# StrongEvidence Data Model

`StrongEvidence` stores evidence promoted from a validated LLM finding by local
deterministic scoring. It is not created directly from model confidence.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `fulltext_result_id` | Source `FulltextAnalysisResult` |
| `scholar_session_id` | Optional parent scholar session |
| `queue_item_id` | Optional scholar queue item |
| `citation_edge_id` | Optional source citation edge |
| `aspect` | Evidence type such as `method_foundation` |
| `stance` | `positive`, `neutral`, `negative`, or `mixed` |
| `mention_type` | Mention specificity, e.g. `strong` or `grouped_citation` |
| `citation_text` | Original cited text span required for evidence |
| `highlighted_text_html` | Safe HTML with keyword `<mark>` tags |
| `highlight_keywords_json` | Keywords actually found in the citation text |
| `evidence_reason` | Deterministic scoring rationale |
| `evidence_strength` | Local strength label such as `moderate` or `strong` |
| `score` | Deterministic numeric score |
| `matched_template_ids_json` | Active template ids satisfied by this evidence |
| `template_match_reason` | Deterministic explanation for satisfied template matches |
| `template_satisfied` | Whether at least one active template was satisfied |
| `template_failure_reason` | Reasons active templates were not satisfied |
| `page`, `span_index` | Optional location metadata |
| `anchor_status` | Whether the citation anchor matched local spans |
| `is_self_citation` | Boolean self-citation flag from queue metadata |
| `third_party_status` | Queue-derived third-party status |
| `review_status` | `unreviewed`, `accepted`, `rejected`, `false_positive`, `important`, or `needs_discussion` |
| `user_note` | Human reviewer note |
| `corrected_label` | Optional human-corrected evidence label |
| `created_at`, `updated_at` | Local timestamps |

## Review Preservation

Repeated analysis may update derived fields such as score, highlighted text, and
source result id, but it must not overwrite `review_status`, `user_note`, or
`corrected_label`.

Rejected and false-positive evidence are excluded from future report-candidate
lists by default. This does not generate a scholar report in Phase 13.5; it only
defines the candidate filter for later report work.

## Promotion Rules

- No `citation_text`, no `StrongEvidence`.
- Bibliography/reference-list entries are not `StrongEvidence`; they are treated
  as `reference_only` and filtered before saving.
- In `fulltext_direct`, a quote must be attributable to the cited paper in the
  main body. Generic similar-keyword sentences without an anchor to the cited
  paper are not saved.
- Grouped citations are scored weakly and are not promoted by default.
- Weak, background, or passing mentions are scored weakly and are not promoted
  by default.
- Scores are computed locally by `app/analysis/evidence_scoring.py`.
- The LLM provider does not decide final evidence ranking.

## Quality Summary

Scholar evidence pages expose:

- `total_evidence_count`
- `accepted_count`
- `rejected_count`
- `important_count`
- `false_positive_count`
- `unreviewed_count`
- `third_party_evidence_count`
- `self_citation_evidence_count`
- `high_strength_count`
- `medium_strength_count`
- `low_strength_count`
