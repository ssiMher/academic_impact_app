# Analysis Templates API

Phase 15 adds scholar-session template management pages.

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/scholar-sessions/{session_id}/templates` | Show built-in and active templates |
| POST | `/scholar-sessions/{session_id}/templates/enable` | Enable a template for the session |
| POST | `/scholar-sessions/{session_id}/templates/disable` | Disable a template for the session |
| POST | `/scholar-sessions/{session_id}/templates/custom` | Create a custom active template |
| GET | `/scholar-sessions/{session_id}/templates/{template_id}` | Show template details |

## Forms

Enable and disable forms require `template_id`.

Custom template forms accept:

- `template_name`
- `natural_language_goal`
- `template_type`
- `positive_keywords`, comma-separated
- `negative_keywords`, comma-separated
- `required_patterns`, comma-separated
- `allowed_evidence_types`, comma-separated
- `strict_rules`, comma-separated
- `instruction_text`
- `min_citation_chars`
- `min_citation_words`
- `require_target_marker`
- `allow_grouped_citation`
- `auto_include_in_report`

## Boundaries

Routers do not inspect queue items, evidence, or database rows directly. They
delegate template work to `TemplateService`.

Template routes do not call external scholarly providers or LLM services. They
only create, enable, disable, and display local template records.
