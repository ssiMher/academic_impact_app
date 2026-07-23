# Strong Evidence Scoring

Strong evidence scoring is deterministic and local. It exists to keep LLM output
grounded in original text and to make promotion rules testable.

## Inputs

The scorer receives a validated `LlmFinding`:

- `evidence_type`
- `stance`
- `mention_type`
- `citation_text`
- `keywords`
- `reasoning`

## Current Rules

| Condition | Effect |
| --- | --- |
| Missing `citation_text` | Score `0.0`, strength `none` |
| `mention_type == reference_only` | Score `0.0`, strength `none` |
| `mention_type == grouped_citation` | Score `0.25`, strength `weak` |
| `mention_type` is `weak_mention`, `background_mention`, or `passing_mention` | Score `0.35`, strength `weak` |
| Built-in strong evidence type | Adds score |
| `stance` is `positive` or `mixed` | Adds score |
| Longer citation text | Adds a small specificity bonus |
| Scholar queue item is a self-citation | Applies a deterministic downrank after base scoring |

Findings are promoted to `StrongEvidence` only when the deterministic score is
at or above the current promotion threshold used by the analysis handler.

## Scholar Phase 13 Boundary

Scholar full-text analysis reuses the same scorer as ordinary paper analysis.
It does not let the LLM rank evidence directly, does not generate highlight
cards, and does not create final scholar reports.

## Phase 13.5 Regression Rules

Phase 13.5 adds golden regression cases for high-value evidence and weak/noisy
mentions. The system should prefer returning reviewable evidence for
must-not-miss cases, while still blocking weak mentions and grouped citations
from becoming promoted `StrongEvidence`.

Golden must-not-miss cases include positive evaluation, first or seminal claims,
detailed comparison, benchmark use, theoretical foundation, and third-party
positive evidence.

Weak mentions remain below the promotion threshold by deterministic scoring.
Grouped citations are usually filtered, but a narrow review-needed path exists
for high-value grouped findings with explicit quote text, such as detailed
comparison, limitation/negative evidence, baseline use, method foundation, or
first-or-seminal claims. Those are saved with `anchor_status=grouped_citation`
and an evidence note requiring manual attribution review.

Self-citations may still be saved when they contain specific original evidence,
but they receive a deterministic score downrank and are counted separately in
quality summaries.

`fulltext_direct` adds a conservative save-time filter before scoring. Findings
that look like bibliography/reference entries, appear after the References
section, or are generic similar-keyword sentences without an attribution anchor
to the cited paper are not saved as `StrongEvidence`.

Filtering diagnostics should record concrete reasons rather than a generic
catch-all. Current reasons include `saved`, `keep_false`, `no_citation_text`,
`reference_only`, `reference_entry`, `background_neutral`,
`grouped_citation_saved_for_review`, `grouped_citation_too_ambiguous`,
`low_strength`, and `no_body_anchor`.

For `fulltext_direct`, reference-aware anchor matching is part of promotion:

- find the target reference entry in the `References` section
- recover the target marker such as `[15]`
- treat grouped citations that contain the target marker as attributable to the
  cited paper group, with explicit manual-review warning

Quality summaries expose `high_strength_count`, `medium_strength_count`, and
`low_strength_count`. These map to stored strength labels `strong`, `moderate`,
and `weak`.
