# Scholar Analysis Data Model

Phase 10 introduces the minimum tables required to create a scholar analysis
session, list fake publications, and expand citation edges for selected
publications. Phase 10.5 adds consistency rules for idempotent expansion and
safe empty-result handling.

## ScholarAnalysisSession

Represents one scholar analysis run.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `display_name` | Resolved scholar display name |
| `dblp_id` | Optional normalized DBLP author id from provider data |
| `openalex_id` | Optional OpenAlex author id |
| `scopus_author_id` | Optional Scopus author id |
| `status` | Session status, initially `created`; `no_publications` when the provider returns no publications; `expanded` after citation expansion succeeds |
| `publication_count` | Number of publications saved for this session |
| `citation_edge_count` | Number of citation edges generated for this session |
| `created_at` / `updated_at` | Local timestamps |

## ScholarPublication

Stores a publication associated with the scholar session while preserving a link
to the shared `Publication` table.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `scholar_session_id` | Parent `ScholarAnalysisSession` |
| `publication_id` | Linked shared `Publication` row |
| `local_code` | Human-readable local code such as `S001` |
| `title`, `year`, `venue`, `doi` | Display metadata copied from provider-normalized data |
| `selected_for_expansion` | Whether this publication should be expanded by the citation task |
| `pdf_asset_id` | Optional local or uploaded PDF asset matched for this scholar publication |

## CitationEdge

Represents a citing-to-cited relationship discovered during scholar citation
expansion.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `scholar_session_id` | Parent `ScholarAnalysisSession` |
| `cited_publication_id` | The scholar publication being cited |
| `citing_publication_id` | The citing publication discovered by the provider |
| `provider_name` | Normalized provider name, `fake` in Phase 10 |
| `self_citation_status` | MVP status, initially `unknown` |
| `third_party_status` | MVP status, initially `third_party` |
| `edge_meta_json` | Small provider-normalized metadata, not raw provider payloads |
| `created_at` | Local timestamp |

## Storage Boundaries

- PDF binaries and extracted text remain in filesystem storage, not these tables.
- API keys and provider secrets are never stored.
- Phase 10 does not store fulltext evidence or scholar dashboard cards.

## Consistency Rules

- `ScholarPublication.local_code` is stable within a session and assigned as
  `S001`, `S002`, and so on in provider publication order.
- `ScholarAnalysisSession.publication_count` equals the number of
  `ScholarPublication` rows in that session.
- Citing `Publication` rows are reused during expansion by DOI, or by
  normalized title plus year when DOI is absent.
- `CitationEdge` rows are unique at the application layer for
  `scholar_session_id + cited_publication_id + citing_publication_id`.
- `ScholarAnalysisSession.citation_edge_count` is recalculated from actual
  `CitationEdge` rows after expansion, so task retry does not inflate counts.
