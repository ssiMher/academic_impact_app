# PDF Library API

The PDF library page exposes the unified PDF asset pool plus local scan-source
status. Routes do not accept scan paths from users.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/pdf-library` | Show the PDF asset pool, local library enabled/disabled status, latest index summary, redacted source dirs, entries, and recent error |
| `GET` | `/pdf-library.json` | Return the same status as JSON with redacted paths and asset-pool summary |
| `POST` | `/pdf-library/rebuild` | Enqueue `rebuild_pdf_index`; does not scan in the request thread |
| `POST` | `/paper-sessions/{session_id}/match-local-pdfs` | Enqueue `match_session_pdfs` for an ordinary paper session |
| `POST` | `/scholar-sessions/{session_id}/match-local-pdfs` | Enqueue `match_session_pdfs` for a scholar session |

## Responses

`GET /pdf-library` renders HTML. It shows:

- PDF asset pool totals.
- Uploaded/imported assets with safe filenames only.
- Linked DOI/OpenAlex/title metadata.
- Queue reuse count.
- Whether the local library is enabled.
- Latest successful `entry_count`.
- Redacted source directory names.
- Recent error, if any.
- Indexed filenames and detected DOI/arXiv ids.

The page must not expose absolute local paths.
The JSON endpoint follows the same rule: it includes filenames and redacted
source directory names, not `file_path`, `index_path`, or configured absolute
directory values.

The `asset_pool` object includes only safe display metadata:

- `asset_count`
- `extracted_count`
- `linked_publication_count`
- `queue_reuse_count`
- `recent_assets[].original_filename`
- `recent_assets[].source_type`
- `recent_assets[].extract_status`
- `recent_assets[].doi`
- `recent_assets[].openalex_id`
- `recent_assets[].raw_title`
- `recent_assets[].queue_usage_count`

It must not include `storage_path`, `extracted_text_path`, API keys, request
headers, or provider secrets.

## Disabled State

If `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS` is empty, `GET /pdf-library` still returns
`200` and displays `local library disabled`. `POST /pdf-library/rebuild` returns
`400`.

## Task Boundary

Rebuild and session matching are task-driven. FastAPI routes enqueue tasks only;
workers execute scanning and matching through `TaskRunner`.

Repeated rebuilds are safe: successful rebuilds replace the current library
entry view instead of accumulating duplicate `PdfLibraryEntry` rows for the same
file. Scanned PDFs are also imported into the PDF asset pool by SHA-256, so the
same file does not create duplicate `PdfAsset` rows.
