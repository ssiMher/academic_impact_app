# Health Checks

Routes:

- `GET /health`
- `GET /health.json`
- `GET /providers/health`

`/health` returns the minimal app status. `/health.json` preserves the existing
`llm_provider` field and also includes all provider status under `providers`.
`/providers/health` returns author, citation, metadata, and LLM provider status.

Health responses show:

- Configured provider name.
- Normalized provider implementation name.
- Whether configuration appears complete.
- Recent error message when known.

Health responses never show API keys. LLM health only reports
`api_key_configured`.

