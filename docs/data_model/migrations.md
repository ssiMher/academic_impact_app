# SQLite Schema Migrations

The project uses a lightweight SQLite schema upgrade path for local databases.
It is intentionally narrow and does not use Alembic.

## Startup Behavior

`init_db()` runs:

1. `Base.metadata.create_all(...)` to create missing tables.
2. `upgrade_sqlite_schema(...)` to add known missing columns to existing SQLite
   tables.

This preserves existing data. The upgrade path does not delete rows and does not
rebuild the database file.

## Current Upgrade Coverage

`app/db/migrations.py` currently checks and upgrades these tables when they
already exist:

- `fulltext_analysis_results`
- `strong_evidences`
- `highlight_cards`

The migration uses `PRAGMA table_info(table_name)` to read existing columns and
then runs `ALTER TABLE ... ADD COLUMN ...` only for missing columns.

## FulltextAnalysisResult Upgrade

Older local databases may have `fulltext_analysis_results.citing_paper_id`
defined as `NOT NULL` and may lack scholar queue columns such as
`paper_session_id`, `scholar_session_id`, `queue_item_id`, and
`citation_edge_id`.

SQLite cannot remove a `NOT NULL` constraint with `ALTER COLUMN`. When the
upgrader detects `citing_paper_id` is `NOT NULL`, it rebuilds only
`fulltext_analysis_results`:

1. Rename the old table to a temporary legacy table.
2. Create a model-compatible `fulltext_analysis_results` table where
   `paper_session_id`, `scholar_session_id`, `citing_paper_id`,
   `queue_item_id`, and `citation_edge_id` are nullable.
3. Copy common existing columns from the legacy table.
4. Drop the temporary legacy table after the copy succeeds.

This table-specific rebuild is required so scholar queue analysis can write
full-text results without a `CitingPaper` row.

## StrongEvidence Upgrade

Older local databases may have `strong_evidences` without Phase 13/14 fields
such as:

- `scholar_session_id`
- `queue_item_id`
- `citation_edge_id`
- `highlighted_text_html`
- `evidence_reason`
- `page`
- `span_index`
- `anchor_status`
- `is_self_citation`
- `third_party_status`
- `review_status`
- `user_note`
- `corrected_label`

The upgrade adds these columns in place. `review_status` defaults to
`unreviewed`; `is_self_citation` defaults to false.

## Constraints

- Migration must be idempotent.
- Migration must not drop or truncate unrelated tables.
- The fulltext result table may be rebuilt in place only to remove an old
  incompatible `NOT NULL` constraint while preserving copied data.
- Migration must not depend on local production data in tests.
- Non-SQLite databases are skipped by this lightweight upgrader.

If future model changes require data backfills, add explicit tests that prove
existing rows are preserved.

## External Citation Import And PDF Discovery

The lightweight SQLite upgrader also creates
`external_citation_import_batches` and `external_citation_import_rows` if they
are missing. PDF discovery adds `source_url`, `license`, and `downloaded_at` to
`pdf_assets`, plus `pdf_discovery_status`, `pdf_access_status`, `pdf_source`,
`pdf_source_url`, publisher/DOI/OpenAlex/Google Scholar helper URLs, publisher
name, and login reason fields to `deep_analysis_queue_items`. The upgrader also
creates `pdf_inbox_entries` for browser-assisted manual PDF downloads.
