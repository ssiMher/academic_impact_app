# Deep Analysis Queue Data Model

`DeepAnalysisQueueItem` represents one candidate citing paper to consider for a
future scholar deep analysis step. Phase 12 stops at queue generation and manual
queue review.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `scholar_session_id` | Parent `ScholarAnalysisSession` |
| `citation_edge_id` | Source `CitationEdge`; one queue item per edge |
| `cited_publication_id` | Publication being cited |
| `citing_publication_id` | Citing publication to potentially analyze |
| `queue_status` | `pending`, `selected`, `skipped`, `analyzed`, or `failed` |
| `priority_score` | Explainable local priority score |
| `priority_reasons_json` | List of `{reason, delta}` scoring reasons |
| `third_party_status` | `third_party`, `not_third_party`, or `ambiguous` |
| `self_citation_status` | `not_self_citation`, `possible_self_citation`, `self_citation`, or `unknown` |
| `pdf_readiness_status` | `manual_pdf`, `reused_pdf`, `local_library_pdf`, `need_pdf`, or `unavailable` |
| `pdf_asset_id` | Matched `PdfAsset`, if available |
| `pdf_discovery_status` | Legal PDF discovery/download status such as `not_started`, `downloaded`, `requires_login`, `failed`, or `no_pdf_found` |
| `pdf_access_status` | Access workflow status such as `open_access_downloaded`, `requires_login`, `manual_download_needed`, `matched_from_inbox`, or `failed` |
| `pdf_source` | Source label such as `arxiv`, `openalex_oa`, `publisher_landing_page`, `local_library`, or `user_upload` |
| `pdf_source_url` | Open-access PDF URL or publisher landing-page URL; do not display local storage paths |
| `publisher_landing_url`, `doi_url`, `openalex_url`, `google_scholar_query_url` | Safe helper links for manual browser-assisted download |
| `publisher_name`, `requires_login_reason` | Restricted-access diagnostics shown to users |
| `venue`, `venue_tier` | Venue metadata used for sorting and scoring |
| `citing_paper_title`, `cited_paper_title` | Denormalized display titles |
| `citing_authors_json`, `cited_authors_json` | Denormalized author lists |
| `year` | Citing paper year |
| `provider_name` | Provider that created the citation edge |
| `user_review_status` | `unreviewed`, `accepted`, `rejected`, `important`, or `needs_discussion` |
| `user_note` | Human reviewer note |
| `created_at`, `updated_at` | Local timestamps |

## Idempotency

Queue build is an upsert by `citation_edge_id`. Rebuilding a queue updates
derived fields such as score, PDF readiness, and venue metadata, but preserves
`queue_status`, `user_review_status`, and `user_note`.

Phase 12.5 explicitly verifies:

- One `CitationEdge` creates at most one queue item.
- Repeated build/rebuild does not create duplicate queue items.
- Queue item count remains aligned with session citation edge count when every
  edge has valid publication metadata.

## PDF Readiness

Manual uploads take priority over local-library matches. If no existing asset is
found, the queue builder may query the latest local PDF index through the Phase
11 service, but it does not scan directories.

Readiness states:

- `manual_pdf`: PDF uploaded directly for the current queue item, highest priority.
- `reused_pdf`: existing user-uploaded `PdfAsset` reused from the global PDF
  asset pool for this queue item.
- `local_library_pdf`: match from the Phase 11 local PDF index.
- `need_pdf`: no PDF asset available.
- `unavailable`: reserved for unsupported asset state.

## From `need_pdf` To Ready

A queue item becomes analyzable when `pdf_readiness_status` is `manual_pdf`,
`reused_pdf`, or `local_library_pdf`.

`need_pdf` can become ready in two ways:

- User uploads a citing paper PDF from the scholar queue page. The system
  creates a `PdfAsset`, extracts text, links it through `pdf_asset_id`, and sets
  `pdf_readiness_status = manual_pdf`.
- The queue page finds a high-confidence match in the global `pdf_assets` pool,
  links the existing asset through `pdf_asset_id`, and sets
  `pdf_readiness_status = reused_pdf`.
- The queue page finds a medium-confidence existing asset match and lets the
  user confirm it with `attach-existing-pdf`.
- The Phase 11 local PDF library has already matched the citing publication.
  The queue item links that asset and sets `pdf_readiness_status =
  local_library_pdf`.
- The user downloads a restricted PDF in their own browser, puts it in the PDF
  inbox, and `/pdf-inbox` binds the resulting `PdfAsset`. The queue item sets
  `pdf_access_status = matched_from_inbox`.

`manual_pdf` means the user explicitly supplied the PDF for this analysis item.
`reused_pdf` means the asset was previously uploaded and is now reused without
copying the file. `local_library_pdf` means the asset came from an indexed,
configured local PDF library. Manual uploads are never overwritten by reusable
asset matching or local-library matching.

Full-text analysis requires a ready PDF because `StrongEvidence` must be grounded
in extracted original citation text. Without a PDF and extracted text, the system
must not ask the LLM to infer evidence or create unsupported findings.
