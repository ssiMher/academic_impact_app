# OpenAI-Compatible LLM Provider

The OpenAI-compatible provider uses `/chat/completions` and validates output
against `CitationAnalysisResponse`.

## Configuration

- `ACADEMIC_IMPACT_LLM_PROVIDER=openai_compatible`
- `ACADEMIC_IMPACT_LLM_BASE_URL`
- `ACADEMIC_IMPACT_LLM_API_KEY`
- `ACADEMIC_IMPACT_LLM_MODEL`
- `ACADEMIC_IMPACT_LLM_TIMEOUT_SECONDS`
- `ACADEMIC_IMPACT_LLM_DISABLE_THINKING`

## Parsing

The provider supports:

- Plain JSON.
- Fenced JSON.
- Embedded JSON in otherwise non-JSON text.

Invalid JSON or schema mismatch maps to `provider_schema_error`.

## Security

The API key is sent only in the Authorization header. Health responses and
ProviderRequestLog expose only `api_key_configured` or `[REDACTED]`.

