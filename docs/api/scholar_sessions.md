# Scholar Sessions API

Phase 10 adds a minimum scholar analysis flow. Phase 10.5 hardens that flow with
integration coverage, idempotent citation expansion, and clearer error handling.
It uses `FakeAuthorProvider` and
`FakeCitationProvider` only; no route calls DBLP, OpenAlex, Scopus, or any real
network provider.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/scholar-sessions/new` | Show the scholar analysis creation form |
| `POST` | `/scholar-sessions` | Create a `ScholarAnalysisSession` and redirect to detail |
| `GET` | `/scholar-sessions/{session_id}` | Show scholar session metadata, fake publications, recent tasks, and citation edge count |
| `POST` | `/scholar-sessions/{session_id}/expand-and-build-queue` | Enqueue a combined task that expands citations first, then builds the deep analysis queue |
| `POST` | `/scholar-sessions/{session_id}/expand-citations` | Enqueue an `expand_scholar_citations` task for selected publications |

Missing scholar sessions return `404`.

## Form Fields

`POST /scholar-sessions`

| Field | Required | Notes |
| --- | --- | --- |
| `author_ref` | Yes | Author name or provider identifier. Phase 10 resolves it with the fake author provider. |

`POST /scholar-sessions/{session_id}/expand-citations`

`POST /scholar-sessions/{session_id}/expand-and-build-queue`

| Field | Required | Notes |
| --- | --- | --- |
| `publication_ids` | Yes | One or more `ScholarPublication.id` values selected on the detail page. |

If no `publication_ids` are submitted, the route returns `400` with a clear
message. If selected publication ids do not belong to the session, the route
also returns `400`.

## Task Behavior

The default user path is the combined route:

1. expand citations
2. if citation edges exist, build the deep analysis queue
3. if no citation edges are expanded, finish with a clear message that the queue
   cannot be built

The original routes remain available for debugging:

- `expand_scholar_citations`
- `build_scholar_queue`

The expand route only enqueues work. It does not execute the long-running
operation in the request cycle. `TaskRunner.run_once()` claims the pending task,
uses the fake citation provider, writes `Publication` and `CitationEdge` rows,
and updates `ScholarAnalysisSession.citation_edge_count`.

The combined task records stage messages for:

- `阶段 1：扩展引用`
- `阶段 2：构建队列`
- expanded citation edge count
- generated queue item count
- provider name
- whether PDF was auto-reused during queue construction

Task behavior is idempotent for the same selected publications:

- Citing `Publication` rows are reused by DOI when available, then by
  normalized title and year.
- `CitationEdge` rows are reused by
  `scholar_session_id + cited_publication_id + citing_publication_id`.
- Retrying or re-enqueueing expansion for the same selected publications does
  not increase `citation_edge_count`.
- If citation expansion raises an exception, `TaskRunner` marks the task
  `failed` and stores `error_message`.

If the fake author provider returns no publications, the session is still
created with `publication_count=0`, `citation_edge_count=0`, and
`status=no_publications`; the detail page remains safe to render.

## Phase 10 Boundaries

- No real DBLP, OpenAlex, Scopus, or Semantic Scholar calls.
- No scholar fulltext analysis or strong evidence dashboard.
- No highlight cards.
- No automatic PDF download.
- No complex author disambiguation or `person_candidates`.
