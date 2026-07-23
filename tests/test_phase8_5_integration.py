import json

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
from app.routers.exports import get_export_service
from app.routers.uploads import get_pdf_service
from app.services.export_service import ExportService
from app.services.pdf_service import PdfService
from app.services.report_service import ReportService
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from tests.unit.test_pdf_service import build_minimal_pdf


def test_full_paper_analysis_loop_exports_report_and_structured_json(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_API_KEY", "do-not-export")
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

    def override_get_export_service():
        db = SessionLocal()
        try:
            yield ExportService(
                report_service=ReportService(db),
                export_dir=tmp_path / "exports",
            )
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    app.dependency_overrides[get_export_service] = override_get_export_service
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
        session_id = int(response.headers["location"].rsplit("/", 1)[-1])

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
            assert db.query(StrongEvidence).count() == 1

        report_response = client.get(f"/paper-sessions/{session_id}/exports/report.md")
        structured_response = client.get(
            f"/paper-sessions/{session_id}/exports/structured.json"
        )

        assert report_response.status_code == 200
        report_text = report_response.content.decode("utf-8")
        assert "Target query: Evidence-aware citation analysis" in report_text
        assert "Citing papers: 5" in report_text
        assert "Analyzed citing papers: 1" in report_text
        assert "Strong evidence: 1" in report_text
        assert "Citing paper: Evidence-Aware Academic Impact Assessment" in report_text
        assert "Aspect: method_foundation" in report_text
        assert "Stance: positive" in report_text
        assert "Mention type: strong" in report_text
        assert "Evidence strength: strong" in report_text
        assert "Score: " in report_text
        assert "Citation text: Evidence-aware citation analysis is a method foundation" in report_text
        assert "Highlight keywords: method foundation" in report_text
        assert "Reason: The citing text makes a concrete methodological dependency claim." in report_text
        assert "do-not-export" not in report_text
        assert str(tmp_path) not in report_text

        assert structured_response.status_code == 200
        structured = json.loads(structured_response.content.decode("utf-8"))
        assert structured["exports"]["schema_version"] == "phase8.5"
        assert structured["session"]["id"] == session_id
        assert len(structured["citing_papers"]) == 5
        assert len(structured["fulltext_results"]) == 1
        assert len(structured["strong_evidence"]) == 1
        assert structured["strong_evidence"][0]["aspect"] == "method_foundation"

        structured_payload = structured_response.text
        assert "do-not-export" not in structured_payload
        assert str(tmp_path) not in structured_payload
        assert "storage_path" not in structured_payload
        assert "extracted_text_path" not in structured_payload
    finally:
        app.dependency_overrides.clear()
