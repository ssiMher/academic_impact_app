# Evidence Templates

Phase 15 adds session-scoped analysis templates for scholar analysis.
Templates guide queue scoring, LLM prompts, evidence matching, highlight card
grouping, and report organization.

## Built-In Templates

The default templates cover:

- `first_or_seminal_claim`
- `detailed_comparison`
- `baseline_or_benchmark`
- `theoretical_foundation`
- `method_foundation`
- `application_extension`
- `important_author_citation`
- `survey_highlight`
- `long_context_citation`
- `positive_evaluation`
- `limitation_or_negative`
- `first_or_pioneering_claim`

Each built-in template includes a Chinese description, English name, natural
language goal, target aspects, keywords, prompt fragment, and scoring rule.

`first_or_pioneering_claim` is satisfied only when body text explicitly contains
first/pioneering/seminal/earliest/first-of-its-kind style language. The system
must not infer firstness from publication year, citation count, or template
intent alone.

## Custom Templates

Users may create custom templates for a scholar session by providing:

- A natural language goal.
- A template type.
- Positive and exclusion keywords.
- Required evidence patterns and allowed evidence types.
- Minimum quote length, target-marker, grouped-citation, and auto-include rules.
- Strict rules and an optional instruction text.

All fields are persisted in `AnalysisTemplate` and its structured scoring rules.
The natural-language goal and instruction text are passed to
`fulltext_template_direct`; they are not reduced to keyword matching.

Fulltext analysis prompts include a structured snapshot of active templates:
template id, name, goal, positive/negative keywords, required patterns, allowed
evidence types, and strict rules. LLM findings may return
`matched_template_ids`, `template_match_reason`, `template_satisfied`, and
`template_failure_reason`; the backend also re-evaluates templates
deterministically if the model omits those fields. Backend validation requires
body evidence, target attribution, configured concepts/patterns, and compliance
with grouped-citation, exclusion, and reference-alignment rules.

## Evidence Boundary

Templates are guidance, not evidence. They must not:

- Generate StrongEvidence without `citation_text`.
- Generate HighlightCard without StrongEvidence.
- Override user-reviewed evidence.
- Let an LLM decide final deterministic scores.

## Phase 15.5 Regression Guarantees

- Disabled templates are excluded from queue scoring.
- Disabled templates are excluded from scholar fulltext LLM prompts.
- Custom templates persist as session-scoped active templates.
- Rebuilding the scholar queue preserves user review status and notes.
- Rebuilding the scholar queue preserves an existing manually attached PDF asset
  on the queue item.
- Template matches may influence ordering and grouping, but never remove the
  requirement for original `citation_text`.
