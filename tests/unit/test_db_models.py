from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.base import Base, init_db
from app.models import AnalysisTask, PaperAnalysisSession


def test_init_db_creates_all_phase_1_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase1.db'}")

    init_db(engine)

    table_names = set(inspect(engine).get_table_names())
    assert table_names == {
        "analysis_tasks",
        "paper_analysis_sessions",
        "publications",
        "target_papers",
        "citing_papers",
        "pdf_assets",
        "pdf_asset_publication_links",
        "fulltext_analysis_results",
        "strong_evidences",
        "evidence_reviews",
        "scholar_analysis_sessions",
        "scholar_publications",
        "citation_edges",
        "pdf_library_indexes",
        "pdf_library_entries",
        "pdf_inbox_entries",
        "deep_analysis_queue_items",
        "highlight_cards",
        "notable_authors",
        "citation_author_annotations",
        "analysis_templates",
        "template_matches",
        "external_citation_import_batches",
        "external_citation_import_rows",
    }


def test_can_insert_and_query_session_and_task(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase1.db'}")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        session = PaperAnalysisSession(
            query_text="academic impact",
            query_kind="title",
            status="created",
        )
        db.add(session)
        db.flush()

        task = AnalysisTask(
            session_kind="paper_analysis",
            session_id=session.id,
            task_type="fulltext_analysis",
            status="pending",
            stage="queued",
        )
        db.add(task)
        db.commit()

    with Session(engine) as db:
        saved_session = db.query(PaperAnalysisSession).one()
        saved_task = db.query(AnalysisTask).one()

    assert saved_session.query_text == "academic impact"
    assert saved_session.provider_total_citation_count is None
    assert saved_session.displayed_candidate_count == 0
    assert saved_task.session_id == saved_session.id
    assert saved_task.progress_current == 0
    assert saved_task.progress_total == 0
