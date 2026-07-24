import json
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisTask,
    CitationEdge,
    CitingPaper,
    DeepAnalysisQueueItem,
    PaperAnalysisSession,
    PdfAsset,
    PdfAssetPublicationLink,
    Publication,
    ScholarAnalysisSession,
)
from app.models.constants import is_pdf_ready_status
from app.repositories.pdf_repo import PdfRepository
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.repositories.task_repo import TaskRepository
from app.routers.scholar_queue import get_pdf_service
from app.services.pdf_service import PdfService
from app.services.pdf_library_service import PdfLibraryService
from app.services.scholar_queue_service import ScholarQueueService
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from tests.test_pdf_library import PDF_BYTES, write_pdf
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


def make_queue_service(db, tmp_path, library_dirs=None, threshold=0.82):
    pdf_library_service = PdfLibraryService(
        repository=PdfRepository(db),
        library_dirs=library_dirs or [],
        index_path=tmp_path / "pdf_index.json",
        max_scan_files=100,
        match_threshold=threshold,
    )
    return ScholarQueueService(
        repository=ScholarQueueRepository(db),
        pdf_library_service=pdf_library_service,
    )


def seed_scholar_edges(db, *, include_self_edge=False):
    session = ScholarAnalysisSession(
        display_name="Grace Hopper",
        status="expanded",
        publication_count=1,
        citation_edge_count=0,
    )
    cited = Publication(
        title="Cited Scholar Paper",
        year=2021,
        venue="Journal of Scholarly Systems",
        authors_json=json.dumps(["Grace Hopper", "Avery Stone"]),
    )
    third_party_citing = Publication(
        title="Independent Citing Paper",
        year=2025,
        venue="Science",
        doi="10.1234/independent.citing",
        authors_json=json.dumps(["Lin Chen", "Maya Patel"]),
    )
    db.add_all([session, cited, third_party_citing])
    db.flush()
    third_party_edge = CitationEdge(
        scholar_session_id=session.id,
        cited_publication_id=cited.id,
        citing_publication_id=third_party_citing.id,
        provider_name="fake",
        self_citation_status="unknown",
        third_party_status="third_party",
    )
    db.add(third_party_edge)

    self_edge = None
    if include_self_edge:
        self_citing = Publication(
            title="Self Citing Paper",
            year=2022,
            venue="Workshop Notes",
            authors_json=json.dumps(["Grace Hopper", "Someone Else"]),
        )
        db.add(self_citing)
        db.flush()
        self_edge = CitationEdge(
            scholar_session_id=session.id,
            cited_publication_id=cited.id,
            citing_publication_id=self_citing.id,
            provider_name="fake",
            self_citation_status="unknown",
            third_party_status="ambiguous",
        )
        db.add(self_edge)

    db.commit()
    return session.id, cited.id, third_party_citing.id, third_party_edge.id, (
        self_edge.id if self_edge else None
    )


