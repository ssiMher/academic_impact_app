# OpenAlex Provider

`OpenAlexProvider` supports citation and metadata provider contracts.

## Capabilities

- `health_check()`
- `resolve_paper(paper_ref)`
- `resolve_publication(query)`
- `enrich_publication(ref)`
- `list_citing_papers(publication, limit)`
- `discover_citations(target_title)`

The provider accepts DOI, OpenAlex work id, OpenAlex work URL, or title search
input, then maps OpenAlex work payloads into `ProviderPublication`.

## Citation Expansion

Citation expansion uses OpenAlex work ids and returns normalized
`ProviderCitationEdge` objects. Citing paper raw fields are mapped before they
reach task handlers or services.

## Error Mapping

- HTTP 429 -> `rate_limit`
- timeout -> `timeout`
- 404 -> `not_found`
- invalid JSON or unexpected shape -> `provider_schema_error`
- 5xx -> `transient_provider_error`

Tests use mocked HTTP responses and do not access OpenAlex.

