# PDF Asset Pool And Local Library Data Model

The PDF asset pool is the canonical PDF model:

`pdf_assets` + `pdf_asset_publication_links`

Manual uploads, local-directory imports, and reused PDFs all create or reuse
`PdfAsset` rows. The local PDF library is only one import source; it is not a
separate runtime library.

## PdfAsset

`PdfAsset` stores metadata for a PDF file. It never stores PDF bytes.

| Field | Purpose |
| --- | --- |
| `storage_path` | Local filesystem path for uploaded or local-library PDFs |
| `original_filename` | User upload name or local-library filename |
| `mime_type` | Usually `application/pdf` |
| `size_bytes` | File size |
| `sha256` | File content digest used for reuse |
| `source_type` | `upload` for manual uploads, `local_library` for local matches |
| `source_url` | Original open-access PDF URL or source URL, when downloaded automatically |
| `license` | License/OA label if provided by metadata |
| `downloaded_at` | Timestamp for automatically downloaded PDFs |
| `extract_status` | Text extraction status |
| `extracted_text_path` | Local extracted text path, when available |

Manual uploads are never overwritten by local library matching.

## PdfAssetPublicationLink

`PdfAssetPublicationLink` binds a known PDF asset to a publication identity.
This makes uploaded PDFs reusable across new scholar sessions and queue items.

| Field | Purpose |
| --- | --- |
| `pdf_asset_id` | Linked `PdfAsset` |
| `publication_id` | Linked `Publication`, when known |
| `doi` | DOI copied from the publication identity, when known |
| `openalex_id` | OpenAlex work id copied from the publication identity, when known |
| `normalized_title` | Normalized title used for exact title reuse |
| `raw_title` | Original title seen during upload or matching |
| `match_method` | `manual_upload_for_queue_item`, `manual_attach_existing_pdf`, `local_library_scan`, etc. |
| `match_score` | Confidence score from `0.0` to `1.0` |
| `is_verified` | `true` when the user explicitly uploaded or attached the PDF for that publication |
| `created_at` / `updated_at` | Link timestamps |

Queue-item PDF upload creates a verified link with:

- `publication_id = DeepAnalysisQueueItem.citing_publication_id`
- `match_method = manual_upload_for_queue_item`
- `match_score = 1.0`
- `is_verified = true`

Reuse matching checks DOI, OpenAlex ID, publication id, normalized title, then
filename/title similarity. Exact DOI/OpenAlex/publication/title matches can be
auto-attached as `reused_pdf`; weaker filename matches are shown as candidates
for user confirmation.

## PdfLibraryIndex

Represents one local index rebuild attempt.

| Field | Purpose |
| --- | --- |
| `index_path` | Configured index metadata path |
| `source_dirs_json` | Configured source dirs used by this run |
| `entry_count` | Number of indexed PDF entries |
| `status` | `running`, `succeeded`, or `failed` |
| `started_at` / `finished_at` | Rebuild timestamps |
| `error_message` | Failure detail if rebuild failed |

## PdfLibraryEntry

Represents one `.pdf` file discovered in configured directories.

| Field | Purpose |
| --- | --- |
| `file_path` | Full path stored for worker use; do not display directly in UI/export |
| `filename` | Safe display name |
| `size_bytes` | File size |
| `sha256` | File content digest |
| `detected_doi` | DOI parsed from filename, when available |
| `detected_arxiv_id` | arXiv id parsed from filename, when available |
| `normalized_title` | Normalized title used for fuzzy matching |
| `title_candidates_json` | Filename-derived title candidates |
| `created_at` | Entry creation timestamp |

Phase 11.5 treats entries as the current index view. Rebuilding the same library
replaces older entry rows so duplicate rows for the same file do not accumulate.
Historical `PdfLibraryIndex` rows may remain as run metadata, but matching uses
the latest successful index.

## Session Links

- Ordinary paper sessions link matches through `CitingPaper.pdf_asset_id`.
- Scholar sessions link matches through `ScholarPublication.pdf_asset_id`.
- Scholar queue items link matches through `DeepAnalysisQueueItem.pdf_asset_id`.
- Cross-session reuse is driven by `PdfAssetPublicationLink`, not by copying PDF
  files or duplicating `PdfAsset` rows.

## Match Consistency

- Local-library `PdfAsset` rows are reused by `sha256`.
- `PdfAsset.sha256` matches the `PdfLibraryEntry.sha256` that produced it.
- Matching the same publication multiple times does not create duplicate
  `PdfAsset` rows.
- Manual upload assets are never overwritten by local-library matches.
- Reusing a PDF in another queue item sets `pdf_readiness_status = reused_pdf`.
