# AnalysisTemplate and TemplateMatch

## AnalysisTemplate

`AnalysisTemplate` stores built-in or session-specific custom templates.

Fields:

- `id`
- `session_kind`
- `session_id`
- `name`
- `description`
- `template_type`
- `natural_language_goal`
- `target_aspects_json`
- `positive_keywords_json`
- `negative_keywords_json`
- `required_evidence_patterns_json`
- `prompt_fragment`
- `scoring_rules_json`
- `is_builtin`
- `is_active`
- `created_at`
- `updated_at`

Built-in templates have `session_id = null`. Enabling a template clones it into
the scholar session so per-session activation does not mutate the built-in
catalog.

Custom template structured rules are stored in `scoring_rules_json`, including
minimum citation length, target-marker requirements, grouped-citation policy,
allowed evidence types, strict rules, and report auto-inclusion. User-provided
analysis instructions are stored in `prompt_fragment` and included in the
`fulltext_template_direct` prompt snapshot.

## TemplateMatch

`TemplateMatch` stores deterministic matches for queue items or evidence.

Fields:

- `id`
- `template_id`
- `strong_evidence_id`
- `queue_item_id`
- `matched_terms_json`
- `matched_reason`
- `match_score`
- `created_at`

At least one of `strong_evidence_id` or `queue_item_id` is set by the service
that creates the match.
