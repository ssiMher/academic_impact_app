# API and Web Routes

This document tracks the currently supported HTTP routes. The current system supports ordinary paper analysis session creation, a local task MVP, local PDF upload/extraction, local PDF library matching, citation evidence analysis for citing papers, downloadable paper-session exports, scholar analysis, template-guided evidence, and configurable providers. Defaults remain fake/offline. DBLP, OpenAlex, and OpenAI-compatible providers are available only when explicitly configured. The system still does not auto-download PDFs or access Scopus/Elsevier.

## Health

| Method | Path | Purpose | Response |
| --- | --- | --- | --- |
| GET | `/health` | Health check | JSON `{"status": "ok"}` |
| GET | `/health.json` | Extended health check | JSON with `status`, redacted LLM provider configuration status, and all provider statuses |
| GET | `/providers/health` | Provider health check | JSON with author, citation, metadata, and LLM provider status without API keys |

## Pages

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Home page with entry to create an ordinary paper analysis session |
| GET | `/paper-sessions/new` | Show the ordinary paper analysis session creation form |
| POST | `/paper-sessions` | Create a `PaperAnalysisSession` with status `created`, then redirect to detail |
| GET | `/paper-sessions/{session_id}` | Show session detail, including query text, query kind, and status |
| POST | `/paper-sessions/{session_id}/discover` | Enqueue a local `discover_paper` task, then redirect to detail |
| GET | `/citing-papers/{citing_paper_id}` | Show citing paper PDF upload form, PDF status, and generated strong evidence |
| POST | `/citing-papers/{citing_paper_id}/pdf` | Upload a local PDF, create `PdfAsset`, extract text, then redirect to citing paper detail |
| POST | `/citing-papers/{citing_paper_id}/analyze` | Enqueue local `analyze_citation` task when PDF text is ready, then redirect to citing paper detail |
| GET | `/pdf-library` | Show local PDF library status and redacted latest index summary |
| GET | `/pdf-library.json` | Return local PDF library status as JSON without absolute local paths |
| POST | `/pdf-library/rebuild` | Enqueue local PDF library index rebuild |
| POST | `/paper-sessions/{session_id}/match-local-pdfs` | Enqueue local PDF matching for a paper session |
| GET | `/scholar-sessions/new` | Show the scholar analysis session creation form |
| POST | `/scholar-sessions` | Create a fake-provider `ScholarAnalysisSession`, then redirect to detail |
| GET | `/scholar-sessions/{session_id}` | Show scholar metadata, fake publications, recent tasks, and citation edge count |
| POST | `/scholar-sessions/{session_id}/expand-citations` | Enqueue local `expand_scholar_citations` task for selected publications |
| POST | `/scholar-sessions/{session_id}/match-local-pdfs` | Enqueue local PDF matching for a scholar session |
| POST | `/scholar-sessions/{session_id}/build-queue` | Enqueue scholar deep analysis queue build |
| GET | `/scholar-sessions/{session_id}/queue` | Show scholar queue with filters |
| POST | `/scholar-sessions/{session_id}/queue/select` | Mark queue items selected |
| POST | `/scholar-sessions/{session_id}/queue/skip` | Mark queue items skipped |
| POST | `/scholar-sessions/{session_id}/queue/{item_id}/review` | Update queue item review status and note |
| POST | `/scholar-sessions/{session_id}/queue/analyze` | Enqueue scholar queue full-text analysis for selected items |
| GET | `/scholar-sessions/{session_id}/evidence` | Show scholar strong evidence with filters |
| POST | `/scholar-sessions/{session_id}/evidence/{evidence_id}/review` | Update scholar evidence review status and note |

## Export API

See `docs/api/exports.md` for field-level export details and safety boundaries.

| Method | Path | Purpose | Response |
| --- | --- | --- | --- |
| GET | `/paper-sessions/{session_id}/exports/report.md` | Generate and download a Markdown report for the paper session | `report.md` attachment |
| GET | `/paper-sessions/{session_id}/exports/structured.json` | Generate and download structured export data for the paper session | `structured.json` attachment |

## Task API

| Method | Path | Purpose | Response |
| --- | --- | --- | --- |
| GET | `/api/v1/tasks/{task_id}` | Return local task status | JSON with task id, session, type, status, stage, progress, and error fields |

## Current Boundaries

- Routers call services and do not directly read or write the database.
- Services do not call external APIs.
- FastAPI requests enqueue local tasks but do not execute long-running work inline.
- `discover_paper` uses the configured citation provider. The default is `FakeCitationProvider`; `OpenAlexProvider` is available when configured.
- Scholar analysis uses the configured author and citation providers. Defaults are `FakeAuthorProvider` and `FakeCitationProvider`; DBLP author lookup and OpenAlex citation expansion are available when configured.
- PDF upload only accepts user-provided `.pdf` files that pass size and magic-byte checks.
- PDF bytes are stored on disk under `var/pdf_assets/`; only metadata and paths are stored in SQLite.
- Extracted text is stored on disk under `var/extracted_text/`.
- Exported files are written under `var/exports/`.
- Local PDF library scanning is disabled unless `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS` is configured.
- Local PDF library routes enqueue tasks; they do not scan configured directories in request handlers.
- Local PDF library pages show filenames and redacted directory names, not full absolute paths.
- Scholar queue build uses existing citation edges and local PDF index metadata; it does not run LLM analysis, generate `StrongEvidence`, or scan PDF directories.
- `analyze_citation` uses the configured LLM provider. The default provider is `FakeLlmProvider`.
- `OpenAICompatibleLlmProvider` may call a configured chat/completions endpoint, but automated tests must mock HTTP and never access real LLM services.
- Provider health responses never expose API keys; they only show whether a key is configured.
- Health responses never expose `ACADEMIC_IMPACT_LLM_API_KEY`; they only show whether a key is configured.
- Findings without original `citation_text` are not converted into `StrongEvidence`.
- Grouped citations are scored weakly and are not promoted as strong evidence.
- Citing paper pages show `need_pdf`, `need_extracted_text`, or `ready` before allowing analysis enqueue.
- Export routes read existing `PaperAnalysisSession`, `CitingPaper`, `FulltextAnalysisResult`, and `StrongEvidence` rows; they do not call LLM providers, re-run PDF extraction, or expose local PDF/text storage paths.
- The current flow does not auto-download PDFs.
