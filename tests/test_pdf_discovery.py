import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AnalysisTask, CitationEdge, DeepAnalysisQueueItem, PdfAsset, Publication
from app.pdf.arxiv import extract_arxiv_identifier, is_valid_arxiv_identifier
from app.pdf.publisher import classify_publisher_from_doi_or_url
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_discovery_service import DownloadFailure, PdfCandidate, PdfDiscoveryService
from app.services.pdf_service import PdfService
from app.tasks.handlers.discover_pdfs_for_queue import handle_discover_pdfs_for_queue
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


class FakeResponse:
    def __init__(self, content: bytes, content_type: str = "application/pdf") -> None:
        self.content = content
        self.headers = {"content-type": content_type}

    def read(self, _size: int = -1) -> bytes:
        return self.content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _pdf_service(db, tmp_path):
    return PdfService(
        repository=PdfRepository(db),
        pdf_asset_dir=Path(tmp_path / "pdf_assets"),
        extracted_text_dir=Path(tmp_path / "extracted_text"),
        max_upload_bytes=10_000_000,
    )


def test_pdf_discovery_finds_arxiv_pdf(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.48550/arXiv.2401.12345"
        db.commit()

        candidates = PdfDiscoveryService(db).discover_pdf_candidates_for_queue_item(item_id)

        assert candidates
        assert candidates[0].source == "arxiv"
        assert candidates[0].is_open_access is True
        assert candidates[0].url.endswith("2401.12345.pdf")
    finally:
        db.close()


def test_acm_doi_not_parsed_as_arxiv_id(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.title = "MoiréVision: A Generalized Mechanism for Motion Sensing"
        publication.doi = "10.1145/3636534.3649374"
        db.commit()

        candidates = PdfDiscoveryService(db).discover_pdf_candidates_for_queue_item(item_id)

        assert extract_arxiv_identifier(publication.doi) is None
        assert all(candidate.source != "arxiv" for candidate in candidates)
        assert all("arxiv.org" not in candidate.url for candidate in candidates)
    finally:
        db.close()


def test_invalid_arxiv_month_rejected():
    assert is_valid_arxiv_identifier("6534.36493") is False
    assert extract_arxiv_identifier("arXiv:6534.36493") is None


def test_valid_arxiv_id_accepted():
    assert extract_arxiv_identifier("arXiv:2401.12345v2") == "2401.12345v2"
    assert extract_arxiv_identifier("https://arxiv.org/abs/cs/0601001") == "cs/0601001"


def test_arxiv_buttons_hidden_when_identifier_invalid(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        item.pdf_source = "arxiv"
        item.pdf_source_url = "https://arxiv.org/abs/6534.36493"
        item.publisher_landing_url = item.pdf_source_url
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert response.status_code == 200
    assert "打开 arXiv" not in response.text
    assert "https://arxiv.org/abs/6534.36493" not in response.text
    assert "https://doi.org/10.1145/3636534.3649374" in response.text
    assert "已移除无效的 arXiv 标识" in response.text


def test_pdf_source_not_arxiv_for_acm_doi(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        db.commit()

        result = PdfDiscoveryService(db).discover_and_download_for_queue_item(
            item_id=item_id,
            pdf_service=_pdf_service(db, tmp_path),
        )

        db.refresh(item)
        assert result["status"] == "requires_login"
        assert item.pdf_source == "acm_dl"
        assert item.pdf_source != "arxiv"
    finally:
        db.close()


def test_existing_invalid_arxiv_identifier_is_cleared(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        item.pdf_source = "arxiv"
        item.pdf_source_url = "https://arxiv.org/pdf/6534.36493.pdf"
        edge = db.get(CitationEdge, item.citation_edge_id)
        edge.edge_meta_json = json.dumps(
            {"arxiv_identifier": "6534.36493", "pdf_source": "arxiv"}
        )
        db.commit()

        PdfDiscoveryService(db).discover_pdf_candidates_for_queue_item(item_id)

        db.refresh(item)
        db.refresh(edge)
        assert item.pdf_source == "publisher_candidate"
        assert item.pdf_source_url is None
        assert item.pdf_access_status == "manual_download_needed"
        assert "arxiv_identifier" not in json.loads(edge.edge_meta_json)
        assert json.loads(edge.edge_meta_json)["pdf_source"] == "unknown"
    finally:
        db.close()


def test_acm_doi_classified_as_acm_dl():
    publisher = classify_publisher_from_doi_or_url(
        "10.1145/3636534.3649374",
        None,
    )

    assert publisher.source == "acm_dl"
    assert publisher.publisher == "ACM Digital Library"
    assert publisher.landing_url == "https://dl.acm.org/doi/10.1145/3636534.3649374"
    assert publisher.fallback_url == "https://doi.org/10.1145/3636534.3649374"


def test_ieee_doi_classified_as_ieee_xplore():
    publisher = classify_publisher_from_doi_or_url(
        "10.1109/TIM.2025.1234567",
        "https://ieeexplore.ieee.org/document/1234567",
    )

    assert publisher.source == "ieee_xplore"
    assert publisher.publisher == "IEEE Xplore"
    assert publisher.landing_url == "https://ieeexplore.ieee.org/document/1234567"


def test_openalex_requires_login_not_primary_download_button(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        item.pdf_source = "openalex"
        item.pdf_source_url = "https://openalex.org/W123456789"
        item.pdf_access_status = "requires_login"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert response.status_code == 200
    assert "打开 OpenAlex OA" not in response.text
    assert "查看 OpenAlex OA 元数据" in response.text
    assert response.text.index("打开 ACM Digital Library") < response.text.index("查看 OpenAlex OA 元数据")


def test_acm_doi_page_shows_acm_dl_and_doi_buttons(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        publication = db.get(Publication, db.get(DeepAnalysisQueueItem, item_id).citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "未发现可直接自动下载的开放 PDF" in response.text
    assert "通常需要 ACM 或学校/机构权限" in response.text
    assert "打开 ACM Digital Library" in response.text
    assert "打开 DOI 页面" in response.text
    assert "上传 PDF" in response.text


def test_ieee_doi_page_shows_ieee_or_doi_button(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        publication = db.get(Publication, db.get(DeepAnalysisQueueItem, item_id).citing_publication_id)
        publication.doi = "10.1109/TIM.2025.1234567"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "IEEE Xplore" in response.text
    assert "打开 DOI 页面" in response.text
    assert "通常需要 IEEE 或学校/机构权限" in response.text


def test_only_direct_pdf_open_access_can_auto_download(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        edge = db.get(CitationEdge, item.citation_edge_id)
        edge.edge_meta_json = json.dumps(
            {
                "open_access_pdf_url": "https://example.test/paper.pdf",
                "is_open_access": True,
            }
        )
        db.commit()

        candidates = PdfDiscoveryService(db).discover_pdf_candidates_for_queue_item(item_id)

        direct = next(candidate for candidate in candidates if candidate.url.endswith("paper.pdf"))
        assert direct.url_type == "direct_pdf"
        assert direct.can_auto_download is True
    finally:
        db.close()


def test_metadata_page_not_auto_downloadable(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        edge = db.get(CitationEdge, item.citation_edge_id)
        edge.edge_meta_json = json.dumps(
            {
                "open_access_pdf_url": "https://openalex.org/W123456789",
                "is_open_access": True,
                "pdf_source": "openalex",
            }
        )
        db.commit()

        candidates = PdfDiscoveryService(db).discover_pdf_candidates_for_queue_item(item_id)

        metadata = next(candidate for candidate in candidates if "openalex.org" in candidate.url)
        assert metadata.url_type == "metadata_page"
        assert metadata.can_auto_download is False
        assert metadata.access_status == "unknown"
    finally:
        db.close()


def test_invalid_arxiv_identifier_does_not_hide_publisher_fallback(
    client, db_session_factory, tmp_path
):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        item.pdf_source = "arxiv"
        item.pdf_source_url = "https://arxiv.org/abs/6534.36493"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "打开 arXiv" not in response.text
    assert "打开 ACM Digital Library" in response.text
    assert "打开 DOI 页面" in response.text


def test_existing_openalex_requires_login_with_acm_doi_uses_acm_fallback(
    client, db_session_factory, tmp_path
):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3636534.3649374"
        item.pdf_source = "openalex"
        item.pdf_source_url = "https://openalex.org/W987654321"
        item.pdf_access_status = "requires_login"
        item.pdf_discovery_status = "requires_login"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "打开 ACM Digital Library" in response.text
    assert "打开 DOI 页面" in response.text
    assert "OpenAlex 是元数据来源" in response.text


def test_pdf_download_rejects_html_login_page(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *args, **kwargs: FakeResponse(b"<html>login</html>", "text/html"),
        )
        candidate = PdfCandidate(
            title="Login Required",
            doi=None,
            source="publisher_open_access",
            url="https://example.test/login",
            is_open_access=True,
            license=None,
            confidence=0.8,
            requires_login=False,
            reason="test",
        )

        result = PdfDiscoveryService(db).download_if_allowed(
            candidate,
            pdf_service=_pdf_service(db, tmp_path),
        )

        assert isinstance(result, DownloadFailure)
        assert result.error_kind == "requires_login"
    finally:
        db.close()


def test_pdf_download_accepts_valid_pdf_and_records_source_license(
    db_session_factory, tmp_path, monkeypatch
):
    db = db_session_factory()
    try:
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *args, **kwargs: FakeResponse(VALID_PDF_BYTES, "application/pdf"),
        )
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("downloaded pdf text", encoding="utf-8"),
        )
        candidate = PdfCandidate(
            title="Open Access Paper",
            doi="10.1/oa",
            source="openalex_oa",
            url="https://example.test/paper.pdf",
            is_open_access=True,
            license="cc-by",
            confidence=0.95,
            requires_login=False,
            reason="metadata_open_access_pdf_url",
        )

        result = PdfDiscoveryService(db).download_if_allowed(
            candidate,
            pdf_service=_pdf_service(db, tmp_path),
        )

        assert isinstance(result, PdfAsset)
        assert result.source_type == "openalex_oa"
        assert result.source_url == "https://example.test/paper.pdf"
        assert result.license == "cc-by"
        assert result.extract_status == "succeeded"
    finally:
        db.close()


def test_acm_ieee_requires_login_not_auto_downloaded(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1145/3494975"
        db.commit()

        result = PdfDiscoveryService(db).discover_and_download_for_queue_item(
            item_id=item_id,
            pdf_service=_pdf_service(db, tmp_path),
        )

        db.refresh(item)
        assert result["status"] == "requires_login"
        assert item.pdf_discovery_status == "requires_login"
        assert item.pdf_asset_id is None
    finally:
        db.close()


def test_requires_login_page_shows_manual_upload_button(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.pdf_discovery_status = "requires_login"
        item.pdf_source = "publisher_landing_page"
        item.pdf_source_url = "https://doi.org/10.1145/3494975"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert response.status_code == 200
    assert "系统不会保存账号密码" in response.text
    assert "打开官方页面" in response.text
    assert "上传 PDF" in response.text


def test_pdf_candidate_displays_specific_publisher_name(client, db_session_factory, tmp_path):
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
    assert "ACM Digital Library" in response.text
    assert "打开 Publisher 页面" not in response.text


def test_pdf_candidate_has_doi_url(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        publication = db.get(Publication, db.get(DeepAnalysisQueueItem, item_id).citing_publication_id)
        publication.doi = "10.1109/example"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "https://doi.org/10.1109/example" in response.text
    assert "打开 DOI 页面" in response.text


def test_pdf_candidate_has_google_scholar_search_url(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, _item_id = seed_queue_item(
            db,
            tmp_path,
            pdf_ready=False,
            title="Paper With Missing PDF",
        )
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "https://scholar.google.com/scholar?q=Paper+With+Missing+PDF" in response.text
    assert "Google Scholar" in response.text


def test_acm_page_marked_requires_login(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        publication = db.get(Publication, db.get(DeepAnalysisQueueItem, item_id).citing_publication_id)
        publication.doi = "10.1145/3494975"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "ACM Digital Library" in response.text
    assert "requires_login" in response.text
    assert "需要登录，请通过浏览器/学校图书馆权限下载后上传。" in response.text


def test_ieee_page_marked_requires_login(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        publication = db.get(Publication, db.get(DeepAnalysisQueueItem, item_id).citing_publication_id)
        publication.doi = "10.1109/example"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "IEEE Xplore" in response.text
    assert "requires_login" in response.text


def test_open_access_candidate_shows_auto_download_button(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        edge = db.get(CitationEdge, db.get(DeepAnalysisQueueItem, item_id).citation_edge_id)
        edge.edge_meta_json = json.dumps(
            {
                "open_access_pdf_url": "https://openalex.org/oa.pdf",
                "is_open_access": True,
                "license": "cc-by",
            }
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "OpenAlex OA" in response.text
    assert "open_access" in response.text
    assert "自动下载开放 PDF" in response.text


def test_pdf_discovery_diagnostics_shown_when_no_pdf_found(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, _item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "PDF 查找诊断" in response.text
    assert "tried_sources" in response.text
    assert "found_candidates_count" in response.text
    assert "no_open_access_pdf_found" in response.text


def test_queue_pdf_helper_not_generic_publisher_only(client, db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        edge = db.get(CitationEdge, db.get(DeepAnalysisQueueItem, item_id).citation_edge_id)
        edge.edge_meta_json = json.dumps(
            {
                "landing_page_url": "https://ieeexplore.ieee.org/document/123",
            }
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=need_pdf")

    assert "IEEE Xplore" in response.text
    assert "打开 Publisher 页面" not in response.text


def test_queue_item_binds_downloaded_pdf(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        _session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        edge = db.get(CitationEdge, db.get(DeepAnalysisQueueItem, item_id).citation_edge_id)
        edge.edge_meta_json = json.dumps(
            {
                "open_access_pdf_url": "https://example.test/oa.pdf",
                "is_open_access": True,
                "license": "cc-by",
            }
        )
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *args, **kwargs: FakeResponse(VALID_PDF_BYTES, "application/pdf"),
        )
        monkeypatch.setattr(
            "app.services.pdf_service.extract_pdf_text",
            lambda pdf_path, output_path: output_path.write_text("downloaded pdf text", encoding="utf-8"),
        )

        result = PdfDiscoveryService(db).discover_and_download_for_queue_item(
            item_id=item_id,
            pdf_service=_pdf_service(db, tmp_path),
        )

        item = db.get(DeepAnalysisQueueItem, item_id)
        assert result["status"] == "downloaded"
        assert item.pdf_asset_id is not None
        assert item.pdf_readiness_status == "reused_pdf"
        assert item.pdf_discovery_status == "downloaded"
    finally:
        db.close()


def test_pdf_discovery_task_summary(db_session_factory, tmp_path, monkeypatch):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="discover_pdfs_for_queue",
            status="running",
        )
        db.add(task)
        db.commit()

        class FakeDownloadService:
            def __init__(self, *args, **kwargs):
                pass

            def download_pdf_for_queue_item(
                self, item_id, *, allow_restricted_browser=False, force=False
            ):
                assert allow_restricted_browser is True
                from app.services.queue_pdf_download_service import PdfDownloadResult

                return PdfDownloadResult(
                    item_id,
                    "downloaded",
                    source="openalex_oa",
                    pdf_asset_id=1,
                )

        monkeypatch.setattr(
            "app.tasks.handlers.discover_pdfs_for_queue.QueuePdfDownloadService",
            FakeDownloadService,
        )

        handle_discover_pdfs_for_queue(db, task)

        assert "total_items=1" in task.stage_message
        assert "downloaded=1" in task.stage_message
        assert "open_access_downloaded=1" in task.stage_message
        assert task.progress_current == 1
        assert task.progress_total == 1
    finally:
        db.close()


def test_queue_page_shows_batch_pdf_download_summary_and_failure_reasons(
    db_session_factory,
    client,
    tmp_path,
):
    db = db_session_factory()
    try:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        summary = {
            "total_items": 2,
            "downloaded": 1,
            "open_access_downloaded": 0,
            "ieee_downloaded": 1,
            "requires_login": 0,
            "no_pdf_found": 0,
            "failed": 1,
            "skipped": 0,
            "failure_count": 1,
            "failures": [
                {
                    "queue_item_id": item_id,
                    "citing_paper_title": "Failed IEEE Paper",
                    "reason": "title_match_failed",
                }
            ],
        }
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="discover_pdfs_for_queue",
            payload_json=json.dumps({"result_summary": summary}),
            status="succeeded",
            stage_message="downloaded=1; failed=1",
            progress_current=2,
            progress_total=2,
        )
        db.add(task)
        db.commit()

        response = client.get(
            f"/scholar-sessions/{session_id}/queue?discover_task_id={task.id}"
        )

        assert response.status_code == 200
        assert "自动查找 / 下载所有 PDF" in response.text
        assert "IEEE 助手" in response.text
        assert "Failed IEEE Paper" in response.text
        assert "title_match_failed" in response.text
    finally:
        db.close()
