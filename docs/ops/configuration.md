# Configuration

Phase 16 provider settings:

```env
ACADEMIC_IMPACT_APP_NAME=Academic Impact App
ACADEMIC_IMPACT_APP_ENV=development
ACADEMIC_IMPACT_LOG_LEVEL=INFO
ACADEMIC_IMPACT_DATABASE_URL=sqlite:///var/academic_impact_app.db
ACADEMIC_IMPACT_PDF_ASSET_DIR=var/pdf_assets
ACADEMIC_IMPACT_EXTRACTED_TEXT_DIR=var/extracted_text
ACADEMIC_IMPACT_EXPORT_DIR=var/exports
ACADEMIC_IMPACT_PDF_MAX_UPLOAD_BYTES=104857600
ACADEMIC_IMPACT_PDF_INBOX_DIR=./var/pdf_inbox
ACADEMIC_IMPACT_PDF_INBOX_AUTO_SCAN=true
ACADEMIC_IMPACT_PDF_INBOX_MATCH_THRESHOLD=0.82
ACADEMIC_IMPACT_AUTHOR_PROVIDER=fake
ACADEMIC_IMPACT_CITATION_PROVIDER=fake
ACADEMIC_IMPACT_METADATA_PROVIDER=fake
ACADEMIC_IMPACT_PROVIDER_TIMEOUT_SECONDS=20
ACADEMIC_IMPACT_PROVIDER_CACHE_ENABLED=true
ACADEMIC_IMPACT_LLM_PROVIDER=fake
ACADEMIC_IMPACT_LLM_BASE_URL=
ACADEMIC_IMPACT_LLM_API_KEY=
ACADEMIC_IMPACT_LLM_MODEL=gpt-4.1-mini
ACADEMIC_IMPACT_LLM_TIMEOUT_SECONDS=30
ACADEMIC_IMPACT_LLM_DISABLE_THINKING=true
ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS=120000
ACADEMIC_IMPACT_DEBUG_SAVE_LLM_PROMPTS=false
ACADEMIC_IMPACT_DEBUG_LLM_DIR=./var/debug/llm_prompts
```

At startup, `app/core/config.py` loads project-root `.env` with
`override=False` semantics. Shell environment variables take precedence over
`.env`. `.env.example` is documentation only and is never loaded as runtime
configuration.

Defaults keep all automated flows offline. To manually test real metadata and
citations, set:

```env
ACADEMIC_IMPACT_AUTHOR_PROVIDER=dblp
ACADEMIC_IMPACT_CITATION_PROVIDER=openalex
ACADEMIC_IMPACT_METADATA_PROVIDER=openalex
```

To manually test a real OpenAI-compatible LLM, set:

```env
ACADEMIC_IMPACT_LLM_PROVIDER=openai_compatible
ACADEMIC_IMPACT_LLM_BASE_URL=https://your-provider.example/v1
ACADEMIC_IMPACT_LLM_API_KEY=...
ACADEMIC_IMPACT_LLM_MODEL=...
```

Do not commit API keys, personal paths, or provider secrets.

## LLM Debug Artifacts

When `ACADEMIC_IMPACT_DEBUG_SAVE_LLM_PROMPTS=true`, each scholar full-text
analysis result may save:

- `prompt.txt`
- `raw_response.txt`
- `normalized_response.json`
- `metadata.json`

under `ACADEMIC_IMPACT_DEBUG_LLM_DIR/result_<fulltext_result_id>/`.

This is intended for local debugging only and is disabled by default. The saved
artifacts must not include API keys, authorization headers, provider secrets,
or local absolute paths in page output.

## Fulltext Direct Analysis Limit

`ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS` controls the maximum extracted-text
length allowed for `analysis_scope=fulltext_direct`. If the extracted text is
longer than this value, the task records
`fulltext_too_long_for_direct_analysis` and does not silently truncate the
paper. Chunked full-text analysis is intentionally not implemented yet.

## SQLite Schema Upgrade

Local SQLite databases are upgraded during application startup through
`init_db()`. The startup path creates missing tables and then runs
`upgrade_sqlite_schema(...)` for known column additions.

The upgrader:

- only runs for SQLite;
- checks existing columns with `PRAGMA table_info`;
- adds missing columns with `ALTER TABLE ... ADD COLUMN`;
- rebuilds only `fulltext_analysis_results` when an old SQLite table has
  `citing_paper_id NOT NULL`, because scholar queue analysis now needs that
  column nullable;
- is safe to run repeatedly;
- does not delete `var/academic_impact_app.db`;
- does not drop unrelated tables or clear data.

This handles local databases created before later phases added scholar evidence,
queue, and highlight-card columns.

The CLI worker entrypoints also call `init_db()` before processing tasks, so
`python3 scripts/run_worker.py` and `python3 scripts/run_worker_once.py` apply
the same SQLite upgrade path as the web app startup.
