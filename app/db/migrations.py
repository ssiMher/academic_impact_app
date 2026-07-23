"""Lightweight SQLite schema upgrades for local development databases."""

from contextlib import contextmanager
from typing import Iterator, Mapping, Set, Union

from sqlalchemy import Connection, Engine, text


ColumnDefinitions = Mapping[str, str]


SQLITE_COLUMN_UPGRADES: Mapping[str, ColumnDefinitions] = {
    "analysis_tasks": {
        "payload_json": "TEXT",
    },
    "fulltext_analysis_results": {
        "paper_session_id": "INTEGER",
        "scholar_session_id": "INTEGER",
        "citing_paper_id": "INTEGER",
        "queue_item_id": "INTEGER",
        "citation_edge_id": "INTEGER",
        "analysis_scope": "VARCHAR(64)",
        "status": "VARCHAR(32)",
        "llm_provider": "VARCHAR(64)",
        "llm_model": "VARCHAR(255)",
        "prompt_version": "VARCHAR(64)",
        "candidate_spans_json": "TEXT",
        "parsed_result_json": "TEXT",
        "error_message": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "strong_evidences": {
        "scholar_session_id": "INTEGER",
        "queue_item_id": "INTEGER",
        "citation_edge_id": "INTEGER",
        "highlighted_text_html": "TEXT",
        "evidence_reason": "TEXT",
        "page": "INTEGER",
        "span_index": "INTEGER",
        "anchor_status": "VARCHAR(64)",
        "is_self_citation": "BOOLEAN DEFAULT 0",
        "third_party_status": "VARCHAR(64)",
        "review_status": "VARCHAR(64) DEFAULT 'unreviewed'",
        "user_note": "TEXT",
        "corrected_label": "VARCHAR(128)",
        "score": "FLOAT",
        "evidence_strength": "VARCHAR(64)",
        "matched_template_ids_json": "TEXT",
        "template_match_reason": "TEXT",
        "template_satisfied": "BOOLEAN",
        "template_failure_reason": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "highlight_cards": {
        "scholar_session_id": "INTEGER",
        "strong_evidence_id": "INTEGER",
        "card_type": "VARCHAR(128)",
        "title": "TEXT",
        "subtitle": "TEXT",
        "narrative_zh": "TEXT",
        "narrative_en": "TEXT",
        "body_markdown": "TEXT",
        "evidence_quote": "TEXT",
        "highlighted_quote_html": "TEXT",
        "source_citing_paper_title": "TEXT",
        "source_cited_paper_title": "TEXT",
        "citing_authors_json": "TEXT",
        "notable_author_name": "TEXT",
        "notable_author_affiliation": "TEXT",
        "notable_author_role": "TEXT",
        "fellow_status": "VARCHAR(64)",
        "venue": "TEXT",
        "venue_tier": "VARCHAR(64)",
        "aspect": "VARCHAR(128)",
        "stance": "VARCHAR(64)",
        "evidence_strength": "VARCHAR(64)",
        "score": "FLOAT",
        "source_evidence_id": "INTEGER",
        "review_status": "VARCHAR(64)",
        "sort_order": "INTEGER DEFAULT 0",
        "is_user_edited": "BOOLEAN DEFAULT 0",
        "user_note": "TEXT",
        "include_in_report": "BOOLEAN DEFAULT 1",
        "matched_template_ids_json": "TEXT",
        "matched_template_names": "TEXT",
        "template_match_reason": "TEXT",
        "template_satisfied": "BOOLEAN",
        "template_failure_reason": "TEXT",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "pdf_assets": {
        "source_url": "TEXT",
        "license": "VARCHAR(255)",
        "downloaded_at": "DATETIME",
    },
    "deep_analysis_queue_items": {
        "pdf_discovery_status": "VARCHAR(64) DEFAULT 'not_started'",
        "pdf_access_status": "VARCHAR(64) DEFAULT 'manual_download_needed'",
        "pdf_source": "VARCHAR(64)",
        "pdf_source_url": "TEXT",
        "publisher_landing_url": "TEXT",
        "doi_url": "TEXT",
        "openalex_url": "TEXT",
        "google_scholar_query_url": "TEXT",
        "publisher_name": "VARCHAR(128)",
        "requires_login_reason": "TEXT",
    },
    "citation_author_annotations": {
        "citing_author_affiliation": "TEXT",
        "parsed_citing_paper_title": "TEXT",
        "parsed_citing_venue_short": "TEXT",
        "parsed_citing_year": "INTEGER",
        "parsed_citing_pub_type": "TEXT",
        "matched_citing_paper_title": "TEXT",
        "matched_cited_paper_title": "TEXT",
        "unmatched_reason": "TEXT",
    },
}


def upgrade_sqlite_schema(engine_or_connection: Union[Engine, Connection]) -> None:
    """Add missing columns to known SQLite tables without dropping data.

    This intentionally covers the project's local SQLite upgrade path only. It
    is idempotent and skips tables that do not exist yet, allowing
    ``Base.metadata.create_all`` to create brand-new databases normally.
    """

    with _connection_for(engine_or_connection) as connection:
        if connection.dialect.name != "sqlite":
            return
        if _table_exists(connection, "fulltext_analysis_results"):
            _rebuild_fulltext_results_if_needed(connection)
        for table_name, columns in SQLITE_COLUMN_UPGRADES.items():
            if not _table_exists(connection, table_name):
                continue
            existing_columns = _existing_column_names(connection, table_name)
            for column_name, column_definition in columns.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {column_definition}"
                        )
                    )
        _create_pdf_asset_publication_links_table(connection)
        _create_external_citation_import_tables(connection)
        _create_pdf_inbox_entries_table(connection)
        _create_notable_authors_table(connection)
        _create_citation_author_annotations_table(connection)
        connection.commit()


@contextmanager
def _connection_for(engine_or_connection: Union[Engine, Connection]) -> Iterator[Connection]:
    if isinstance(engine_or_connection, Engine):
        with engine_or_connection.connect() as connection:
            yield connection
        return
    yield engine_or_connection


def _table_exists(connection: Connection, table_name: str) -> bool:
    result = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = :table_name"
        ),
        {"table_name": table_name},
    )
    return result.first() is not None


