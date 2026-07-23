# Scholar Tasks

This document covers local scholar tasks. The current implementation does not
introduce Redis, Celery, real scholarly providers, automatic PDF download,
strong evidence dashboards, final scholar reports, or highlight cards.

## expand_scholar_citations

`expand_scholar_citations` is enqueued by
`POST /scholar-sessions/{session_id}/expand-citations` after the user selects
one or more `ScholarPublication` rows.

Execution flow:

1. `TaskRunner.claim_next_task()` marks the pending task as `running`.
2. The handler validates that the task belongs to a `scholar_analysis` session.
3. The handler reads selected `ScholarPublication` rows.
4. `FakeCitationProvider` returns normalized `ProviderCitationEdge` objects.
5. The repository reuses or creates citing `Publication` rows.
6. The repository reuses or creates `CitationEdge` rows.
7. The handler updates task progress and recalculates
   `ScholarAnalysisSession.citation_edge_count` from stored edges.

## Idempotency

The task is safe to retry for the same selected publications:

- Existing citing publications are reused by DOI or normalized title plus year.
- Existing citation edges are reused by session, cited publication, and citing
  publication.
- Retrying the task does not duplicate `Publication` rows for the same citing
  papers.
- Retrying the task does not duplicate `CitationEdge` rows or inflate
  `citation_edge_count`.

## Failure Handling

If the handler raises an exception, `TaskRunner` rolls back the in-flight
transaction, marks the task `failed`, and stores the error text in
`AnalysisTask.error_message`.

## Provider Boundary

Phase 10.5 still uses fake providers only. Services do not call `requests`,
`httpx`, `urllib`, or other HTTP clients. Provider output enters the database
only after conversion into normalized provider schemas.

## build_scholar_queue

`build_scholar_queue` is enqueued by
`POST /scholar-sessions/{session_id}/build-queue`.

Execution flow:

1. The handler validates that the task belongs to a `scholar_analysis` session.
2. It reads existing `CitationEdge` rows for the session.
3. For each edge, `ScholarQueueService` upserts one `DeepAnalysisQueueItem`.
4. It derives PDF readiness from existing `PdfAsset` links or Phase 11 local
   PDF index matching.
5. It calculates explainable `priority_score` and `priority_reasons_json`.

Boundaries:

- No LLM analysis.
- No `StrongEvidence` generation.
- No highlight cards.
- No PDF directory scanning or index rebuild.
- No overwrite of user review status or notes during rebuild.

## expand_and_build_scholar_queue

`expand_and_build_scholar_queue` is enqueued by
`POST /scholar-sessions/{session_id}/expand-and-build-queue`.

Execution flow:

1. Read selected `ScholarPublication` rows.
2. Run the same expansion logic as `expand_scholar_citations`.
3. If expanded citation edge count is greater than zero, run the same queue
   build logic as `build_scholar_queue`.
4. If expanded citation edge count is zero, finish with a clear message that
   the queue could not be built.

This is the default user-facing workflow because it avoids a common dead-end:
expanding citations successfully but opening an empty queue because queue build
was never triggered.

The task keeps the original task boundaries internally. It does not delete or
replace `expand_scholar_citations` or `build_scholar_queue`.

## analyze_scholar_queue

`analyze_scholar_queue` is enqueued by
`POST /scholar-sessions/{session_id}/queue/analyze`.

Execution flow:

1. The handler validates that the task belongs to a `scholar_analysis` session.
2. It reads selected `DeepAnalysisQueueItem` rows for the session.
3. Items with `manual_pdf` or `local_library_pdf` are analyzed with the selected
   `analysis_scope`.
   `candidate_spans` uses the Phase 6 candidate span pipeline.
   `fulltext_direct` sends the full extracted text to the LLM when the text is
   within `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`.
4. Items with `need_pdf` are skipped with a warning.
5. Each successful item creates a `FulltextAnalysisResult`.
6. Eligible findings with original `citation_text` are upserted as
   `StrongEvidence`.
7. Task progress records processed item count.

Failure handling:

- One item failure does not abort the full batch.
- If at least one item succeeds or is skipped, the task can finish as
  `succeeded` with warnings.
- If selected ready items all fail due to errors, the task is marked `failed`.

Task summary:

- `total_queue_items`
- `selected_items`
- `ready_items`
- `skipped_need_pdf_count`
- `skipped_not_selected_count`
- `analyzed_count`
- `fulltext_result_count`
- `strong_evidence_count`
- `failed_item_count`
- `analysis_scope`
- `fulltext_chars`
- `llm_findings_count`
- `warnings`

These fields are included in `stage_message` for warning cases and in
`error_message` when all selected ready items fail, so a task does not look
successful when no `FulltextAnalysisResult` or `StrongEvidence` was written.

Boundaries:

- Uses fake LLM by default in tests and local development.
- Does not generate highlight cards or final scholar reports.
- Does not auto-download PDFs or scan the local PDF library.
- Does not overwrite existing evidence review status or user notes.
