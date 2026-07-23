# Template Matching

Template matching is deterministic in Phase 15. It scans queue item text and
StrongEvidence text for active template terms.

## Queue Matching

For queue items, matching uses:

- Citing paper title.
- Cited paper title.
- Venue.
- Citing authors.
- Citation contexts stored on `CitationEdge.edge_meta_json`.
- Target title stored on `CitationEdge.edge_meta_json`.

Matched templates add an explainable bonus to `priority_score`.
`priority_reasons_json` records entries such as:

```json
{"reason": "template_match:baseline_or_benchmark:baseline, benchmark", "delta": 20}
```

User `important` review status still has the highest priority. Rejected and
skipped items remain downranked.

## Evidence Matching

For StrongEvidence, matching uses:

- `citation_text`
- `aspect`
- `stance`
- `evidence_reason`

Matches are stored as `TemplateMatch` records. Evidence pages display matched
terms, match reason, and match score.

## Prompt Integration

Scholar fulltext analysis injects active template prompt fragments into the LLM
prompt. The prompt still requires original `citation_text` and warns that
grouped citations or weak mentions must not be treated as strong evidence.

Disabled templates are not included in prompt fragments. A template can only
reach the prompt if it is active for the current scholar session.
