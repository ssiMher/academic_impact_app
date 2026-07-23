import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import DeepAnalysisQueueItem, PdfAsset, PdfInboxEntry, Publication
from app.pdf.match import normalize_title_for_match
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_inbox_service import PdfInboxService
from app.services.pdf_service import PdfService
from tests.test_scholar_evidence import seed_queue_item
from tests.unit.test_pdf_service import VALID_PDF_BYTES


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


def _service(db, tmp_path, *, threshold=0.82):
    return PdfInboxService(
        db=db,
        inbox_dir=Path(tmp_path / "pdf_inbox"),
        pdf_service=PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=Path(tmp_path / "pdf_assets"),
            extracted_text_dir=Path(tmp_path / "extracted_text"),
            max_upload_bytes=10_000_000,
        ),
        match_threshold=threshold,
    )


def _write_inbox_pdf(tmp_path, filename="Imported Citing Paper.pdf"):
    inbox = Path(tmp_path / "pdf_inbox")
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / filename
    path.write_bytes(VALID_PDF_BYTES)
    return path


def test_requires_login_item_shows_manual_download_helper(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3494975"
        item.pdf_discovery_status = "requires_login"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert response.status_code == 200
    assert "受限 PDF 下载助手" in response.text
    assert "系统不会保存账号密码或 Cookie" in response.text
    assert "打开 DOI 页面" in response.text
    assert "ACM Digital Library" in response.text
    assert "打开 Publisher 页面" not in response.text
    assert "打开 Google Scholar 搜索" in response.text
    assert "从本地导入目录匹配" in response.text


def test_pdf_inbox_scan_creates_pdf_asset(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _write_inbox_pdf(tmp_path)
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Imported Citing Paper", encoding="utf-8"),
        )

        summary = _service(db, tmp_path).scan_inbox()

        assert summary.scanned_count == 1
        assert db.query(PdfAsset).count() == 1
        assert db.query(PdfInboxEntry).count() == 1
        assert db.query(PdfAsset).one().source_type == "manual_download_inbox"
    finally:
        db.close()


def test_pdf_inbox_deduplicates_by_hash(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _write_inbox_pdf(tmp_path)
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Imported Citing Paper", encoding="utf-8"),
        )
        service = _service(db, tmp_path)
        service.scan_inbox()
        service.scan_inbox()

        assert db.query(PdfAsset).count() == 1
        assert db.query(PdfInboxEntry).count() == 1
    finally:
        db.close()


def test_pdf_inbox_extracts_title_or_doi(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _write_inbox_pdf(tmp_path, "10.1234_example.pdf")
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Title\n10.1234/example", encoding="utf-8"),
        )

        _service(db, tmp_path).scan_inbox()
        entry = db.query(PdfInboxEntry).one()

        assert entry.detected_doi == "10.1234/example"
        assert entry.detected_title
    finally:
        db.close()


def test_pdf_inbox_matches_queue_item_by_doi(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1234/example"
        _write_inbox_pdf(tmp_path, "10.1234_example.pdf")
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Downloaded paper text", encoding="utf-8"),
        )

        _service(db, tmp_path).scan_inbox()

        db.refresh(item)
        entry = db.query(PdfInboxEntry).one()
        assert entry.match_status == "matched"
        assert item.pdf_asset_id is not None
        assert item.pdf_access_status == "matched_from_inbox"
    finally:
        db.close()


def test_pdf_inbox_matches_queue_item_by_fuzzy_title(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            pdf_ready=False,
            title="Imported Citing Paper",
        )
        item = db.get(DeepAnalysisQueueItem, item_id)
        _write_inbox_pdf(tmp_path, "Imported Citing Paper.pdf")
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Imported Citing Paper", encoding="utf-8"),
        )

        _service(db, tmp_path).scan_inbox()

        db.refresh(item)
        assert item.pdf_asset_id is not None
        assert db.query(PdfInboxEntry).one().match_reason == "fuzzy_title"
    finally:
        db.close()


def test_pdf_inbox_low_confidence_requires_manual_confirmation(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        seed_queue_item(db, tmp_path, pdf_ready=False, title="Shared Similar Alpha Paper")
        _write_inbox_pdf(tmp_path, "Shared Similar Beta Paper.pdf")
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Shared Similar Beta Paper", encoding="utf-8"),
        )

        _service(db, tmp_path, threshold=0.60).scan_inbox()
        entry = db.query(PdfInboxEntry).one()

        assert entry.match_status == "candidate"
        assert entry.matched_queue_item_id is not None
    finally:
        db.close()


def test_pdf_inbox_bind_updates_queue_item_pdf_status(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False, title="Manual Candidate")
        _write_inbox_pdf(tmp_path, "Candidate Elsewhere.pdf")
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("Candidate Elsewhere", encoding="utf-8"),
        )
        service = _service(db, tmp_path)
        service.scan_inbox()
        entry = db.query(PdfInboxEntry).one()

        service.bind_entry_to_queue_item(entry_id=entry.id, queue_item_id=item_id)

        item = db.get(DeepAnalysisQueueItem, item_id)
        assert item.pdf_asset_id == entry.pdf_asset_id
        assert item.pdf_readiness_status == "manual_pdf"
        assert item.pdf_access_status == "matched_from_inbox"
    finally:
        db.close()


def test_missing_pdfs_download_list_export(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1109/example"
        item.venue = "IEEE Example"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/exports/missing_pdfs_download_list.csv")

    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["queue_item_id"] == str(item_id)
    assert rows[0]["doi_url"] == "https://doi.org/10.1109/example"
    assert "scholar.google.com" in rows[0]["google_scholar_query_url"]


def test_no_password_or_cookie_fields_added(db_session_factory):
    engine = db_session_factory.kw["bind"]
    columns = set()
    for table_name in inspect(engine).get_table_names():
        columns.update(column["name"].lower() for column in inspect(engine).get_columns(table_name))

    assert not any("password" in column for column in columns)
    assert not any("cookie" in column for column in columns)


def test_ui_says_no_credentials_are_stored(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.pdf_discovery_status = "requires_login"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue")

    assert response.status_code == 200
    assert "系统不会保存账号密码或 Cookie" in response.text
