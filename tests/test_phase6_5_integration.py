from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AnalysisTask, CitingPaper, FulltextAnalysisResult, StrongEvidence
from app.repositories.pdf_repo import PdfRepository
from app.repositories.task_repo import TaskRepository
from app.routers.uploads import get_pdf_service
from app.services.pdf_service import PdfService
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from tests.unit.test_pdf_service import build_minimal_pdf


def test_full_paper_analysis_loop_generates_strong_evidence(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_pdf_service():
        db = SessionLocal()
        try:
            yield PdfService(
                repository=PdfRepository(db),
                pdf_asset_dir=tmp_path / "pdf_assets",
                extracted_text_dir=tmp_path / "extracted_text",
                max_upload_bytes=100000,
            )
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    try:
        client = TestClient(app)
        response = client.post(
            "/paper-sessions",
            data={
                "query_text": "Evidence-aware citation analysis",
                "query_kind": "title",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        session_url = response.headers["location"]
        session_id = int(session_url.rsplit("/", 1)[-1])

        response = client.post(f"/paper-sessions/{session_id}/discover", follow_redirects=False)
        assert response.status_code == 303

        with Session(engine) as db:
            runner = TaskRunner(
                task_repository=TaskRepository(db),
                task_manager=TaskManager(),
            )
            discover_task = runner.run_once()
            assert discover_task.status == "succeeded"
            citing_paper = db.query(CitingPaper).order_by(CitingPaper.id.asc()).first()
            citing_paper_id = citing_paper.id

        session_detail = client.get(f"/paper-sessions/{session_id}")
        assert session_detail.status_code == 200
        assert f"/citing-papers/{citing_paper_id}" in session_detail.text

        pdf_bytes = build_minimal_pdf(
            "Evidence-aware citation analysis is a method foundation for this system."
        )
        response = client.post(
            f"/citing-papers/{citing_paper_id}/pdf",
            files={"file": ("target.pdf", pdf_bytes, "application/pdf")},
            follow_redirects=False,
        )
        assert response.status_code == 303

        response = client.post(f"/citing-papers/{citing_paper_id}/analyze", follow_redirects=False)
        assert response.status_code == 303

        with Session(engine) as db:
            analyze_task = (
                db.query(AnalysisTask)
                .filter(AnalysisTask.task_type == "analyze_citation")
                .one()
            )
            runner = TaskRunner(
                task_repository=TaskRepository(db),
                task_manager=TaskManager(),
            )
            ran_task = runner.run_once()
            assert ran_task.id == analyze_task.id
            assert ran_task.status == "succeeded"
            assert db.query(FulltextAnalysisResult).count() == 1
            evidence = db.query(StrongEvidence).one()
            assert evidence.aspect == "method_foundation"
            assert evidence.stance == "positive"
            assert evidence.mention_type == "strong"
            assert "method foundation" in evidence.highlight_keywords_json

        citing_detail = client.get(f"/citing-papers/{citing_paper_id}")
        assert citing_detail.status_code == 200
        assert "Evidence-aware citation analysis is a method foundation" in citing_detail.text
        assert "method_foundation" in citing_detail.text
        assert "positive" in citing_detail.text
        assert "strong" in citing_detail.text
        assert "Mention Type: strong" in citing_detail.text
        assert "Reason:" in citing_detail.text
        assert "concrete methodological dependency claim" in citing_detail.text
        assert "method foundation" in citing_detail.text
    finally:
        app.dependency_overrides.clear()