def _existing_column_names(connection: Connection, table_name: str) -> Set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    return {str(row["name"]) for row in rows}


def _column_info(connection: Connection, table_name: str) -> Mapping[str, Mapping[str, object]]:
    rows = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    return {str(row["name"]): dict(row) for row in rows}


def _rebuild_fulltext_results_if_needed(connection: Connection) -> None:
    columns = _column_info(connection, "fulltext_analysis_results")
    citing_paper = columns.get("citing_paper_id")
    if citing_paper is None or int(citing_paper.get("notnull") or 0) != 1:
        return

    legacy_table = "fulltext_analysis_results__legacy_upgrade"
    connection.execute(text(f"DROP TABLE IF EXISTS {legacy_table}"))
    connection.execute(
        text(f"ALTER TABLE fulltext_analysis_results RENAME TO {legacy_table}")
    )
    _create_fulltext_results_table(connection)

    new_columns = [
        "id",
        "paper_session_id",
        "scholar_session_id",
        "citing_paper_id",
        "queue_item_id",
        "citation_edge_id",
        "analysis_scope",
        "status",
        "llm_provider",
        "llm_model",
        "prompt_version",
        "candidate_spans_json",
        "parsed_result_json",
        "error_message",
        "created_at",
        "updated_at",
    ]
    legacy_columns = _existing_column_names(connection, legacy_table)
    common_columns = [column for column in new_columns if column in legacy_columns]
    if common_columns:
        column_sql = ", ".join(common_columns)
        connection.execute(
            text(
                "INSERT INTO fulltext_analysis_results "
                f"({column_sql}) SELECT {column_sql} FROM {legacy_table}"
            )
        )
    connection.execute(text(f"DROP TABLE {legacy_table}"))


