# Scholar Queue API

Phase 12 adds a scholar deep analysis queue. This phase only creates and manages
queue items. It does not run LLM analysis, generate `StrongEvidence`, create
highlight cards, download PDFs, or call real Scopus/Elsevier providers.
Phase 12.5 hardens queue repeatability, filters, review preservation, and path
redaction.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/scholar-sessions/{session_id}/build-queue` | Enqueue `build_scholar_queue` for a scholar session |
| `GET` | `/scholar-sessions/{session_id}/queue` | Show queue items with filter links |
| `POST` | `/scholar-sessions/{session_id}/queue/select` | Mark selected queue items as `selected` |
| `POST` | `/scholar-sessions/{session_id}/queue/skip` | Mark selected queue items as `skipped` |
| `POST` | `/scholar-sessions/{session_id}/queue/{item_id}/review` | Update `user_review_status` and `user_note` |
| `POST` | `/scholar-sessions/{session_id}/queue/{item_id}/upload-pdf` | Upload a citing paper PDF for a `DeepAnalysisQueueItem` |
| `POST` | `/scholar-sessions/{session_id}/queue/{item_id}/attach-existing-pdf` | Attach an existing global `PdfAsset` to a queue item |
| `POST` | `/scholar-sessions/{session_id}/queue/{item_id}/download-open-pdf` | Download a discovered open-access PDF candidate for one queue item |
| `POST` | `/scholar-sessions/{session_id}/queue/discover-pdfs` | Enqueue legal open-access PDF discovery/download for queue items |
| `GET` | `/scholar-sessions/{session_id}/exports/missing_pdfs_download_list.csv` | Download a CSV checklist for manually downloading missing citing-paper PDFs |

## Filters

The queue page supports `?view=` values:

- `all`
- `ready_only`
- `need_pdf`
- `third_party_only`
- `exclude_self_citation`
- `selected`
- `skipped`
- `important`

Phase 12.5 regression tests cover `ready_only`, `need_pdf`, `third_party_only`,
`exclude_self_citation`, `selected`, `skipped`, and `important`.

## Display Fields

Each queue item shows citing/cited paper titles, year, venue, venue tier,
third-party status, self-citation status, PDF readiness, priority score,
priority reasons, review status, and queue status.

The queue page also shows summary counts:

- `total queue items`
- `ready_count`
- `need_pdf_count`
- `selected_count`
- `analyzed_count`
- `important_count`

## Queue Item PDF Upload

`POST /scholar-sessions/{session_id}/queue/{item_id}/upload-pdf` accepts a
multipart form field named `file`.

Successful upload:

- validates the file through the shared PDF upload security checks;
- stores the PDF as a `PdfAsset`;
- extracts text through the existing PDF extraction flow;
- sets `DeepAnalysisQueueItem.pdf_asset_id` to the uploaded asset;
- sets `pdf_readiness_status` to `manual_pdf`;
- redirects back to `/scholar-sessions/{session_id}/queue`.

Error behavior:

- `404`: queue item does not exist in the scholar session.
- `409`: the item already has a `manual_pdf`; replacing is not supported in
  this phase.
- `400`: PDF validation fails.

Automatic PDF discovery is separate from upload. It only downloads open-access
or clearly authorized PDFs. Restricted publisher landing pages are marked
`requires_login` and remain a manual upload/bind workflow.

For restricted PDFs, the queue page displays DOI, publisher, Google Scholar,
and OpenAlex links plus copy buttons for the citing paper title and DOI. Users
download PDFs in their own browser and either upload them directly or place them
in the configured PDF inbox.

The queue page also shows per-item PDF download candidates. Each candidate
contains:

- `source_name`: a user-facing source label such as `ACM Digital Library`,
  `IEEE Xplore`, `arXiv`, `Semantic Scholar`, `OpenAlex OA`, `DOI`, or
  `Google Scholar`;
- `url`: a safe external URL for the source;
- `access_status`: `open_access`, `requires_login`, `search_only`, `unknown`,
  or `failed`;
- `can_auto_download`: whether the system may download the PDF without login;
- `reason`: a short diagnostic such as `open access pdf found`,
  `publisher page requires login`, or `search_fallback`.

If a DOI is known, the helper includes `https://doi.org/{doi}`. If no concrete
publisher URL is known, the helper still includes a Google Scholar search URL
for manual discovery. ACM/IEEE/Springer/Elsevier-style restricted candidates
are displayed as `requires_login` and must not be downloaded automatically.

`POST /scholar-sessions/{session_id}/queue/{item_id}/download-open-pdf` runs the
same legal PDF download checks as the batch discovery task. It is intended for
open-access candidates only; restricted publisher pages remain manual
download/upload or PDF inbox workflows.

## Existing PDF Reuse

`POST /scholar-sessions/{session_id}/queue/{item_id}/attach-existing-pdf`
accepts a form field named `pdf_asset_id`.

The route is used when the queue page finds a likely match from the global
`pdf_assets` pool or the local PDF library index. It validates that the queue
item belongs to the scholar session and that the asset exists, then links the
queue item to the existing `PdfAsset` without copying the PDF file.

Successful attachment:

- sets `DeepAnalysisQueueItem.pdf_asset_id` to the existing asset;
- sets `pdf_readiness_status` to `reused_pdf` for uploaded reusable assets or
  `local_library_pdf` for local library assets;
- rescoring records the PDF-ready priority reason;
- redirects back to `/scholar-sessions/{session_id}/queue`.

Error behavior:

- `404`: queue item is not part of the scholar session, or the `PdfAsset` does
  not exist.
- `409`: the item already has a manual uploaded PDF; replace is not supported
  in this phase.

The queue page only displays safe PDF metadata such as original filename,
source type, extraction status, match reason, and match score. It must not show
local absolute paths such as `storage_path` or `extracted_text_path`.

## Boundaries

Queue build reads existing `CitationEdge`, `Publication`, `PdfAsset`, and local
PDF index metadata. It may use Phase 11's local PDF matching service for a
single publication lookup, but it must not scan PDF directories or rebuild the
PDF index.

Queue pages must not expose full local absolute PDF paths. They display paper
metadata, statuses, scores, reasons, PDF filename, and source type only.
