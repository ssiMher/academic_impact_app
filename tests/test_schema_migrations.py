from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.migrations import upgrade_sqlite_schema
from app.db.session import get_db
from app.main import app
from app.models import ScholarAnalysisSession
from app.services.scholar_fulltext_service import ScholarFulltextService
from tests.test_scholar_evidence import seed_queue_item


def _sqlite_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _column_names(engine, table_name):
    with engine.connect() as connection:
        return {
            row["name"]
            for row in connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
        }


def _column_info(engine, table_name):
    with engine.connect() as connection:
        return {
            row["name"]: dict(row)
            for row in connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
        }


def _create_old_fulltext_results_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE fulltext_analysis_results (
                    id INTEGER PRIMARY KEY,
                    citing_paper_id INTEGER NOT NULL,
                    analysis_scope VARCHAR(64),
                    status VARCHAR(32),
                    parsed_result_json TEXT
                )
                """
            )
        )


def _create_old_analysis_tasks_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE analysis_tasks (
                    id INTEGER PRIMARY KEY,
                    session_kind VARCHAR(64),
                    session_id INTEGER,
                    task_type VARCHAR(64),
                    status VARCHAR(32),
                    stage VARCHAR(64),
                    stage_message TEXT,
                    progress_current INTEGER,
                    progress_total INTEGER,
                    error_message TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    started_at DATETIME,
                    finished_at DATETIME
                )
                """
            )
        )


def _replace_fulltext_results_with_old_schema(engine):
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE fulltext_analysis_results"))
        connection.execute(
            text(
                """
                CREATE TABLE fulltext_analysis_results (
                    id INTEGER PRIMARY KEY,
                    citing_paper_id INTEGER NOT NULL,
                    analysis_scope VARCHAR(64),
                    status VARCHAR(32),
                    parsed_result_json TEXT
                )
                """
            )
        )


def _create_old_highlight_cards_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE highlight_cards (
                    id INTEGER PRIMARY KEY,
                    strong_evidence_id INTEGER,
                    title TEXT
                )
                """
            )
        )


def _replace_strong_evidence_with_old_schema(engine):
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE strong_evidences"))
        connection.execute(
            text(
                """
                CREATE TABLE strong_evidences (
                    id INTEGER PRIMARY KEY,
                    fulltext_result_id INTEGER NOT NULL,
                    aspect VARCHAR(128),
                    stance VARCHAR(64),
                    mention_type VARCHAR(64),
                    citation_text TEXT,
                    highlight_keywords_json TEXT,
                    score FLOAT,
                    evidence_strength VARCHAR(64)
                )
                """
            )
        )


def _create_old_strong_evidence_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE strong_evidences (
                    id INTEGER PRIMARY KEY,
                    fulltext_result_id INTEGER NOT NULL,
                    aspect VARCHAR(128),
                    stance VARCHAR(64),
                    mention_type VARCHAR(64),
                    citation_text TEXT,
                    highlight_keywords_json TEXT,
                    score FLOAT,
                    evidence_strength VARCHAR(64)
                )
                """
            )
        )


def _insert_old_strong_evidence(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO strong_evidences (
                    id,
                    fulltext_result_id,
                    aspect,
                    stance,
                    mention_type,
                    citation_text,
                    highlight_keywords_json,
                    score,
                    evidence_strength
                )
                VALUES (
                    1,
                    10,
                    'method_foundation',
                    'positive',
                    'strong',
                    'Original citation text',
                    '["method"]',
                    0.9,
                    'strong'
                )
                """
            )
        )


def _insert_old_fulltext_result(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO fulltext_analysis_results (
                    id,
                    citing_paper_id,
                    analysis_scope,
                    status,
                    parsed_result_json
                )
                VALUES (
                    1,
                    123,
                    'citation_context',
                    'succeeded',
                    '{"findings":[]}'
                )
                """
            )
        )


