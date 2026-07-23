# Evidence Quality Regression

Phase 13.5 introduces golden regression cases for scholar `StrongEvidence`.
These cases live in `tests/golden/scholar_evidence/` and are executed by
`tests/test_scholar_evidence.py`.

## Golden Case Shape

Each fixture contains:

- `target_paper`
- `citing_paper`
- `candidate_spans`
- `fake_llm_response`
- `expected.labels`
- `expected.keep`
- `expected.evidence_strength`
- `expected.highlight_keywords`
- `expected.must_not_miss`

Tests inject the fixture response through a static fake LLM provider. They still
exercise the real scholar fulltext service, database persistence, deterministic
scoring, evidence upsert, and keyword highlighting.

## Covered Cases

- `positive_evaluation_case`
- `first_or_seminal_claim_case`
- `detailed_comparison_case`
- `baseline_or_benchmark_case`
- `theoretical_foundation_case`
- `weak_mention_should_not_be_strong_case`
- `grouped_citation_should_not_be_high_strength_case`
- `self_citation_should_be_downranked_case`
- `third_party_positive_case`

## Must-Not-Miss Rule

For golden cases marked `must_not_miss`, the system should preserve a
reviewable `StrongEvidence` row when the finding includes original
`citation_text` and passes deterministic scoring.

## False Positive Control

Weak mentions and grouped citations are expected to remain below the promotion
threshold. Their validated LLM findings may remain in `FulltextAnalysisResult`,
but they must not become `StrongEvidence`.

## Review Preservation

Re-analysis may update derived fields, but it must preserve:

- `review_status`
- `user_note`
- `corrected_label`

This keeps the human review loop authoritative over repeated model runs.
