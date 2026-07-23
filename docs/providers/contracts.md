# Provider Contracts

Phase 16 keeps provider outputs behind normalized schemas:

- `ProviderAuthorIdentity`
- `ProviderPublication`
- `ProviderCitationEdge`
- `ProviderHealth`
- `ProviderError`

Services consume these schemas only. Provider raw API fields must not leak into
services, templates, reports, or database export payloads.

## Selection

Provider factories read environment configuration:

- `ACADEMIC_IMPACT_AUTHOR_PROVIDER=fake|dblp`
- `ACADEMIC_IMPACT_CITATION_PROVIDER=fake|openalex`
- `ACADEMIC_IMPACT_METADATA_PROVIDER=fake|openalex`
- `ACADEMIC_IMPACT_LLM_PROVIDER=fake|openai_compatible`

Defaults remain fake so the local test and development flow is offline by
default.

## Errors

Providers raise `ProviderException` with `ProviderErrorCode`.

Common mappings:

- `timeout` for socket timeouts.
- `rate_limit` for HTTP 429.
- `auth_error` for LLM HTTP 401/403.
- `not_found` for DBLP/OpenAlex 404 or missing author/paper.
- `provider_schema_error` for invalid provider payloads.
- `transient_network_error` or `transient_provider_error` for retryable network
  or upstream failures.

## Security

ProviderRequestLog stores only redacted request payloads. API keys and sensitive
headers must not be written to logs, database rows, templates, reports, or
exports.

