import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisTask,
    CitationEdge,
    DeepAnalysisQueueItem,
    PdfAssetPublicationLink,
    Publication,
)
from app.repositories.task_repo import TaskRepository
from app.services.ieee_download_service import IeeeBrowserDownloader, IeeeDownloadResult
from app.services.queue_pdf_download_service import (
    PdfDownloadResult,
    QueuePdfDownloadService,
)
from app.tasks.handlers.discover_pdfs_for_queue import handle_discover_pdfs_for_queue
from app.tasks.handlers.download_ieee_pdf import handle_download_ieee_pdf
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from tests.test_scholar_evidence import seed_queue_item
from tests.unit.test_pdf_service import VALID_PDF_BYTES


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ieee_item(db, tmp_path):
    session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
    item = db.get(DeepAnalysisQueueItem, item_id)
    publication = db.get(Publication, item.citing_publication_id)
    publication.title = "A Precise IEEE Paper Title"
    publication.doi = "10.1109/TIM.2025.1234567"
    item.citing_paper_title = publication.title
    item.publisher_landing_url = "https://ieeexplore.ieee.org/document/12345678"
    db.commit()
    return session_id, item_id


def test_ieee_downloader_accepts_complete_pdf_from_configured_output(tmp_path, monkeypatch):
    tool = tmp_path / "ieee-download"
    tool.touch()
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    pdf_path = download_dir / "12345678_paper.pdf"
    pdf_path.write_bytes(VALID_PDF_BYTES)
    monkeypatch.setattr(
        "app.services.ieee_download_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"[成功] {pdf_path}\n",
        ),
    )

    result = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(download_dir),
    ).download("A Precise IEEE Paper Title")

    assert result.status == "downloaded"
    assert result.pdf_path == pdf_path


def test_ieee_downloader_rejects_html_or_incomplete_output(tmp_path, monkeypatch):
    tool = tmp_path / "ieee-download"
    tool.touch()
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    bad_path = download_dir / "login.pdf"
    bad_path.write_bytes(b"<html>Institutional Sign In</html>")
    monkeypatch.setattr(
        "app.services.ieee_download_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"[成功] {bad_path}\n",
        ),
    )

    result = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(download_dir),
    ).download("Paper")

    assert result.status == "requires_login"
    assert result.pdf_path is None


def test_ieee_download_route_enqueues_queue_item_payload(tmp_path):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    db.close()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/download-ieee-pdf",
            follow_redirects=False,
        )
        assert response.status_code == 303
        verify = factory()
        task = verify.query(AnalysisTask).filter_by(task_type="download_ieee_pdf").one()
        assert json.loads(task.payload_json) == {"queue_item_id": item_id}
        verify.close()
    finally:
        app.dependency_overrides.clear()


def test_ieee_download_task_imports_asset_and_binds_queue_item(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    pdf_path = tmp_path / "downloads" / "12345678_paper.pdf"
    pdf_path.parent.mkdir()
    pdf_path.write_bytes(VALID_PDF_BYTES)
    task = TaskRepository(db).create(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="download_ieee_pdf",
        payload={"queue_item_id": item_id},
    )

    fake_settings = SimpleNamespace(
        ieee_downloader_command="ieee-download",
        ieee_downloader_work_dir=str(tmp_path),
        ieee_downloader_download_dir=str(pdf_path.parent),
        ieee_downloader_timeout_seconds=30,
        pdf_asset_dir=str(tmp_path / "assets"),
        extracted_text_dir=str(tmp_path / "text"),
        pdf_max_upload_bytes=10_000_000,
    )
    fake_settings.provider_timeout_seconds = 20
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.settings",
        fake_settings,
    )
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.IeeeBrowserDownloader.download",
        lambda self, query: IeeeDownloadResult("downloaded", "ok", pdf_path),
    )
    monkeypatch.setattr(
        "app.services.pdf_service.extract_pdf_text",
        lambda pdf_path, output_path: output_path.write_text("IEEE paper text", encoding="utf-8"),
    )

    result = TaskRunner(
        task_repository=TaskRepository(db),
        task_manager=TaskManager(),
    ).run_once()

    item = db.get(DeepAnalysisQueueItem, item_id)
    assert result.id == task.id
    assert result.status == "succeeded"
    assert item.pdf_asset_id is not None
    assert item.pdf_readiness_status == "reused_pdf"
    assert item.pdf_source == "ieee_browser_helper"
    assert db.query(PdfAssetPublicationLink).filter_by(
        pdf_asset_id=item.pdf_asset_id,
        publication_id=item.citing_publication_id,
    ).count() == 1
    db.close()


def test_ieee_download_task_records_login_required(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="download_ieee_pdf",
        payload_json=json.dumps({"queue_item_id": item_id}),
        status="running",
    )
    db.add(task)
    db.commit()
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.settings",
        SimpleNamespace(
            ieee_downloader_command="ieee-download",
            ieee_downloader_work_dir=str(tmp_path),
            ieee_downloader_download_dir=str(tmp_path / "downloads"),
            ieee_downloader_timeout_seconds=30,
            pdf_asset_dir=str(tmp_path / "assets"),
            extracted_text_dir=str(tmp_path / "text"),
            pdf_max_upload_bytes=10_000_000,
            provider_timeout_seconds=20,
        ),
    )
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.IeeeBrowserDownloader.download",
        lambda self, query: IeeeDownloadResult(
            "requires_login", "Institutional Sign In", reason="ieee_session_required"
        ),
    )

    handle_download_ieee_pdf(db, task)

    item = db.get(DeepAnalysisQueueItem, item_id)
    assert item.pdf_access_status == "requires_login"
    assert item.requires_login_reason == "ieee_browser_session_required"
    assert "机构登录" in task.stage_message
    db.close()


