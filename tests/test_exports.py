import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    CitingPaper,
    FulltextAnalysisResult,
    PaperAnalysisSession,
    PdfAsset,
    Publication,
    StrongEvidence,
)
from app.services.report_service import ReportService


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def seed_report_fixture(db: Session, *, with_evidence: bool = True) -> int:
    session = PaperAnalysisSession(
        query_text="Evidence-aware citation analysis",
        query_kind="title",
        status="created",
    )
    publication = Publication(
        title="Citing Study on Evidence Quality",
        year=2025,
        venue="Journal of Tests",
    )
    db.add_all([session, publication])
    db.flush()

    citing_paper = CitingPaper(
        paper_session_id=session.id,
        publication_id=publication.id,
        local_code="C001",
        analysis_status="analyzed" if with_evidence else "discovered",
    )
    db.add(citing_paper)
    db.flush()

    if with_evidence:
        parsed_result_json = json.dumps(
            {
                "findings": [
                    {
                        "evidence_type": "method_foundation",
                        "stance": "positive",
                        "mention_type": "strong",
                        "citation_text": (
                            "Evidence-aware citation analysis is a method foundation "
                            "for this system."
                        ),
                        "reasoning": "The citing paper describes a concrete method dependency.",
                        "keywords": ["method foundation", "evidence-aware"],
                    }
                ]
            }
        )
        fulltext_result = FulltextAnalysisResult(
            citing_paper_id=citing_paper.id,
            analysis_scope="citation_context",
            status="succeeded",
            parsed_result_json=parsed_result_json,
        )
        db.add(fulltext_result)
        db.flush()
        db.add(
            StrongEvidence(
                fulltext_result_id=fulltext_result.id,
                aspect="method_foundation",
                stance="positive",
                mention_type="strong",
                citation_text=(
                    "Evidence-aware citation analysis is a method foundation "
                    "for this system."
                ),
                highlight_keywords_json=json.dumps(["method foundation", "evidence-aware"]),
                score=0.9,
                evidence_strength="strong",
            )
        )

    db.commit()
    return session.id


def test_report_markdown_contains_golden_key_content(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_report_fixture(db)
        report = ReportService(db).build_report_markdown(session_id)

    assert "# Academic Impact Report" in report
    assert "Target query: Evidence-aware citation analysis" in report
    assert "Citing papers: 1" in report
    assert "Analyzed citing papers: 1" in report
    assert "Strong evidence: 1" in report
    assert "PDF status: need_pdf" in report
    assert "Citing paper: Citing Study on Evidence Quality" in report
    assert "Aspect: method_foundation" in report
    assert "Stance: positive" in report
    assert "Mention type: strong" in report
    assert "Evidence strength: strong" in report
    assert "Score: 0.90" in report
    assert "Citation text: Evidence-aware citation analysis is a method foundation" in report
    assert "Highlight keywords: method foundation, evidence-aware" in report
    assert "Reason: The citing paper describes a concrete method dependency." in report
    assert "storage_path" not in report
    assert "extracted_text_path" not in report


def test_structured_json_can_be_loaded(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_report_fixture(db)
        payload = ReportService(db).build_structured_json(session_id)

    decoded = json.loads(payload)
    assert set(decoded) == {
        "exports",
        "session",
        "citing_papers",
        "fulltext_results",
        "strong_evidence",
    }
    assert decoded["exports"]["schema_version"] == "phase8.5"
    assert decoded["exports"]["formats"] == ["report.md", "structured.json"]
    assert decoded["session"]["query_text"] == "Evidence-aware citation analysis"
    assert decoded["citing_papers"][0]["publication"]["title"] == "Citing Study on Evidence Quality"
    assert decoded["fulltext_results"][0]["status"] == "succeeded"
    assert decoded["strong_evidence"][0]["reason"] == (
        "The citing paper describes a concrete method dependency."
    )
    assert "storage_path" not in payload
    assert "extracted_text_path" not in payload


def test_exports_do_not_expose_local_library_absolute_paths(db_session_factory, tmp_path):
    secret_library_dir = tmp_path / "private-library"
    secret_library_dir.mkdir()
    local_pdf_path = secret_library_dir / "Citing Study on Evidence Quality.pdf"
    local_pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(
            query_text="Evidence-aware citation analysis",
            query_kind="title",
            status="created",
        )
        publication = Publication(title="Citing Study on Evidence Quality")
        asset = PdfAsset(
            storage_path=str(local_pdf_path),
            original_filename=local_pdf_path.name,
            mime_type="application/pdf",
            size_bytes=local_pdf_path.stat().st_size,
            sha256="local-library-sha",
            source_type="local_library",
            extract_status="pending",
        )
        db.add_all([session, publication, asset])
        db.flush()
        db.add(
            CitingPaper(
                paper_session_id=session.id,
                publication_id=publication.id,
                local_code="C001",
                analysis_status="discovered",
                pdf_asset_id=asset.id,
            )
        )
        db.commit()

        report = ReportService(db).build_report_markdown(session.id)
        payload = ReportService(db).build_structured_json(session.id)

    assert str(secret_library_dir) not in report
    assert str(local_pdf_path) not in report
    assert str(secret_library_dir) not in payload
    assert str(local_pdf_path) not in payload


def test_empty_report_exports_without_evidence(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_report_fixture(db, with_evidence=False)
        report = ReportService(db).build_report_markdown(session_id)
        decoded = json.loads(ReportService(db).build_structured_json(session_id))

    assert "Strong evidence: 0" in report
    assert "No strong evidence has been generated yet." in report
    assert decoded["strong_evidence"] == []
    assert decoded["fulltext_results"] == []


def test_empty_report_exports_without_citing_papers(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(
            query_text="No citations yet",
            query_kind="title",
            status="created",
        )
        db.add(session)
        db.commit()
        session_id = session.id

        report = ReportService(db).build_report_markdown(session_id)
        decoded = json.loads(ReportService(db).build_structured_json(session_id))

    assert "Citing papers: 0" in report
    assert "No citing papers have been discovered yet." in report
    assert decoded["citing_papers"] == []
    assert decoded["strong_evidence"] == []


def test_export_routes_return_404_for_missing_or_unsupported_export(
    client,
    db_session_factory,
):
    missing_response = client.get("/paper-sessions/999/exports/report.md")

    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_report_fixture(db)

    unsupported_response = client.get(f"/paper-sessions/{session_id}/exports/report.pdf")

    assert missing_response.status_code == 404
    assert unsupported_response.status_code == 404


def test_export_routes_return_downloadable_files(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_report_fixture(db)

    report_response = client.get(f"/paper-sessions/{session_id}/exports/report.md")
    json_response = client.get(f"/paper-sessions/{session_id}/exports/structured.json")

    assert report_response.status_code == 200
    assert "text/markdown" in report_response.headers["content-type"]
    assert "attachment" in report_response.headers["content-disposition"]
    report_response.content.decode("utf-8")
    assert "Citing Study on Evidence Quality" in report_response.text

    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert "attachment" in json_response.headers["content-disposition"]
    assert json_response.json()["strong_evidence"][0]["aspect"] == "method_foundation"
