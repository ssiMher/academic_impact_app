import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    AnalysisTask,
    CitingPaper,
    FulltextAnalysisResult,
    PaperAnalysisSession,
    PdfAsset,
    Publication,
    StrongEvidence,
)
from app.repositories.task_repo import TaskRepository
from app.services.task_service import DuplicateActiveTaskError, TaskService
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_paper_session(db: Session) -> PaperAnalysisSession:
    session = PaperAnalysisSession(
        query_text="Evidence-aware citation analysis",
        query_kind="title",
        status="created",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_enqueue_task(db_session):
    session = create_paper_session(db_session)
    service = TaskService(TaskRepository(db_session))

    task = service.enqueue(
        session_kind="paper_analysis",
        session_id=session.id,
        task_type="discover_paper",
    )

    assert task.id is not None
    assert task.status == "pending"
    assert task.stage == "queued"
    assert task.progress_current == 0
    assert task.progress_total == 0


def test_run_once_marks_success_and_writes_citing_papers(db_session):
    session = create_paper_session(db_session)
    task_service = TaskService(TaskRepository(db_session))
    task_service.enqueue(
        session_kind="paper_analysis",
        session_id=session.id,
        task_type="discover_paper",
    )

    runner = TaskRunner(
        task_repository=TaskRepository(db_session),
        task_manager=TaskManager(),
    )

    ran_task = runner.run_once()

    assert ran_task is not None
    assert ran_task.status == "succeeded"
    assert ran_task.stage == "finished"
    assert ran_task.finished_at is not None
    assert db_session.query(CitingPaper).count() == 5
    refreshed_session = db_session.get(PaperAnalysisSession, session.id)
    assert refreshed_session.displayed_candidate_count == 5
    assert refreshed_session.provider_total_citation_count == 5


def test_run_once_marks_failed_when_handler_fails(db_session):
    session = create_paper_session(db_session)
    task_service = TaskService(TaskRepository(db_session))
    task_service.enqueue(
        session_kind="paper_analysis",
        session_id=session.id,
        task_type="broken_task",
    )

    def fail_handler(db: Session, task: AnalysisTask) -> None:
        raise RuntimeError("boom")

    runner = TaskRunner(
        task_repository=TaskRepository(db_session),
        task_manager=TaskManager({"broken_task": fail_handler}),
    )

    ran_task = runner.run_once()

    assert ran_task is not None
    assert ran_task.status == "failed"
    assert ran_task.stage == "failed"
    assert "boom" in ran_task.error_message
    assert ran_task.finished_at is not None


def test_same_session_cannot_enqueue_two_active_discover_tasks(db_session):
    session = create_paper_session(db_session)
    service = TaskService(TaskRepository(db_session))
    service.enqueue(
        session_kind="paper_analysis",
        session_id=session.id,
        task_type="discover_paper",
    )

    with pytest.raises(DuplicateActiveTaskError):
        service.enqueue(
            session_kind="paper_analysis",
            session_id=session.id,
            task_type="discover_paper",
        )


def test_run_once_analyze_citation_generates_strong_evidence(db_session, tmp_path):
    text_path = tmp_path / "extracted.txt"
    text_path.write_text(
        "Evidence-aware citation analysis is a method foundation for this system.",
        encoding="utf-8",
    )
    session = create_paper_session(db_session)
    publication = Publication(title="Runner citing paper")
    pdf_asset = PdfAsset(
        storage_path=str(tmp_path / "paper.pdf"),
        original_filename="paper.pdf",
        extract_status="succeeded",
        extracted_text_path=str(text_path),
    )
    db_session.add_all([publication, pdf_asset])
    db_session.flush()
    citing_paper = CitingPaper(
        paper_session_id=session.id,
        publication_id=publication.id,
        analysis_status="discovered",
        pdf_asset_id=pdf_asset.id,
    )
    db_session.add(citing_paper)
    db_session.commit()
    db_session.refresh(citing_paper)

    TaskService(TaskRepository(db_session)).enqueue(
        session_kind="citing_paper",
        session_id=citing_paper.id,
        task_type="analyze_citation",
    )
    runner = TaskRunner(
        task_repository=TaskRepository(db_session),
        task_manager=TaskManager(),
    )

    ran_task = runner.run_once()

    assert ran_task is not None
    assert ran_task.status == "succeeded"
    assert db_session.query(FulltextAnalysisResult).count() == 1
    assert db_session.query(StrongEvidence).count() == 1
