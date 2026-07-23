# PDF Discovery And Legal Download

PDF discovery is limited to open-access or otherwise clearly authorized PDFs.
The system does not save publisher credentials, browser cookies, or session
tokens, and it does not bypass paywalls.

## Queue Item Status

`DeepAnalysisQueueItem` records discovery diagnostics:

- `pdf_discovery_status`: `not_started`, `found_open_access_pdf`, `downloaded`,
  `requires_login`, `requires_manual_upload`, `failed`, or `no_pdf_found`.
- `pdf_source`: source label such as `arxiv`, `openalex_oa`,
  `publisher_landing_page`, `local_library`, or `user_upload`.
- `pdf_source_url`: open-access PDF URL or publisher landing-page URL.
- `pdf_access_status`: `open_access_downloaded`, `open_access_available`,
  `requires_login`, `manual_download_needed`, `manual_download_imported`,
  `matched_from_inbox`, `no_pdf_found`, or `failed`.

## Download Rules

The system may automatically download arXiv PDFs and metadata-provided
open-access PDF URLs. It rejects HTML login pages, non-PDF responses, oversized
files, and candidates marked as requiring login.

For ACM, IEEE, Springer, Elsevier, or other restricted publisher landing pages,
the queue item is marked `requires_login`. The UI tells users to open the
official page, use their own authorized access, and upload the downloaded PDF
manually.

## Browser-Assisted Restricted PDF Flow

For restricted PDFs, the queue page shows a download helper with DOI,
publisher, Google Scholar search, and OpenAlex links. The user downloads the PDF
in their own browser using personal or institutional access, then places it in
`ACADEMIC_IMPACT_PDF_INBOX_DIR`.

`/pdf-inbox` scans this directory, creates or reuses `PdfAsset` rows, extracts
text, detects DOI/title candidates, and matches PDFs to scholar queue items.
High-confidence DOI/title matches are bound automatically. Medium-confidence
matches are shown for manual confirmation. Low-confidence files remain
unmatched.

The system does not request, store, or replay publisher usernames, passwords,
cookies, or session tokens.

## Tasks

`discover_pdfs_for_queue` and `download_open_access_pdfs` use the same handler.
The task summary reports `total_items`, `found_open_access`, `downloaded`,
`requires_login`, `manual_upload_required`, `failed`, and
`skipped_existing_pdf`.
