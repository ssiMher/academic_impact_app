# PDF Inbox Entry Data Model

`PdfInboxEntry` records PDFs found in the browser-assisted manual download
inbox.

| Field | Meaning |
| --- | --- |
| `filename` | Original inbox filename |
| `file_path` | Worker-readable local path; do not show absolute paths in UI/export |
| `size_bytes` | File size |
| `sha256` | Content hash for duplicate detection |
| `pdf_asset_id` | Linked `PdfAsset` in the global asset pool |
| `detected_title` | Title candidate from filename or extracted text |
| `detected_doi` | DOI candidate from filename or extracted text |
| `page_count` | Reserved page-count diagnostic |
| `match_status` | `matched`, `candidate`, `unmatched`, or `ignored` |
| `match_reason` | `doi_exact`, `fuzzy_title`, `manual_confirmed`, etc. |
| `matched_queue_item_id` | Matched scholar queue item, when known |
| `match_score` | Matching confidence |
| `ignored` | Whether the user ignored the inbox PDF |

Binding an inbox entry sets the queue item `pdf_asset_id`,
`pdf_readiness_status=manual_pdf`, and `pdf_access_status=matched_from_inbox`.