def _create_fulltext_results_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE fulltext_analysis_results (
                id INTEGER PRIMARY KEY,
                paper_session_id INTEGER,
                scholar_session_id INTEGER,
                citing_paper_id INTEGER,
                queue_item_id INTEGER,
                citation_edge_id INTEGER,
                analysis_scope VARCHAR(64),
                status VARCHAR(32),
                llm_provider VARCHAR(64),
                llm_model VARCHAR(255),
                prompt_version VARCHAR(64),
                candidate_spans_json TEXT,
                parsed_result_json TEXT,
                error_message TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
    )


def _create_pdf_asset_publication_links_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_asset_publication_links (
                id INTEGER PRIMARY KEY,
                pdf_asset_id INTEGER NOT NULL,
                publication_id INTEGER,
                doi VARCHAR(255),
                openalex_id VARCHAR(255),
                normalized_title TEXT,
                raw_title TEXT,
                match_method VARCHAR(128) NOT NULL,
                match_score FLOAT DEFAULT 0.0,
                is_verified BOOLEAN DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
    )


def _create_notable_authors_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS notable_authors (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                affiliation TEXT,
                fellow_status VARCHAR(64) DEFAULT 'unknown',
                homepage TEXT,
                notes TEXT,
                source TEXT,
                is_manual_verified BOOLEAN DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
    )


def _create_citation_author_annotations_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS citation_author_annotations (
                id INTEGER PRIMARY KEY,
                scholar_session_id INTEGER NOT NULL,
                queue_item_id INTEGER,
                citation_edge_id INTEGER,
                citing_publication_id INTEGER,
                notable_author_id INTEGER NOT NULL,
                citing_author_name TEXT NOT NULL,
                citing_author_affiliation TEXT,
                honor_category TEXT NOT NULL,
                citing_paper_info TEXT,
                parsed_citing_paper_title TEXT,
                parsed_citing_venue_short TEXT,
                parsed_citing_year INTEGER,
                parsed_citing_pub_type TEXT,
                my_cited_paper_title TEXT,
                matched_citing_paper_title TEXT,
                matched_cited_paper_title TEXT,
                match_method VARCHAR(64) DEFAULT 'unmatched',
                match_score FLOAT DEFAULT 0.0,
                match_status VARCHAR(32) DEFAULT 'unmatched',
                unmatched_reason TEXT,
                is_important BOOLEAN DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
    )


def _create_external_citation_import_tables(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS external_citation_import_batches (
                id INTEGER PRIMARY KEY,
                session_kind VARCHAR(64) NOT NULL,
                session_id INTEGER NOT NULL,
                source_name VARCHAR(128) NOT NULL,
                filename TEXT,
                total_rows INTEGER DEFAULT 0,
                imported_count INTEGER DEFAULT 0,
                matched_existing_count INTEGER DEFAULT 0,
                duplicate_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                created_at DATETIME
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS external_citation_import_rows (
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                raw_row_json TEXT NOT NULL,
                parsed_title TEXT,
                parsed_doi VARCHAR(255),
                parsed_year INTEGER,
                parsed_venue TEXT,
                match_status VARCHAR(64) NOT NULL,
                match_reason TEXT,
                citation_edge_id INTEGER,
                error_message TEXT
            )
            """
        )
    )


def _create_pdf_inbox_entries_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pdf_inbox_entries (
                id INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                sha256 VARCHAR(64) NOT NULL,
                pdf_asset_id INTEGER,
                detected_title TEXT,
                detected_doi VARCHAR(255),
                page_count INTEGER,
                match_status VARCHAR(64) DEFAULT 'unmatched',
                match_reason TEXT,
                matched_queue_item_id INTEGER,
                match_score FLOAT DEFAULT 0.0,
                ignored BOOLEAN DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
    )
