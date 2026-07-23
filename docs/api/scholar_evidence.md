# Scholar Evidence API

Phase 13 analyzes selected, PDF-ready `DeepAnalysisQueueItem` rows and persists
`FulltextAnalysisResult` plus eligible `StrongEvidence`. It reuses the Phase 6
candidate span, LLM parser, deterministic scoring, and keyword highlighting
pipeline.

This phase does not create highlight cards, final scholar reports, automatic PDF
downloads, real Scopus/Elsevier integrations, or complex author disambiguation.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/scholar-sessions/{session_id}/queue/analyze` | Enqueue `analyze_scholar_queue` for selected queue items |
| `GET` | `/scholar-sessions/{session_id}/evidence` | Show scholar strong evidence list |
| `GET` | `/scholar-sessions/{session_id}/analysis-debug` | Show recent full-text analysis diagnostics, prompt preview, and debug links |
| `GET` | `/scholar-sessions/{session_id}/analysis-debug/{result_id}/{kind}` | Read one debug artifact: `prompt`, `raw_response`, `normalized_response`, or `metadata` |
| `POST` | `/scholar-sessions/{session_id}/evidence/{evidence_id}/review` | Update evidence `review_status`, `user_note`, and optional `corrected_label` |

## Evidence Filters

The evidence page supports `?view=` values:

- `all`
- `accepted`
- `important`
- `unreviewed`
- `false_positive`
- `positive`
- `high_strength`
- `first_or_seminal_claim`
- `detailed_comparison`
- `baseline_or_benchmark`
- `method_foundation`
- `theoretical_foundation`
- `third_party_only`
- `exclude_self_citation`

## Analyze Behavior

`POST /scholar-sessions/{session_id}/queue/analyze` only enqueues a local task.
It does not run LLM analysis inside the HTTP request thread. The form accepts
`analysis_scope`:

- `candidate_spans`: candidate-span analysis, faster but may miss evidence.
- `fulltext_direct`: direct full-text analysis, slower and bounded by
  `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`.

The task analyzes selected queue items with `pdf_readiness_status` equal to
`manual_pdf`, `reused_pdf`, or `local_library_pdf`. `need_pdf` items are
skipped with a clear warning and do not crash the whole batch.

If `fulltext_direct` completes with `findings=[]`, the evidence page shows the
analysis scope, full-text character count, LLM finding count, and a clear empty
state instead of silently showing only an empty evidence list.

If `llm_findings_count > 0` but `generated_strong_evidence_count == 0`, the
evidence page shows:

- filter reason distribution
- per-finding citation preview
- evidence type / stance / mention type
- filter reason
- model reasoning

This makes it clear whether the result was filtered as `background_neutral`,
`reference_only`, `reference_entry`, `no_citation_text`,
`grouped_citation_too_ambiguous`, `low_strength`, `no_body_anchor`, or another
concrete reason.

## Display Fields

The evidence page shows citing and cited paper titles, aspect, stance, mention
type, evidence strength, score, highlighted citation text, highlight keywords,
evidence reason, page/span metadata, third-party status, user note, corrected
label, and review buttons.

The page also displays evidence quality summary counts:

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

## Boundaries

- Tests and default local runs use `FakeLlmProvider`.
- Findings without original `citation_text` do not become `StrongEvidence`.
- Reference-only findings do not become `StrongEvidence`.
- Some grouped citations with explicit quote text and high-value evidence types
  may be saved as low/medium strength evidence with `anchor_status=grouped_citation`
  and `review_status=unreviewed`, so the user can review attribution manually.
- For `fulltext_direct`, the system may use a target reference marker such as
  `[15]` recovered from the References section to decide whether grouped body
  citations can be attributed to the cited paper group.
- Weak mentions remain weak by deterministic scoring and are not promoted.
- API keys, local PDF paths, and extracted text paths must not be rendered.