def test_ieee_queue_helper_shows_automatic_download_action(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, _item_id = _ieee_item(db, tmp_path)
    db.close()
    original_settings = __import__(
        "app.services.scholar_queue_service", fromlist=["settings"]
    ).settings
    fake_settings = SimpleNamespace(
        ieee_downloader_command="ieee-download",
        ieee_downloader_portal_url="http://127.0.0.1:8090/",
        pdf_library_dirs=original_settings.pdf_library_dirs,
        pdf_index_path=original_settings.pdf_index_path,
        pdf_max_scan_files=original_settings.pdf_max_scan_files,
        pdf_match_threshold=original_settings.pdf_match_threshold,
    )
    monkeypatch.setattr("app.services.scholar_queue_service.settings", fake_settings)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            f"/scholar-sessions/{session_id}/queue?view=need_pdf"
        )
        assert response.status_code == 200
        assert "通过 IEEE 浏览器助手自动下载" in response.text
        assert "主系统不接收或保存 IEEE 账号密码" in response.text
        assert "打开 IEEE 助手登录页" in response.text
    finally:
        app.dependency_overrides.clear()


def test_unified_queue_download_service_uses_ieee_after_open_discovery(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    _session_id, item_id = _ieee_item(db, tmp_path)
    pdf_path = tmp_path / "downloads" / "paper.pdf"
    pdf_path.parent.mkdir()
    pdf_path.write_bytes(VALID_PDF_BYTES)

    class NoOpenPdf:
        def discover_and_download_for_queue_item(self, *, item_id, pdf_service):
            return {"status": "requires_login"}

    class FakeIeee:
        def download(self, query):
            return IeeeDownloadResult("downloaded", "ok", pdf_path)

    monkeypatch.setattr(
        "app.services.pdf_service.extract_pdf_text",
        lambda pdf_path, output_path: output_path.write_text(
            "IEEE text", encoding="utf-8"
        ),
    )
    service = QueuePdfDownloadService(
        db,
        pdf_service=__import__(
            "tests.test_pdf_discovery", fromlist=["_pdf_service"]
        )._pdf_service(db, tmp_path),
        discovery_service=NoOpenPdf(),
        ieee_downloader=FakeIeee(),
    )

    result = service.download_pdf_for_queue_item(
        item_id,
        allow_restricted_browser=True,
    )

    item = db.get(DeepAnalysisQueueItem, item_id)
    assert result.status == "downloaded"
    assert result.source == "ieee_browser_helper"
    assert item.pdf_asset_id == result.pdf_asset_id
    assert item.pdf_discovery_status == "downloaded"
    db.close()


def test_batch_pdf_download_continues_and_records_per_item_failure(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    session_id, first_id = _ieee_item(db, tmp_path)
    first = db.get(DeepAnalysisQueueItem, first_id)
    second_publication = Publication(
        title="Second IEEE Paper",
        doi="10.1109/TIM.2025.7654321",
        venue="IEEE TIM",
        authors_json="[]",
    )
    db.add(second_publication)
    db.flush()
    second_edge = CitationEdge(
        scholar_session_id=session_id,
        cited_publication_id=first.cited_publication_id,
        citing_publication_id=second_publication.id,
        provider_name="fake",
    )
    db.add(second_edge)
    db.flush()
    second = DeepAnalysisQueueItem(
        scholar_session_id=session_id,
        citation_edge_id=second_edge.id,
        cited_publication_id=first.cited_publication_id,
        citing_publication_id=second_publication.id,
        queue_status="pending",
        priority_score=1,
        priority_reasons_json="[]",
        third_party_status="third_party",
        self_citation_status="not_self_citation",
        pdf_readiness_status="need_pdf",
        citing_paper_title=second_publication.title,
        cited_paper_title=first.cited_paper_title,
        citing_authors_json="[]",
        cited_authors_json="[]",
        provider_name="fake",
    )
    db.add(second)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        payload_json="{}",
        status="running",
    )
    db.add(task)
    db.commit()

    class FakeBatchService:
        def __init__(self, db):
            pass

        def download_pdf_for_queue_item(
            self, item_id, *, allow_restricted_browser=False, force=False
        ):
            assert allow_restricted_browser is True
            if item_id == first_id:
                return PdfDownloadResult(
                    item_id,
                    "downloaded",
                    source="ieee_browser_helper",
                    pdf_asset_id=10,
                )
            return PdfDownloadResult(
                item_id,
                "failed",
                source="ieee_browser_helper",
                reason="title_match_failed",
            )

    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.QueuePdfDownloadService",
        FakeBatchService,
    )

    handle_discover_pdfs_for_queue(db, task)

    summary = json.loads(task.payload_json)["result_summary"]
    assert summary["downloaded"] == 1
    assert summary["ieee_downloaded"] == 1
    assert summary["failed"] == 1
    assert summary["failures"] == [
        {
            "queue_item_id": second.id,
            "citing_paper_title": "Second IEEE Paper",
            "reason": "title_match_failed",
        }
    ]
    db.close()