def _prepare_upgraded_app_db(engine):
    Base.metadata.create_all(bind=engine)
    _replace_strong_evidence_with_old_schema(engine)
    with sessionmaker(bind=engine, autoflush=False, autocommit=False)() as db:
        session = ScholarAnalysisSession(
            display_name="Legacy Scholar",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        session_id = session.id
    upgrade_sqlite_schema(engine)
    return session_id


def test_upgrade_adds_missing_fulltext_result_columns():
    engine = _sqlite_engine()
    _create_old_fulltext_results_table(engine)

    upgrade_sqlite_schema(engine)

    columns = _column_names(engine, "fulltext_analysis_results")
    for column in [
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
    ]:
        assert column in columns


def test_upgrade_rebuilds_fulltext_results_when_citing_paper_id_not_null():
    engine = _sqlite_engine()
    _create_old_fulltext_results_table(engine)

    assert _column_info(engine, "fulltext_analysis_results")["citing_paper_id"]["notnull"] == 1

    upgrade_sqlite_schema(engine)

    assert _column_info(engine, "fulltext_analysis_results")["citing_paper_id"]["notnull"] == 0


def test_upgrade_adds_missing_strong_evidence_columns():
    engine = _sqlite_engine()
    _create_old_strong_evidence_table(engine)

    upgrade_sqlite_schema(engine)

    columns = _column_names(engine, "strong_evidences")
    for column in [
        "scholar_session_id",
        "queue_item_id",
        "citation_edge_id",
        "highlighted_text_html",
        "evidence_reason",
        "page",
        "span_index",
        "anchor_status",
        "is_self_citation",
        "third_party_status",
        "review_status",
        "user_note",
        "corrected_label",
    ]:
        assert column in columns


def test_upgrade_adds_missing_highlight_card_columns():
    engine = _sqlite_engine()
    _create_old_highlight_cards_table(engine)

    upgrade_sqlite_schema(engine)

    columns = _column_names(engine, "highlight_cards")
    for column in [
        "scholar_session_id",
        "strong_evidence_id",
        "card_type",
        "title",
        "subtitle",
        "body_markdown",
        "evidence_quote",
        "highlighted_quote_html",
        "source_citing_paper_title",
        "source_cited_paper_title",
        "aspect",
        "stance",
        "evidence_strength",
        "score",
        "sort_order",
        "is_user_edited",
        "user_note",
        "created_at",
        "updated_at",
    ]:
        assert column in columns


def test_schema_upgrade_adds_missing_task_payload_column_if_model_requires_it():
    engine = _sqlite_engine()
    _create_old_analysis_tasks_table(engine)

    upgrade_sqlite_schema(engine)

    columns = _column_names(engine, "analysis_tasks")
    assert "payload_json" in columns


def test_analysis_tasks_schema_has_expected_payload_field_or_query_does_not_require_it():
    engine = _sqlite_engine()
    _create_old_analysis_tasks_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO analysis_tasks (
                    id, session_kind, session_id, task_type, status, stage,
                    progress_current, progress_total
                )
                VALUES (1, 'scholar_analysis', 1, 'expand_scholar_citations', 'pending', 'queued', 0, 0)
                """
            )
        )

    upgrade_sqlite_schema(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, payload_json FROM analysis_tasks WHERE id = 1")
        ).mappings().one()

    assert row["id"] == 1
    assert row["payload_json"] is None


def test_task_debug_page_does_not_crash_without_payload_json():
    engine = _sqlite_engine()
    _create_old_analysis_tasks_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO analysis_tasks (
                    id, session_kind, session_id, task_type, status, stage,
                    stage_message, progress_current, progress_total
                )
                VALUES (1, 'scholar_analysis', 1, 'expand_scholar_citations', 'pending', 'queued', 'queued', 0, 0)
                """
            )
        )
    upgrade_sqlite_schema(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/v1/tasks/1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["task_type"] == "expand_scholar_citations"


def test_upgrade_creates_pdf_asset_publication_links_table():
    engine = _sqlite_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE pdf_assets (
                    id INTEGER PRIMARY KEY,
                    storage_path TEXT NOT NULL
                )
                """
            )
        )

    upgrade_sqlite_schema(engine)

    table_names = inspect(engine).get_table_names()
    columns = _column_names(engine, "pdf_asset_publication_links")
    assert "pdf_asset_publication_links" in table_names
    for column in [
        "pdf_asset_id",
        "publication_id",
        "doi",
        "openalex_id",
        "normalized_title",
        "raw_title",
        "match_method",
        "match_score",
        "is_verified",
    ]:
        assert column in columns


def test_upgrade_is_idempotent():
    engine = _sqlite_engine()
    _create_old_strong_evidence_table(engine)

    upgrade_sqlite_schema(engine)
    first_columns = _column_names(engine, "strong_evidences")
    upgrade_sqlite_schema(engine)
    second_columns = _column_names(engine, "strong_evidences")

    assert second_columns == first_columns


def test_existing_fulltext_data_preserved_after_upgrade():
    engine = _sqlite_engine()
    _create_old_fulltext_results_table(engine)
    _insert_old_fulltext_result(engine)

    upgrade_sqlite_schema(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, citing_paper_id, analysis_scope, status, parsed_result_json
                FROM fulltext_analysis_results
                WHERE id = 1
                """
            )
        ).mappings().one()

    assert row["id"] == 1
    assert row["citing_paper_id"] == 123
    assert row["analysis_scope"] == "citation_context"
    assert row["status"] == "succeeded"
    assert row["parsed_result_json"] == '{"findings":[]}'


def test_existing_data_preserved_after_upgrade():
    engine = _sqlite_engine()
    _create_old_strong_evidence_table(engine)
    _insert_old_strong_evidence(engine)

    upgrade_sqlite_schema(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT citation_text, review_status
                FROM strong_evidences
                WHERE id = 1
                """
            )
        ).mappings().one()

    assert row["citation_text"] == "Original citation text"
    assert row["review_status"] == "unreviewed"


def test_analyze_scholar_queue_writes_fulltext_result_after_upgrade(tmp_path):
    engine = _sqlite_engine()
    Base.metadata.create_all(bind=engine)
    _replace_fulltext_results_with_old_schema(engine)
    upgrade_sqlite_schema(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        rows = db.execute(text("SELECT * FROM fulltext_analysis_results")).mappings().all()

    assert summary["analyzed_count"] == 1
    assert len(rows) == 1
    assert rows[0]["scholar_session_id"] == session_id
    assert rows[0]["queue_item_id"] == item_id
    assert rows[0]["citing_paper_id"] is None


def test_evidence_page_does_not_fail_on_upgraded_db():
    engine = _sqlite_engine()
    session_id = _prepare_upgraded_app_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(f"/scholar-sessions/{session_id}/evidence")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_scholar_report_export_does_not_fail_on_upgraded_db():
    engine = _sqlite_engine()
    session_id = _prepare_upgraded_app_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            f"/scholar-sessions/{session_id}/exports/report.md"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
