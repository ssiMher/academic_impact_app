# Scholar Impact Report

Phase 14 scholar reports summarize reviewed evidence through highlight cards.
They do not create new claims and do not re-run analysis.

Phase 15 allows highlight cards to be grouped by active analysis template type
when the source StrongEvidence has a TemplateMatch. This changes organization
only; it does not create report claims without evidence.

Phase 15.5 adds regression coverage for the full template path: queue scoring,
LLM prompt injection, StrongEvidence matching, HighlightCard generation, and
report grouping.

## Markdown Report

`report.md` includes:

- Scholar identity and session counts.
- `publication_count`.
- `citation_edge_count`.
- `analyzed_queue_count`.
- `strong_evidence_count`.
- `important_evidence_count`.
- Highlight cards grouped by `card_type`.
- Chinese narrative (`narrative_zh`) for every included card.
- Template-driven card groups when a card was generated from template-matched
  StrongEvidence.
- A dedicated template-match section in `highlight_cards.md` showing matched
  templates, whether each card satisfies active templates, template match
  reasons, and template failure reasons.
- Original evidence quote for every card.
- Citing paper and cited paper titles.
- Notable author and fellow metadata when available; otherwise `unknown`.
- Evidence reason from the source `StrongEvidence`.

## PPTX Export

`report.pptx` is a first-stage deck export built from report-ready cards. The
deck currently focuses on:

- cover / overview
- one highlight slide per included card
- original evidence quote
- Chinese narrative
- notable author / fellow metadata when available

It must not fabricate fellow identity, positive evaluation, or claims that are
not supported by the source `StrongEvidence`.

## Structured JSON

`structured.json` includes:

- `scholar_session`
- `publications_summary`
- `citation_edges_summary`
- `queue_summary`
- `evidence_summary`
- `strong_evidence`
- `highlight_cards`
- `exports` metadata

## Safety

Reports must not include local PDF paths, extracted text paths, API keys, or raw
provider secrets. Rejected and false-positive evidence is excluded from report
candidates.

Phase 14.5 also excludes cards whose source evidence later becomes `rejected`
or `false_positive`, even if the card was generated earlier. Cards without an
original evidence quote are not reportable.

Template matches are safe to export because they contain only matched terms,
match reason, and deterministic score. They must not include local PDF paths,
API keys, provider secrets, or raw provider responses.

Rejected and false-positive evidence remain excluded from default report
candidates even when they have TemplateMatch records.

## Boundaries

Phase 14 does not implement final narrative polishing, external provider calls,
automatic PDF download, or LLM-based report writing.

Phase 15 does not implement natural language template auto-structuring by LLM.
Custom templates are saved from explicit user input and keyword fields.