def test_build_scholar_queue_from_citation_edges(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, cited_id, citing_id, edge_id, _ = seed_scholar_edges(db)
        items = make_queue_service(db, tmp_path).build_queue(session_id)

    assert len(items) == 1
    assert items[0].scholar_session_id == session_id
    assert items[0].citation_edge_id == edge_id
    assert items[0].cited_publication_id == cited_id
    assert items[0].citing_publication_id == citing_id
    assert items[0].queue_status == "pending"
    assert items[0].citing_paper_title == "Independent Citing Paper"
    assert items[0].cited_paper_title == "Cited Scholar Paper"
    assert items[0].priority_score > 0
    assert json.loads(items[0].priority_reasons_json)


def test_build_queue_idempotent(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        service.build_queue(session_id)
        service.build_queue(session_id)
        count = db.query(DeepAnalysisQueueItem).count()

    assert count == 1


def test_queue_item_preserves_user_review_on_rebuild(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        service.select_queue_items(session_id, [item.id])
        service.update_queue_item_review(item.id, "important", "Review this first")
        service.rebuild_queue(session_id)
        saved = db.get(DeepAnalysisQueueItem, item.id)

    assert saved.user_review_status == "important"
    assert saved.user_note == "Review this first"
    assert saved.queue_status == "selected"


def test_citation_edge_count_matches_queue_item_count(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        service.build_queue(session_id)
        edge_count = db.query(CitationEdge).filter_by(scholar_session_id=session_id).count()
        queue_count = db.query(DeepAnalysisQueueItem).filter_by(
            scholar_session_id=session_id
        ).count()

    assert edge_count == 2
    assert queue_count == edge_count


def test_queue_scores_third_party_higher_than_self_citation(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        items = make_queue_service(db, tmp_path).build_queue(session_id)
        third_party = next(item for item in items if item.third_party_status == "third_party")
        self_citation = next(item for item in items if item.self_citation_status == "self_citation")

    assert third_party.priority_score > self_citation.priority_score


def test_queue_marks_pdf_ready_for_manual_pdf(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _cited_id, citing_id, *_ = seed_scholar_edges(db)
        paper_session = PaperAnalysisSession(query_text="manual", query_kind="title")
        asset = PdfAsset(
            storage_path=str(tmp_path / "manual.pdf"),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="manual",
            source_type="upload",
            extract_status="pending",
        )
        db.add_all([paper_session, asset])
        db.flush()
        asset_id = asset.id
        db.add(
            CitingPaper(
                paper_session_id=paper_session.id,
                publication_id=citing_id,
                pdf_asset_id=asset.id,
                analysis_status="discovered",
            )
        )
        db.commit()
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]

    assert item.pdf_readiness_status == "manual_pdf"
    assert item.pdf_asset_id == asset_id


def test_queue_marks_pdf_ready_for_local_library_pdf(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_independent.citing_Independent_Citing_Paper.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path, library_dirs=[library_dir])
        service.pdf_library_service.rebuild_index()
        item = service.build_queue(session_id)[0]

    assert item.pdf_readiness_status == "local_library_pdf"
    assert item.pdf_asset_id is not None


def test_reused_pdf_is_ready_status():
    assert is_pdf_ready_status("reused_pdf") is True
    assert is_pdf_ready_status("manual_pdf") is True
    assert is_pdf_ready_status("local_library_pdf") is True
    assert is_pdf_ready_status("need_pdf") is False


def test_manual_pdf_takes_priority_over_local_library_pdf(db_session_factory, tmp_path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    write_pdf(library_dir / "10.1234_independent.citing_Independent_Citing_Paper.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _cited_id, citing_id, *_ = seed_scholar_edges(db)
        paper_session = PaperAnalysisSession(query_text="manual", query_kind="title")
        manual_asset = PdfAsset(
            storage_path=str(tmp_path / "manual.pdf"),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="manual-priority",
            source_type="upload",
            extract_status="pending",
        )
        db.add_all([paper_session, manual_asset])
        db.flush()
        manual_asset_id = manual_asset.id
        db.add(
            CitingPaper(
                paper_session_id=paper_session.id,
                publication_id=citing_id,
                pdf_asset_id=manual_asset.id,
                analysis_status="discovered",
            )
        )
        db.commit()

        service = make_queue_service(db, tmp_path, library_dirs=[library_dir])
        service.pdf_library_service.rebuild_index()
        item = service.build_queue(session_id)[0]

    assert item.pdf_readiness_status == "manual_pdf"
    assert item.pdf_asset_id == manual_asset_id


def test_queue_marks_need_pdf_when_no_asset(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]

    assert item.pdf_readiness_status == "need_pdf"
    assert item.pdf_asset_id is None


def test_queue_filter_ready_only(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _cited_id, citing_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        paper_session = PaperAnalysisSession(query_text="manual", query_kind="title")
        asset = PdfAsset(
            storage_path=str(tmp_path / "manual.pdf"),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="manual-ready",
            source_type="upload",
            extract_status="pending",
        )
        db.add_all([paper_session, asset])
        db.flush()
        db.add(CitingPaper(paper_session_id=paper_session.id, publication_id=citing_id, pdf_asset_id=asset.id))
        db.commit()
        service = make_queue_service(db, tmp_path)
        service.build_queue(session_id)
        items = service.list_queue_items(session_id, filters={"view": "ready_only"})

    assert len(items) == 1
    assert items[0].pdf_readiness_status == "manual_pdf"


def test_queue_filter_third_party_only(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        service.build_queue(session_id)
        items = service.list_queue_items(session_id, filters={"view": "third_party_only"})

    assert items
    assert all(item.third_party_status == "third_party" for item in items)


def test_queue_filter_need_pdf(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        service.build_queue(session_id)
        items = service.list_queue_items(session_id, filters={"view": "need_pdf"})

    assert len(items) == 2
    assert all(item.pdf_readiness_status == "need_pdf" for item in items)


def test_queue_filter_exclude_self_citation(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        service.build_queue(session_id)
        items = service.list_queue_items(session_id, filters={"view": "exclude_self_citation"})

    assert items
    assert all(item.self_citation_status != "self_citation" for item in items)


def test_queue_select_items(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        service.select_queue_items(session_id, [item.id])
        db.refresh(item)

    assert item.queue_status == "selected"


def test_queue_skip_items(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        service.skip_queue_items(session_id, [item.id])
        db.refresh(item)

    assert item.queue_status == "skipped"


def test_queue_filters_selected_skipped_and_important(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        items = service.build_queue(session_id)
        service.select_queue_items(session_id, [items[0].id])
        service.skip_queue_items(session_id, [items[1].id])
        service.update_queue_item_review(items[0].id, "important", "Top candidate")
        selected = service.list_queue_items(session_id, filters={"view": "selected"})
        skipped = service.list_queue_items(session_id, filters={"view": "skipped"})
        important = service.list_queue_items(session_id, filters={"view": "important"})

    assert [item.queue_status for item in selected] == ["selected"]
    assert [item.queue_status for item in skipped] == ["skipped"]
    assert [item.user_review_status for item in important] == ["important"]


def test_queue_review_status_update(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        updated = service.update_queue_item_review(item.id, "needs_discussion", "Check authors")

    assert updated.user_review_status == "needs_discussion"
    assert updated.user_note == "Check authors"


def test_mark_important_changes_priority(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        initial_score = item.priority_score
        updated = service.update_queue_item_review(item.id, "important", "Top candidate")
        reasons = json.loads(updated.priority_reasons_json)

    assert updated.priority_score > initial_score
    assert {"reason": "user_marked_important", "delta": 100} in reasons


def test_reject_item_adds_note_and_lowers_priority(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        initial_score = item.priority_score
        updated = service.update_queue_item_review(item.id, "rejected", "Not relevant")
        reasons = json.loads(updated.priority_reasons_json)

    assert updated.user_review_status == "rejected"
    assert updated.user_note == "Not relevant"
    assert updated.priority_score < initial_score
    assert {"reason": "user_rejected", "delta": -100} in reasons


def test_priority_score_sorting_is_descending(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        items = service.build_queue(session_id)
        scores = [item.priority_score for item in items]

    assert scores == sorted(scores, reverse=True)


def test_scholar_queue_page_and_actions(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")
    assert page.status_code == 200
    assert "Independent Citing Paper" in page.text
    assert "Priority score" in page.text

    select_response = client.post(
        f"/scholar-sessions/{session_id}/queue/select",
        data={"item_ids": ["1"]},
        follow_redirects=False,
    )
    assert select_response.status_code == 303

    important_response = client.post(
        f"/scholar-sessions/{session_id}/queue/1/review",
        data={"review_status": "important", "user_note": "Prioritize"},
        follow_redirects=False,
    )
    assert important_response.status_code == 303

    selected_page = client.get(f"/scholar-sessions/{session_id}/queue?view=selected")
    assert selected_page.status_code == 200
    assert "selected" in selected_page.text


def test_queue_page_shows_upload_form_for_need_pdf_item(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "需要上传 citing paper PDF 后才能分析" in page.text
    assert f"/scholar-sessions/{session_id}/queue/1/upload-pdf" in page.text
    assert "选择 PDF 文件" in page.text
    assert "上传 PDF" in page.text


def test_queue_page_shows_pdf_upload_hint(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "Please upload the citing paper PDF: " in page.text
    assert "Independent Citing Paper" in page.text
    assert "Do not upload the cited / target paper PDF: " in page.text
    assert "Cited Scholar Paper" in page.text


def test_upload_pdf_for_queue_item_marks_manual_pdf(client, db_session_factory, tmp_path):
    def override_get_pdf_service(db: Session = Depends(get_db)):
        return PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=tmp_path / "pdf_assets",
            extracted_text_dir=tmp_path / "extracted_text",
            max_upload_bytes=100000,
        )

    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    try:
        with Session(db_session_factory.kw["bind"]) as db:
            session_id, *_ = seed_scholar_edges(db)
            item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
            item_id = item.id

        response = client.post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/upload-pdf",
            files={"file": ("queue-upload.pdf", VALID_PDF_BYTES, "application/pdf")},
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_pdf_service, None)

    assert response.status_code == 303
    assert response.headers["location"] == f"/scholar-sessions/{session_id}/queue"

    with Session(db_session_factory.kw["bind"]) as db:
        saved = db.get(DeepAnalysisQueueItem, item_id)
        asset = db.get(PdfAsset, saved.pdf_asset_id)

    assert saved.pdf_readiness_status == "manual_pdf"
    assert asset.original_filename == "queue-upload.pdf"
    assert asset.source_type == "upload"
    assert asset.extract_status == "succeeded"
    assert "queue-upload.pdf" not in asset.storage_path


def test_pdf_upload_creates_publication_link(client, db_session_factory, tmp_path):
    def override_get_pdf_service(db: Session = Depends(get_db)):
        return PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=tmp_path / "pdf_assets",
            extracted_text_dir=tmp_path / "extracted_text",
            max_upload_bytes=100000,
        )

    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    try:
        with Session(db_session_factory.kw["bind"]) as db:
            session_id, *_ = seed_scholar_edges(db)
            item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
            item_id = item.id

        response = client.post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/upload-pdf",
            files={"file": ("queue-upload.pdf", VALID_PDF_BYTES, "application/pdf")},
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_pdf_service, None)

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        link = db.query(PdfAssetPublicationLink).one()

    assert link.publication_id is not None
    assert link.match_method == "manual_upload_for_queue_item"
    assert link.match_score == 1.0
    assert link.is_verified is True


def test_pdf_upload_binds_asset_to_queue_item_publication_doi(
    client,
    db_session_factory,
    tmp_path,
):
    def override_get_pdf_service(db: Session = Depends(get_db)):
        return PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=tmp_path / "pdf_assets",
            extracted_text_dir=tmp_path / "extracted_text",
            max_upload_bytes=100000,
        )

    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    try:
        with Session(db_session_factory.kw["bind"]) as db:
            session_id, *_ = seed_scholar_edges(db)
            item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
            publication = db.get(Publication, item.citing_publication_id)
            publication.doi = "10.1234/queue.upload"
            db.commit()
            item_id = item.id

        client.post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/upload-pdf",
            files={"file": ("queue-upload.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
    finally:
        app.dependency_overrides.pop(get_pdf_service, None)

    with Session(db_session_factory.kw["bind"]) as db:
        link = db.query(PdfAssetPublicationLink).one()

    assert link.doi == "10.1234/queue.upload"


def test_pdf_upload_binds_asset_to_normalized_title(client, db_session_factory, tmp_path):
    def override_get_pdf_service(db: Session = Depends(get_db)):
        return PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=tmp_path / "pdf_assets",
            extracted_text_dir=tmp_path / "extracted_text",
            max_upload_bytes=100000,
        )

    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    try:
        with Session(db_session_factory.kw["bind"]) as db:
            session_id, *_ = seed_scholar_edges(db)
            item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
            item_id = item.id

        client.post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/upload-pdf",
            files={"file": ("queue-upload.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
    finally:
        app.dependency_overrides.pop(get_pdf_service, None)

    with Session(db_session_factory.kw["bind"]) as db:
        link = db.query(PdfAssetPublicationLink).one()

    assert link.normalized_title == "independent citing paper"


def test_upload_pdf_does_not_overwrite_existing_manual_pdf_without_explicit_replace(
    client,
    db_session_factory,
    tmp_path,
):
    def override_get_pdf_service(db: Session = Depends(get_db)):
        return PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=tmp_path / "pdf_assets",
            extracted_text_dir=tmp_path / "extracted_text",
            max_upload_bytes=100000,
        )

    app.dependency_overrides[get_pdf_service] = override_get_pdf_service
    try:
        with Session(db_session_factory.kw["bind"]) as db:
            session_id, *_ = seed_scholar_edges(db)
            item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
            asset = PdfAsset(
                storage_path=str(tmp_path / "existing.pdf"),
                original_filename="existing.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="existing-manual",
                source_type="upload",
                extract_status="succeeded",
                extracted_text_path=str(tmp_path / "existing.txt"),
            )
            db.add(asset)
            db.flush()
            item.pdf_asset_id = asset.id
            item.pdf_readiness_status = "manual_pdf"
            db.commit()
            item_id = item.id
            original_asset_id = asset.id

        response = client.post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/upload-pdf",
            files={"file": ("replacement.pdf", VALID_PDF_BYTES, "application/pdf")},
        )
    finally:
        app.dependency_overrides.pop(get_pdf_service, None)

    assert response.status_code == 409
    assert "already has a manual PDF" in response.text

    with Session(db_session_factory.kw["bind"]) as db:
        saved = db.get(DeepAnalysisQueueItem, item_id)

    assert saved.pdf_asset_id == original_asset_id
    assert saved.pdf_readiness_status == "manual_pdf"


def test_ready_item_does_not_show_need_pdf_warning(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _cited_id, citing_id, *_ = seed_scholar_edges(db)
        paper_session = PaperAnalysisSession(query_text="manual", query_kind="title")
        asset = PdfAsset(
            storage_path=str(tmp_path / "manual.pdf"),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="manual-ready-page",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(tmp_path / "manual.txt"),
        )
        db.add_all([paper_session, asset])
        db.flush()
        db.add(
            CitingPaper(
                paper_session_id=paper_session.id,
                publication_id=citing_id,
                pdf_asset_id=asset.id,
            )
        )
        db.commit()
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "PDF 已就绪" in page.text
    assert "需要上传 citing paper PDF 后才能分析" not in page.text


def test_analyze_button_disabled_when_no_selected_ready_items(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "Analyze selected ready items" in page.text
    assert "disabled" in page.text
    assert "请先上传或匹配 PDF，并选择 ready item。" in page.text


def test_queue_page_does_not_leak_local_absolute_path(client, db_session_factory, tmp_path):
    library_dir = tmp_path / "private-library"
    library_dir.mkdir()
    local_pdf = write_pdf(library_dir / "10.1234_independent.citing_Independent_Citing_Paper.pdf")

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path, library_dirs=[library_dir])
        service.pdf_library_service.rebuild_index()
        service.build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "Independent Citing Paper" in page.text
    assert str(library_dir) not in page.text
    assert str(local_pdf) not in page.text


def test_queue_page_does_not_leak_local_absolute_paths(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        secret_path = tmp_path / "secret" / "manual.pdf"
        asset = PdfAsset(
            storage_path=str(secret_path),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="secret-manual-path",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(tmp_path / "secret" / "manual.txt"),
        )
        db.add(asset)
        db.flush()
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = "manual_pdf"
        db.commit()

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "manual.pdf" in page.text
    assert str(secret_path) not in page.text
    assert str(tmp_path) not in page.text


def test_queue_page_shows_summary_counts(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        items = service.build_queue(session_id)
        service.select_queue_items(session_id, [items[0].id])
        service.update_queue_item_review(items[1].id, "important", "Important candidate")

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "total queue items: 2" in page.text
    assert "ready_count: 0" in page.text
    assert "need_pdf_count: 2" in page.text
    assert "selected_count: 1" in page.text
    assert "analyzed_count: 0" in page.text
    assert "important_count: 1" in page.text


def test_queue_empty_with_edges_shows_build_button(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "已经扩展出引用，但还没有构建深度分析队列。" in page.text
    assert "构建深度分析队列" in page.text


def test_queue_empty_without_edges_shows_expand_prompt(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        session_id = session.id

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "请先扩展引用。" in page.text


def test_queue_page_in_chinese(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "深度分析队列" in page.text
    assert "已扩展引用" in page.text
    assert "PDF 已就绪" in page.text
    assert "全文分析" in page.text
    assert "强证据" in page.text


def test_queue_filters_have_user_friendly_labels(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    for label in ["全部", "可分析", "缺 PDF", "第三方引用", "排除自引", "已选择", "已跳过", "重要"]:
        assert label in page.text


def test_queue_page_can_select_analysis_scope(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert 'name="analysis_scope" value="candidate_spans"' in page.text
    assert 'name="analysis_scope" value="fulltext_direct"' in page.text
    assert 'name="analysis_scope" value="fulltext_anchor_direct"' in page.text
    assert 'name="analysis_scope" value="fulltext_template_direct"' in page.text
    assert "候选段分析，快但可能漏" in page.text
    assert "全文直接分析，慢但更不容易漏" in page.text
    assert "锚点优先全文分析，推荐用于引用证据验证" in page.text


def test_queue_form_posts_fulltext_template_direct_scope(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        item_id = item.id
        page = client.get(f"/scholar-sessions/{session_id}/queue")
        assert 'name="analysis_scope" value="fulltext_template_direct"' in page.text

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/analyze",
        data={
            "item_ids": [str(item_id)],
            "analysis_scope": "fulltext_template_direct",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        task = db.query(AnalysisTask).one()
        payload = json.loads(task.payload_json)

    assert payload["analysis_scope"] == "fulltext_template_direct"
    assert payload["queue_item_id"] == item_id
    assert payload["queue_item_ids"] == [item_id]


def test_task_payload_keeps_fulltext_template_direct_scope(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        item_id = item.id

    client.post(
        f"/scholar-sessions/{session_id}/queue/analyze",
        data={
            "item_ids": [str(item_id)],
            "analysis_scope": "fulltext_template_direct",
        },
        follow_redirects=False,
    )

    with Session(db_session_factory.kw["bind"]) as db:
        task = db.query(AnalysisTask).one()
        payload = json.loads(task.payload_json)

    assert task.stage_message == "analysis_scope=fulltext_template_direct"
    assert payload["analysis_scope"] == "fulltext_template_direct"


def test_queue_selected_ready_count_includes_reused_pdf(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        asset = PdfAsset(
            storage_path=str(tmp_path / "reused.pdf"),
            original_filename="reused.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="selected-ready-reused",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(tmp_path / "reused.txt"),
        )
        Path(asset.extracted_text_path).write_text("Cited Scholar Paper is a method foundation.", encoding="utf-8")
        db.add(asset)
        db.flush()
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = "reused_pdf"
        item.queue_status = "selected"
        item_id = item.id
        db.commit()
        summary = service.get_queue_summary(session_id)
        selected_ready_ids = service.selected_ready_item_ids(session_id)

    assert summary["ready_count"] == 1
    assert summary["ready_items"] == 1
    assert selected_ready_ids == [item_id]


def test_analyze_button_enabled_for_selected_reused_pdf(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        text_path = tmp_path / "reused.txt"
        text_path.write_text("Cited Scholar Paper is a method foundation.", encoding="utf-8")
        asset = PdfAsset(
            storage_path=str(tmp_path / "reused.pdf"),
            original_filename="reused.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="button-reused",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(text_path),
        )
        db.add(asset)
        db.flush()
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = "reused_pdf"
        item.queue_status = "selected"
        db.commit()

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "请先上传或匹配 PDF，并选择 ready item。" not in page.text
    assert "reused_pdf" in page.text


def test_recent_tasks_use_scholar_analysis_session_kind_consistently(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)
        db.add(
            AnalysisTask(
                session_kind="scholar_analysis",
                session_id=session_id,
                task_type="analyze_scholar_queue",
                status="pending",
            )
        )
        db.commit()

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "任务 #1 analyze_scholar_queue - pending" in page.text


def test_queue_page_shows_analysis_scope_selector(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "Analysis scope" in page.text
    assert "fulltext_anchor_direct 会先定位目标论文在 References 中的引用编号" in page.text
    assert "fulltext_chunked" in page.text
    assert "fulltext_anchor_direct" in page.text


def test_queue_cards_have_checkboxes(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert 'type="checkbox" name="item_ids"' in page.text


def test_bulk_select_current_view(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        make_queue_service(db, tmp_path).build_queue(session_id)

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/bulk-select",
        data={"mode": "current_view", "view": "all"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        selected = db.query(DeepAnalysisQueueItem).filter_by(
            scholar_session_id=session_id,
            queue_status="selected",
        ).count()
    assert selected == 2


def test_bulk_select_ready_items(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        text_path = tmp_path / "ready.txt"
        text_path.write_text("Cited Scholar Paper is a method foundation.", encoding="utf-8")
        asset = PdfAsset(
            storage_path=str(tmp_path / "ready.pdf"),
            original_filename="ready.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="bulk-ready",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(text_path),
        )
        db.add(asset)
        db.flush()
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = "manual_pdf"
        db.commit()

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/bulk-select",
        data={"mode": "ready_items", "view": "all"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        item = db.query(DeepAnalysisQueueItem).filter_by(scholar_session_id=session_id).first()
    assert item.queue_status == "selected"


def test_bulk_select_important_items(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db, include_self_edge=True)
        service = make_queue_service(db, tmp_path)
        items = service.build_queue(session_id)
        service.update_queue_item_review(items[0].id, "important", "")

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/bulk-select",
        data={"mode": "important_items", "view": "all"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        important_selected = db.get(DeepAnalysisQueueItem, items[0].id)
    assert important_selected.queue_status == "selected"


def test_bulk_clear_selection(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        item.queue_status = "selected"
        db.commit()

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/bulk-clear",
        data={"mode": "current_view", "view": "selected"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        item = db.query(DeepAnalysisQueueItem).filter_by(scholar_session_id=session_id).first()
    assert item.queue_status == "pending"


def test_bulk_mark_important(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        item_id = item.id

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/bulk-update",
        data={"action": "mark_important", "item_ids": [str(item_id)]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        item = db.get(DeepAnalysisQueueItem, item_id)
    assert item.user_review_status == "important"


def test_bulk_actions_do_not_cross_session(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        first_session_id, *_ = seed_scholar_edges(db)
        first_item = make_queue_service(db, tmp_path).build_queue(first_session_id)[0]
        second_session_id, *_ = seed_scholar_edges(db)
        second_item = make_queue_service(db, tmp_path).build_queue(second_session_id)[0]
        second_item_id = second_item.id
        first_item_id = first_item.id

    response = client.post(
        f"/scholar-sessions/{first_session_id}/queue/bulk-update",
        data={"action": "skip", "item_ids": [str(second_item_id)]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        first_item = db.get(DeepAnalysisQueueItem, first_item_id)
        second_item = db.get(DeepAnalysisQueueItem, second_item_id)
    assert first_item.queue_status != "skipped"
    assert second_item.queue_status != "skipped"


def test_important_filter_uses_user_review_status(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        service.update_queue_item_review(item.id, "important", "")

    page = client.get(f"/scholar-sessions/{session_id}/queue?view=important")

    assert page.status_code == 200
    assert "Independent Citing Paper" in page.text


def test_fulltext_anchor_direct_available_in_queue_page(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert 'value="fulltext_anchor_direct"' in page.text


def test_queue_page_shows_status_badges(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "badge" in page.text
    assert "need_pdf" in page.text
    assert "pending" in page.text


def test_queue_page_shows_evidence_link(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert f'href="/scholar-sessions/{session_id}/evidence"' in page.text
    assert f'href="/scholar-sessions/{session_id}/cards"' in page.text
    assert f'href="/scholar-sessions/{session_id}"' in page.text


def test_analyze_task_created_message_visible(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        asset = PdfAsset(
            storage_path=str(tmp_path / "ready.pdf"),
            original_filename="ready.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="ready-for-analyze-task",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(tmp_path / "ready.txt"),
        )
        db.add(asset)
        db.flush()
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = "manual_pdf"
        item.queue_status = "selected"
        db.commit()
        item_id = item.id

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/analyze",
        data={"item_ids": [str(item_id)]},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "analyze_scholar_queue 任务已创建" in response.text
    assert "Task #1 analyze_scholar_queue - pending" in response.text
    assert "python3 scripts/run_worker.py" in response.text


def test_failed_analyze_task_error_visible(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)
        db.add(
            AnalysisTask(
                session_kind="scholar_analysis",
                session_id=session_id,
                task_type="analyze_scholar_queue",
                status="failed",
                stage="failed",
                progress_current=0,
                progress_total=1,
                error_message="No extracted text file.",
            )
        )
        db.commit()

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "Task #1 analyze_scholar_queue - failed" in page.text
    assert "分析失败：No extracted text file." in page.text


def test_succeeded_analyze_task_links_to_evidence(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)
        db.add(
            AnalysisTask(
                session_kind="scholar_analysis",
                session_id=session_id,
                task_type="analyze_scholar_queue",
                status="succeeded",
                stage="finished",
                progress_current=1,
                progress_total=1,
            )
        )
        db.commit()

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "分析完成" in page.text
    assert f'href="/scholar-sessions/{session_id}/evidence"' in page.text


def test_queue_page_renders_analyze_task_with_generic_task_poller(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="analyze_scholar_queue",
            status="running",
            stage="analyzing_fulltext",
            stage_message="正在分析 2/9：Realtime Paper",
            progress_current=1,
            progress_total=9,
        )
        db.add(task)
        db.commit()
        task_id = task.id

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert 'class="task-notice task-progress js-task-progress"' in page.text
    assert 'data-task-type="analyze_scholar_queue"' in page.text
    assert (
        f'data-status-url="/scholar-sessions/{session_id}/tasks/{task_id}/status"'
        in page.text
    )
    assert 'data-task-role="progress"' in page.text
    assert "正在分析 2/9：Realtime Paper" in page.text
    assert "全文分析正在进行" in page.text


def test_task_poller_supports_pdf_and_analysis_tasks():
    script = Path("app/static/js/app.js").read_text(encoding="utf-8")

    assert 'querySelectorAll(".js-task-progress")' in script
    assert "initializeTaskProgressPolling" in script
    assert "initializePdfDownloadTaskPolling" not in script
    assert "task-terminal-refreshed:${taskType}:${taskId}" in script


def test_analyze_task_status_endpoint_returns_live_progress(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        make_queue_service(db, tmp_path).build_queue(session_id)
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="analyze_scholar_queue",
            status="running",
            stage="analyzing_fulltext",
            stage_message="正在分析 3/5：Current Analysis Paper",
            progress_current=2,
            progress_total=5,
            payload_json=json.dumps(
                {
                    "progress_summary": {
                        "analyzed_count": 2,
                        "failed_item_count": 0,
                        "skipped": 0,
                    }
                }
            ),
        )
        db.add(task)
        db.commit()
        task_id = task.id

    response = client.get(
        f"/scholar-sessions/{session_id}/tasks/{task_id}/status"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["task_type"] == "analyze_scholar_queue"
    assert payload["progress_current"] == 2
    assert payload["progress_total"] == 5
    assert payload["progress_percent"] == 40.0
    assert payload["stage_message"] == "正在分析 3/5：Current Analysis Paper"
    assert payload["progress_summary"]["analyzed_count"] == 2
    assert payload["is_terminal"] is False


def test_build_scholar_queue_task(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        task = make_queue_service(db, tmp_path).enqueue_build_queue(session_id)
        ran_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        count = db.query(DeepAnalysisQueueItem).count()

    assert task.task_type == "build_scholar_queue"
    assert ran_task.status == "succeeded"
    assert count == 1


def test_uploaded_pdf_can_be_reused_across_scholar_sessions(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        first_session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        first_item = service.build_queue(first_session_id)[0]
        pdf_path = tmp_path / "private" / "Independent Citing Paper.pdf"
        pdf_path.parent.mkdir()
        pdf_path.write_bytes(PDF_BYTES)
        text_path = tmp_path / "private" / "Independent Citing Paper.txt"
        text_path.write_text("Reusable extracted text", encoding="utf-8")
        asset = PdfAsset(
            storage_path=str(pdf_path),
            original_filename="Independent Citing Paper.pdf",
            mime_type="application/pdf",
            size_bytes=pdf_path.stat().st_size,
            sha256="reusable-upload",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(text_path),
        )
        db.add(asset)
        db.flush()
        asset_id = asset.id
        first_item.pdf_asset_id = asset.id
        first_item.pdf_readiness_status = "manual_pdf"
        db.commit()

        second_session_id, *_ = seed_scholar_edges(db)
        second_item = service.build_queue(second_session_id)[0]

    assert second_item.pdf_asset_id == asset_id
    assert second_item.pdf_readiness_status == "reused_pdf"


def test_pdf_reuse_by_exact_doi(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.9999/reuse.doi"
        asset = PdfAsset(
            storage_path=str(tmp_path / "doi.pdf"),
            original_filename="doi.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="reuse-by-doi",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.flush()
        asset_id = asset.id
        PdfRepository(db).create_or_update_asset_publication_link(
            pdf_asset=asset,
            publication=publication,
            raw_title=publication.title,
            match_method="manual_upload_for_queue_item",
            match_score=1.0,
            is_verified=True,
        )
        db.commit()
        item.pdf_asset_id = None
        item.pdf_readiness_status = "need_pdf"
        db.commit()
        result = service.list_queue_items(session_id)[0]

    assert result.pdf_asset_id == asset_id
    assert result.pdf_readiness_status == "reused_pdf"


def test_pdf_reuse_by_openalex_id(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        publication = db.get(Publication, item.citing_publication_id)
        publication.openalex_id = "W123456"
        asset = PdfAsset(
            storage_path=str(tmp_path / "openalex.pdf"),
            original_filename="openalex.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="reuse-by-openalex",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.flush()
        asset_id = asset.id
        PdfRepository(db).create_or_update_asset_publication_link(
            pdf_asset=asset,
            publication=publication,
            raw_title=publication.title,
            match_method="manual_upload_for_queue_item",
            match_score=1.0,
            is_verified=True,
        )
        db.commit()
        item.pdf_asset_id = None
        item.pdf_readiness_status = "need_pdf"
        db.commit()
        result = service.list_queue_items(session_id)[0]

    assert result.pdf_asset_id == asset_id
    assert result.pdf_readiness_status == "reused_pdf"


def test_pdf_reuse_by_publication_id(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        publication = db.get(Publication, item.citing_publication_id)
        asset = PdfAsset(
            storage_path=str(tmp_path / "publication.pdf"),
            original_filename="publication.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="reuse-by-publication",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.flush()
        asset_id = asset.id
        PdfRepository(db).create_or_update_asset_publication_link(
            pdf_asset=asset,
            publication=publication,
            raw_title=publication.title,
            match_method="manual_upload_for_queue_item",
            match_score=1.0,
            is_verified=True,
        )
        db.commit()
        item.pdf_asset_id = None
        item.pdf_readiness_status = "need_pdf"
        db.commit()
        result = service.list_queue_items(session_id)[0]

    assert result.pdf_asset_id == asset_id
    assert result.pdf_readiness_status == "reused_pdf"


def test_pdf_reuse_by_normalized_title(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        service = make_queue_service(db, tmp_path)
        item = service.build_queue(session_id)[0]
        publication = db.get(Publication, item.citing_publication_id)
        publication.normalized_title = "independent citing paper"
        asset = PdfAsset(
            storage_path=str(tmp_path / "title.pdf"),
            original_filename="title.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="reuse-by-title",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.flush()
        asset_id = asset.id
        link = PdfAssetPublicationLink(
            pdf_asset_id=asset.id,
            normalized_title=publication.normalized_title,
            raw_title=publication.title,
            match_method="legacy_title_link",
            match_score=0.95,
            is_verified=True,
        )
        db.add(link)
        db.commit()
        item.pdf_asset_id = None
        item.pdf_readiness_status = "need_pdf"
        db.commit()
        result = service.list_queue_items(session_id)[0]

    assert result.pdf_asset_id == asset_id
    assert result.pdf_readiness_status == "reused_pdf"


def test_queue_item_shows_existing_pdf_candidates(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        asset = PdfAsset(
            storage_path=str(tmp_path / "secret" / "Independent Citation Paper.pdf"),
            original_filename="Independent Citation Paper.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="candidate-upload",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(tmp_path / "secret" / "candidate.txt"),
        )
        db.add(asset)
        db.commit()
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "发现可能匹配的已上传 PDF" in page.text
    assert "Independent Citation Paper.pdf" in page.text
    assert "使用这个 PDF" in page.text


def test_queue_page_shows_citing_paper_doi_and_openalex_id(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.1234/display"
        publication.openalex_id = "WDisplay"
        db.commit()

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "10.1234/display" in page.text
    assert "WDisplay" in page.text
    assert "independent citing paper" in page.text


def test_queue_page_shows_existing_pdf_candidates_with_match_reason(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        asset = PdfAsset(
            storage_path=str(tmp_path / "secret" / "Independent Citation Paper.pdf"),
            original_filename="Independent Citation Paper.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="candidate-match-reason",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.commit()
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "可复用 PDF 候选" in page.text
    assert "filename_title_similarity" in page.text
    assert "上传文件名与引用论文标题相似" in page.text


def test_attach_existing_pdf_to_queue_item(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        asset = PdfAsset(
            storage_path=str(tmp_path / "secret" / "candidate.pdf"),
            original_filename="candidate.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="attach-existing",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(tmp_path / "secret" / "candidate.txt"),
        )
        db.add(asset)
        db.flush()
        item_id = item.id
        asset_id = asset.id
        db.commit()

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/{item_id}/attach-existing-pdf",
        data={"pdf_asset_id": str(asset_id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        saved = db.get(DeepAnalysisQueueItem, item_id)

    assert saved.pdf_asset_id == asset_id
    assert saved.pdf_readiness_status == "reused_pdf"


def test_attach_existing_pdf_creates_verified_link_if_missing(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        publication = db.get(Publication, item.citing_publication_id)
        publication.doi = "10.4444/attach"
        asset = PdfAsset(
            storage_path=str(tmp_path / "candidate.pdf"),
            original_filename="candidate.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="attach-creates-link",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.flush()
        item_id = item.id
        asset_id = asset.id
        db.commit()

    response = client.post(
        f"/scholar-sessions/{session_id}/queue/{item_id}/attach-existing-pdf",
        data={"pdf_asset_id": str(asset_id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        link = db.query(PdfAssetPublicationLink).one()

    assert link.pdf_asset_id == asset_id
    assert link.doi == "10.4444/attach"
    assert link.match_method == "manual_attach_existing_pdf"
    assert link.is_verified is True


def test_attach_existing_pdf_rejects_wrong_session_item(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        first_session_id, *_ = seed_scholar_edges(db)
        first_item = make_queue_service(db, tmp_path).build_queue(first_session_id)[0]
        second_session_id, *_ = seed_scholar_edges(db)
        asset = PdfAsset(
            storage_path=str(tmp_path / "candidate.pdf"),
            original_filename="candidate.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="wrong-session-attach",
            source_type="upload",
            extract_status="succeeded",
        )
        db.add(asset)
        db.flush()
        first_item_id = first_item.id
        asset_id = asset.id
        db.commit()

    response = client.post(
        f"/scholar-sessions/{second_session_id}/queue/{first_item_id}/attach-existing-pdf",
        data={"pdf_asset_id": str(asset_id)},
    )

    assert response.status_code == 404


def test_pdf_reuse_does_not_expose_absolute_path(client, db_session_factory, tmp_path):
    secret_dir = tmp_path / "private-upload"
    secret_dir.mkdir()
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, *_ = seed_scholar_edges(db)
        asset = PdfAsset(
            storage_path=str(secret_dir / "Independent Citation Paper.pdf"),
            original_filename="Independent Citation Paper.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="candidate-path-redaction",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(secret_dir / "candidate.txt"),
        )
        db.add(asset)
        db.commit()
        make_queue_service(db, tmp_path).build_queue(session_id)

    page = client.get(f"/scholar-sessions/{session_id}/queue")

    assert page.status_code == 200
    assert "Independent Citation Paper.pdf" in page.text
    assert str(secret_dir) not in page.text
    assert str(tmp_path) not in page.text


def test_no_pdf_library_scan_inside_build_queue():
    checked_paths = [
        "app/services/scholar_queue_service.py",
        "app/tasks/handlers/build_scholar_queue.py",
    ]
    forbidden = ("scan_pdf_library", "rebuild_index(", "rglob(")

    for path in checked_paths:
        source = (Path.cwd() / path).read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
