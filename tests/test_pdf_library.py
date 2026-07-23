from pathlib import Path

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
    PaperAnalysisSession,
    PdfAsset,
    PdfAssetPublicationLink,
    PdfLibraryEntry,
    Publication,
    ScholarAnalysisSession,
    ScholarPublication,
)
from app.pdf.index import extract_arxiv_id_from_filename, extract_doi_from_filename
from app.pdf.match import normalize_title_for_match
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_library_service import PdfLibraryService, get_pdf_library_service
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from app.repositories.task_repo import TaskRepository


PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


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


def write_pdf(path: Path, content: bytes = PDF_BYTES) -> Path:
    path.write_bytes(content)
    return path


def make_service(db, tmp_path, library_dirs=None, threshold=0.82):
    return PdfLibraryService(
        repository=PdfRepository(db),
        library_dirs=library_dirs or [],
        index_path=tmp_path / "pdf_index.json",
        max_scan_files=100,
        match_threshold=threshold,
    )


def test_pdf_library_disabled(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[])
        status = service.get_index_status()

    assert status["enabled"] is False
    assert status["message"] == "local library disabled"


def test_rebuild_pdf_index_with_fixture_dir(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_fake.paper_Evidence_Aware_Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        index = service.rebuild_index()

    assert index.status == "succeeded"
    assert index.entry_count == 1

    with Session(db_session_factory.kw["bind"]) as db:
        status = make_service(db, tmp_path, library_dirs=[library_dir]).get_index_status()
    assert status["enabled"] is True
    assert status["entry_count"] == 1
    assert status["source_dirs"] == [library_dir.name]


def test_rebuild_pdf_index_is_repeatable_without_duplicate_entries(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    pdf_path = write_pdf(library_dir / "10.1234_fake.paper_Evidence_Aware_Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        first_index = service.rebuild_index()
        second_index = service.rebuild_index()
        entries = db.query(PdfLibraryEntry).all()
        first_status = first_index.status
        second_status = second_index.status

    assert first_status == "succeeded"
    assert second_status == "succeeded"
    assert len(entries) == 1
    assert entries[0].filename == pdf_path.name


def test_extract_doi_from_filename():
    assert (
        extract_doi_from_filename("10.1234_fake.paper_Evidence_Aware_Impact.pdf")
        == "10.1234/fake.paper"
    )


def test_extract_arxiv_from_filename():
    assert extract_arxiv_id_from_filename("arXiv_2301.12345_contexts.pdf") == "2301.12345"


def test_normalized_title_match():
    assert normalize_title_for_match(" Evidence-Aware: Academic Impact! ") == (
        "evidence aware academic impact"
    )


def test_match_publication_by_doi(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_fake.paper_Evidence_Aware_Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        publication = Publication(title="Different title", doi="10.1234/fake.paper")
        db.add(publication)
        db.commit()
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        match = service.match_publication(publication.id)

    assert match is not None
    assert match.match_score == 1.0
    assert match.match_reason == "doi"
    assert match.pdf_asset_id is not None


def test_doi_match_takes_priority_over_better_title_match(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.9999_wrong.doi_Evidence_Aware_Academic_Impact.pdf")
    write_pdf(library_dir / "10.1234_correct.doi_Completely_Different_Title.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        publication = Publication(title="Evidence-Aware Academic Impact", doi="10.1234/correct.doi")
        db.add(publication)
        db.commit()
        service = make_service(db, tmp_path, library_dirs=[library_dir], threshold=0.5)
        service.rebuild_index()
        match = service.match_publication(publication.id)

    assert match.match_reason == "doi"
    assert match.filename == "10.1234_correct.doi_Completely_Different_Title.pdf"


def test_arxiv_match_takes_priority_over_better_title_match(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "arXiv_2302.11111_Evidence_Aware_Academic_Impact.pdf")
    write_pdf(library_dir / "arXiv_2301.12345_Completely_Different_Title.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        publication = Publication(
            title="Evidence-Aware Academic Impact",
            semantic_scholar_id="arXiv:2301.12345",
        )
        db.add(publication)
        db.commit()
        service = make_service(db, tmp_path, library_dirs=[library_dir], threshold=0.5)
        service.rebuild_index()
        match = service.match_publication(publication.id)

    assert match.match_reason == "arxiv_id"
    assert match.filename == "arXiv_2301.12345_Completely_Different_Title.pdf"


def test_match_publication_by_title(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        publication = Publication(title="Evidence-Aware Academic Impact", year=2024)
        db.add(publication)
        db.commit()
        service = make_service(db, tmp_path, library_dirs=[library_dir], threshold=0.75)
        service.rebuild_index()
        match = service.match_publication(publication.id)

    assert match is not None
    assert match.match_reason == "title"
    assert match.match_score >= 0.75
    assert match.pdf_asset_id is not None


def test_title_match_below_threshold_is_not_attached(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "Totally Different Local Paper.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        publication = Publication(title="Evidence-Aware Academic Impact")
        db.add(publication)
        db.commit()
        service = make_service(db, tmp_path, library_dirs=[library_dir], threshold=0.95)
        service.rebuild_index()
        match = service.match_publication(publication.id)

    assert match is None


def test_manual_upload_not_overwritten(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_fake.paper_Evidence_Aware_Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(query_text="target", query_kind="title")
        publication = Publication(title="Evidence-Aware Academic Impact", doi="10.1234/fake.paper")
        manual_asset = PdfAsset(
            storage_path=str(tmp_path / "manual.pdf"),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="manual",
            source_type="upload",
            extract_status="pending",
        )
        db.add_all([session, publication, manual_asset])
        db.flush()
        manual_asset_id = manual_asset.id
        citing_paper = CitingPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            analysis_status="discovered",
            pdf_asset_id=manual_asset.id,
        )
        db.add(citing_paper)
        db.commit()

        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        matched_count = service.match_session_pdfs("paper_analysis", session.id)
        db.refresh(citing_paper)

    assert matched_count == 0
    assert citing_paper.pdf_asset_id == manual_asset_id


def test_no_scan_in_request_thread():
    source = (Path.cwd() / "app/routers/pdf_library.py").read_text(encoding="utf-8")
    assert "rebuild_index(" not in source
    assert "scan_pdf_library" not in source


def test_redacted_paths_in_response(client, db_session_factory, tmp_path):
    library_dir = tmp_path / "secret-library"
    library_dir.mkdir()
    write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            service = make_service(db, tmp_path, library_dirs=[library_dir])
            service.rebuild_index()
            yield service
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "Evidence Aware Academic Impact.pdf" in response.text
    assert str(tmp_path) not in response.text
    assert str(library_dir) not in response.text


def test_pdf_library_page_uses_dashboard_layout(client, db_session_factory, tmp_path):
    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            yield make_service(db, tmp_path, library_dirs=[])
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "app-shell" in response.text
    assert "stat-card" in response.text
    assert "本地 PDF 库" in response.text


def test_pdf_library_empty_state_in_chinese(client, db_session_factory, tmp_path):
    library_dir = tmp_path / "empty-library"
    library_dir.mkdir()

    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            yield make_service(db, tmp_path, library_dirs=[library_dir])
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "尚未索引到 PDF" in response.text
    assert "请确认来源目录存在且包含 PDF 文件" in response.text


def test_local_pdf_library_relative_path_warning(client, db_session_factory, tmp_path):
    relative_dir = Path("__missing_pdf_library_dir_for_test__")

    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            yield make_service(db, tmp_path, library_dirs=[relative_dir])
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "当前是相对路径，实际扫描位置取决于程序启动目录。建议使用绝对路径。" in response.text
    assert "目录不存在" in response.text


def test_redacted_paths_in_json_response(client, db_session_factory, tmp_path):
    library_dir = tmp_path / "secret-library"
    library_dir.mkdir()
    write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            service = make_service(db, tmp_path, library_dirs=[library_dir])
            service.rebuild_index()
            yield service
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library.json")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_dirs"] == ["secret-library"]
    assert payload["entries"][0]["filename"] == "Evidence Aware Academic Impact.pdf"
    assert str(tmp_path) not in response.text
    assert str(library_dir) not in response.text


def test_match_session_pdfs_task_for_paper_session(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_fake.paper_Evidence_Aware_Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(query_text="target", query_kind="title")
        publication = Publication(title="Evidence-Aware Academic Impact", doi="10.1234/fake.paper")
        db.add_all([session, publication])
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            analysis_status="discovered",
        )
        db.add(citing_paper)
        db.commit()

        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        service.enqueue_match_session_pdfs("paper_analysis", session.id)
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        db.refresh(citing_paper)

    assert task.status == "succeeded"
    assert task.progress_total == 1
    assert citing_paper.pdf_asset_id is not None


def test_match_publication_reuses_pdf_asset_and_links_by_sha256(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_fake.paper_Evidence_Aware_Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        publication = Publication(title="Evidence-Aware Academic Impact", doi="10.1234/fake.paper")
        db.add(publication)
        db.commit()
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        first_match = service.match_publication(publication.id)
        second_match = service.match_publication(publication.id)
        assets = db.query(PdfAsset).all()
        entry = db.query(PdfLibraryEntry).one()

    assert first_match.pdf_asset_id == second_match.pdf_asset_id
    assert len(assets) == 1
    assert assets[0].sha256 == entry.sha256
    assert assets[0].source_type == "local_library"


def test_pdf_reuse_does_not_duplicate_same_sha256(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        service.rebuild_index()
        assets = db.query(PdfAsset).all()

    assert len(assets) == 1


def test_local_library_scan_imports_pdf_asset(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    pdf_path = write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        asset = db.query(PdfAsset).one()

    assert asset.original_filename == pdf_path.name
    assert asset.source_type == "local_library"
    assert asset.sha256


def test_pdf_library_page_shows_asset_pool_count(client, db_session_factory, tmp_path):
    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            asset = PdfAsset(
                storage_path=str(tmp_path / "uploaded.pdf"),
                original_filename="uploaded.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="asset-pool-page",
                source_type="upload",
                extract_status="succeeded",
            )
            db.add(asset)
            db.commit()
            yield make_service(db, tmp_path, library_dirs=[])
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "PDF 资产池" in response.text
    assert "uploaded.pdf" in response.text
    assert "PDF asset pool count 1" in response.text


def test_pdf_library_page_separates_asset_pool_and_scan_index(
    client,
    db_session_factory,
    tmp_path,
):
    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            yield make_service(db, tmp_path, library_dirs=[])
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "PDF 资产池" in response.text
    assert "本地目录扫描来源" in response.text


def test_pdf_library_shows_uploaded_assets_when_scan_index_empty(
    client,
    db_session_factory,
    tmp_path,
):
    def override_get_pdf_library_service():
        db = db_session_factory()
        try:
            asset = PdfAsset(
                storage_path=str(tmp_path / "uploaded.pdf"),
                original_filename="uploaded.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="asset-pool-no-index",
                source_type="upload",
                extract_status="succeeded",
            )
            db.add(asset)
            db.flush()
            db.add(
                PdfAssetPublicationLink(
                    pdf_asset_id=asset.id,
                    doi="10.1000/uploaded",
                    normalized_title="uploaded paper",
                    raw_title="Uploaded Paper",
                    match_method="manual_upload_for_queue_item",
                    match_score=1.0,
                    is_verified=True,
                )
            )
            db.commit()
            yield make_service(db, tmp_path, library_dirs=[])
        finally:
            db.close()

    app.dependency_overrides[get_pdf_library_service] = override_get_pdf_library_service
    try:
        response = client.get("/pdf-library")
    finally:
        app.dependency_overrides.pop(get_pdf_library_service, None)

    assert response.status_code == 200
    assert "uploaded.pdf" in response.text
    assert "10.1000/uploaded" in response.text
    assert "本地目录暂无扫描条目" in response.text
    assert "系统已有上传 PDF 资产" in response.text


def test_scan_only_configured_directories_and_does_not_delete_files(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    outside_dir = tmp_path / "outside"
    library_dir.mkdir()
    outside_dir.mkdir()
    inside_pdf = write_pdf(library_dir / "Inside Configured Dir.pdf")
    outside_pdf = write_pdf(outside_dir / "Outside Configured Dir.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[library_dir])
        service.rebuild_index()
        filenames = [entry.filename for entry in db.query(PdfLibraryEntry).all()]

    assert filenames == [inside_pdf.name]
    assert inside_pdf.exists()
    assert outside_pdf.exists()


def test_database_does_not_store_pdf_binary(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        service = make_service(db, tmp_path, library_dirs=[library_dir], threshold=0.75)
        service.rebuild_index()
        publication = Publication(title="Evidence-Aware Academic Impact")
        db.add(publication)
        db.commit()
        service.match_publication(publication.id)
        entries = db.query(PdfLibraryEntry).all()
        assets = db.query(PdfAsset).all()

    serialized_values = " ".join(
        [
            " ".join(str(value) for value in entry.__dict__.values())
            for entry in entries
        ]
        + [
            " ".join(str(value) for value in asset.__dict__.values())
            for asset in assets
        ]
    )
    assert PDF_BYTES.decode("latin1") not in serialized_values


def test_match_session_pdfs_for_scholar_session(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "Evidence Aware Academic Impact.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=1,
            citation_edge_count=0,
        )
        publication = Publication(title="Evidence-Aware Academic Impact")
        db.add_all([session, publication])
        db.flush()
        scholar_publication = ScholarPublication(
            scholar_session_id=session.id,
            publication_id=publication.id,
            local_code="S001",
            title=publication.title,
        )
        db.add(scholar_publication)
        db.commit()

        service = make_service(db, tmp_path, library_dirs=[library_dir], threshold=0.75)
        service.rebuild_index()
        matched_count = service.match_session_pdfs("scholar_analysis", session.id)
        db.refresh(scholar_publication)

    assert matched_count == 1
    assert scholar_publication.pdf_asset_id is not None
