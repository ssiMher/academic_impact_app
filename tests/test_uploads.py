from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CitingPaper, FulltextAnalysisResult, PdfAsset, Publication, StrongEvidence
from app.repositories.pdf_repo import PdfRepository
from app.routers.uploads import get_pdf_service
from app.services.pdf_service import PdfService
from tests.unit.test_pdf_service import VALID_PDF_BYTES


def test_upload_pdf_route_saves_asset_and_detail_shows_status(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with Session(engine) as db:
        publication = Publication(title="Route citing paper")
        db.add(publication)
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=1,
            publication_id=publication.id,
            analysis_status="discovered",
        )
        db.add(citing_paper)
        db.commit()
        citing_paper_id = citing_paper.id

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
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            f"/citing-papers/{citing_paper_id}/pdf",
            files={"file": ("uploaded-name.pdf", VALID_PDF_BYTES, "application/pdf")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/citing-papers/{citing_paper_id}"

        detail = client.get(f"/citing-papers/{citing_paper_id}")
        assert detail.status_code == 200
        assert "PDF 状态" in detail.text
        assert "succeeded" in detail.text
    finally:
        app.dependency_overrides.clear()

    with Session(engine) as db:
        asset = db.query(PdfAsset).one()
    assert asset.original_filename == "uploaded-name.pdf"
    assert "uploaded-name.pdf" not in asset.storage_path


def test_citing_paper_detail_displays_strong_evidence(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with Session(engine) as db:
        publication = Publication(title="Evidence detail paper")
        db.add(publication)
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=1,
            publication_id=publication.id,
            analysis_status="analyzed",
        )
        db.add(citing_paper)
        db.flush()
        result = FulltextAnalysisResult(
            citing_paper_id=citing_paper.id,
            analysis_scope="citation_context",
            status="succeeded",
            parsed_result_json="{}",
        )
        db.add(result)
        db.flush()
        db.add(
            StrongEvidence(
                fulltext_result_id=result.id,
                aspect="method_foundation",
                stance="positive",
                mention_type="strong",
                citation_text="The target paper is a method foundation.",
                highlight_keywords_json='["method foundation", "target paper"]',
                score=0.86,
                evidence_strength="strong",
            )
        )
        db.commit()
        citing_paper_id = citing_paper.id

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
        from fastapi.testclient import TestClient

        response = TestClient(app).get(f"/citing-papers/{citing_paper_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "The target paper is a method foundation." in response.text
    assert "method_foundation" in response.text
    assert "positive" in response.text
    assert "method foundation" in response.text
    assert "strong" in response.text


def test_citing_paper_without_pdf_shows_need_pdf_and_rejects_analyze(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with Session(engine) as db:
        publication = Publication(title="Needs PDF paper")
        db.add(publication)
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=1,
            publication_id=publication.id,
            analysis_status="discovered",
        )
        db.add(citing_paper)
        db.commit()
        citing_paper_id = citing_paper.id

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        from fastapi.testclient import TestClient

        client = TestClient(app)
        detail = client.get(f"/citing-papers/{citing_paper_id}")
        analyze = client.post(f"/citing-papers/{citing_paper_id}/analyze")
    finally:
        app.dependency_overrides.clear()

    assert detail.status_code == 200
    assert "need_pdf" in detail.text
    assert analyze.status_code == 409
    assert "need_pdf" in analyze.json()["detail"]
