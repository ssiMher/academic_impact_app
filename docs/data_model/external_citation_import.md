# External Citation Import Data Model

## `external_citation_import_batches`

One row represents one uploaded external citation CSV.

| Field | Meaning |
| --- | --- |
| `session_kind` | `scholar_analysis` or `paper_analysis` |
| `session_id` | Session receiving the imported citations |
| `source_name` | Source label such as `google_scholar` or `external_import` |
| `filename` | Uploaded CSV filename |
| `total_rows` | Parsed CSV row count |
| `imported_count` | New citations created |
| `matched_existing_count` | Rows matched to existing citations |
| `duplicate_count` | Duplicate rows skipped |
| `skipped_count` | Invalid or incomplete rows skipped |
| `error_count` | Rows that raised import errors |

## `external_citation_import_rows`

Each row stores row-level import diagnostics.

| Field | Meaning |
| --- | --- |
| `batch_id` | Parent import batch |
| `row_index` | 1-based CSV row index |
| `raw_row_json` | Raw CSV row JSON |
| `parsed_title` | Parsed citing paper title |
| `parsed_doi` | Parsed DOI |
| `parsed_year` | Parsed year |
| `parsed_venue` | Parsed venue/source |
| `match_status` | `imported`, `matched_existing`, `skipped`, or `error` |
| `match_reason` | Deduplication or failure reason |
| `citation_edge_id` | Created or matched scholar citation edge, when applicable |
| `error_message` | Safe row-level error message |

The importer does not store Google Scholar credentials, browser cookies, or
session tokens.
