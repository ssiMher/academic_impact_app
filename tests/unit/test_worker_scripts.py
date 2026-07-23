import importlib.util

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import AnalysisTask, CitingPaper, PaperAnalysisSession
from app.repositories.task_repo import TaskRepository
from app.services.task_service import TaskService
from scripts.worker_entrypoint import run_worker_once


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


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


def test_run_worker_once_executes_pending_task(capsys):
    session_factory = make_session_factory()
    with Session(session_factory.kw["bind"]) as db:
        session = create_paper_session(db)
        TaskService(TaskRepository(db)).enqueue(
            session_kind="paper_analysis",
            session_id=session.id,
            task_type="discover_paper",
        )

    task = run_worker_once(session_factory=session_factory)

    captured = capsys.readouterr()
    assert task is not None
    assert f"Task #{task.id} discover_paper -> succeeded" in captured.out
    with Session(session_factory.kw["bind"]) as db:
        assert db.query(CitingPaper).count() == 5


def test_run_worker_once_without_pending_task_prints_message(capsys):
    session_factory = make_session_factory()

    task = run_worker_once(session_factory=session_factory)

    captured = capsys.readouterr()
    assert task is None
    assert "No pending task." in captured.out


def test_run_worker_once_marks_failed_task_and_records_error(capsys):
    session_factory = make_session_factory()
    with Session(session_factory.kw["bind"]) as db:
        session = create_paper_session(db)
        TaskService(TaskRepository(db)).enqueue(
            session_kind="paper_analysis",
            session_id=session.id,
            task_type="missing_handler",
        )

    task = run_worker_once(session_factory=session_factory)

    captured = capsys.readouterr()
    assert task is not None
    assert f"Task #{task.id} missing_handler -> failed" in captured.out
    with Session(session_factory.kw["bind"]) as db:
        saved = db.query(AnalysisTask).one()
        assert saved.status == "failed"
        assert "No handler registered" in saved.error_message


def test_worker_scripts_can_import_without_path_errors():
    for path in ["scripts/run_worker_once.py", "scripts/run_worker.py"]:
        spec = importlib.util.spec_from_file_location("worker_script_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
