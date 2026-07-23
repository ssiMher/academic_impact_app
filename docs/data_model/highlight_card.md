# HighlightCard Data Model

`HighlightCard` stores an editable report-ready card derived from one
`StrongEvidence` row.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `scholar_session_id` | Parent scholar session |
| `strong_evidence_id` | Required source evidence |
| `card_type` | Card category |
| `title` | Editable title |
| `subtitle` | Supporting source summary |
| `narrative_zh` | Main Chinese narrative for report/PPT use |
| `narrative_en` | Optional English narrative |
| `body_markdown` | Editable body text |
| `evidence_quote` | Original evidence quote from `StrongEvidence.citation_text` |
| `highlighted_quote_html` | Safe highlighted quote HTML |
| `source_citing_paper_title` | Source citing paper title |
| `source_cited_paper_title` | Source cited paper title |
| `citing_authors_json` | Source citing authors for report and notable-author lookup |
| `notable_author_name` | Matched or manually edited notable author name |
| `notable_author_affiliation` | Notable author affiliation |
| `notable_author_role` | Manual or inferred role label |
| `fellow_status` | `IEEE Fellow`, `ACM Fellow`, `AAAS Fellow`, or `unknown` |
| `venue`, `venue_tier` | Source venue summary |
| `aspect` | Evidence aspect copied from source |
| `stance` | Evidence stance copied from source |
| `evidence_strength` | Evidence strength copied from source |
| `score` | Deterministic source evidence score |
| `source_evidence_id` | Traceable source evidence id, normally equal to `strong_evidence_id` |
| `review_status` | Copied card/evidence review status for report filtering |
| `sort_order` | Display/report order |
| `is_user_edited` | Protects manual edits from regeneration |
| `user_note` | Reviewer/editor note |
| `include_in_report` | Whether the card appears in report exports |
| `matched_template_ids_json` | Template ids copied from source `StrongEvidence` |
| `matched_template_names` | Safe display names for satisfied templates |
| `template_match_reason` | Why the card satisfies matched templates |
| `template_satisfied` | Whether the card satisfies at least one active template |
| `template_failure_reason` | Why active templates were not satisfied |
| `created_at`, `updated_at` | Local timestamps |

## Card Types

- `first_or_seminal_claim`
- `positive_evaluation`
- `detailed_comparison`
- `baseline_or_benchmark`
- `theoretical_foundation`
- `method_foundation`
- `application_extension`
- `important_author_citation`
- `survey_highlight`
- `long_context_citation`
- `limitation_or_negative`

## Invariants

- A card without `strong_evidence_id` is invalid.
- A card without original `evidence_quote` is invalid for report/PPT export.
- `narrative_zh` must stay grounded in `evidence_quote` and source evidence.
- Cards must keep original evidence quotes traceable.
- Regeneration must not overwrite user-edited card text.
- Regeneration must preserve user notes and avoid arbitrary sort-order churn for
  edited cards.
- Unreviewed high-strength evidence can produce a draft card, marked in the
  subtitle.
- Negative evidence becomes `limitation_or_negative` cards and must not be
  rewritten as positive highlight claims.
