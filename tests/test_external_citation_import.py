import csv
import io
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
from app.models import CitationEdge, Publication, ScholarAnalysisSession, ScholarPublication
from app.pdf.match import normalize_title_for_match
from app.repositories.pdf_repo import PdfRepository
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.services.external_citation_import_service import ExternalCitationImportService
from app.services.pdf_library_service import PdfLibraryService
from app.services.scholar_queue_service import ScholarQueueService


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


def _csv_bytes(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _seed_scholar_session(db):
    session = ScholarAnalysisSession(
        display_name="Target Scholar",
        status="created",
        publication_count=1,
        citation_edge_count=0,
    )
    target = Publication(
        title="Target Paper",
        normalized_title=normalize_title_for_match("Target Paper"),
        year=2022,
        venue="Target Venue",
        doi="10.0000/target",
        authors_json=json.dumps(["Target Author"]),
    )
    db.add_all([session, target])
    db.flush()
    db.add(
        ScholarPublication(
            scholar_session_id=session.id,
            publication_id=target.id,
            title=target.title,
            year=target.year,
            venue=target.venue,
            doi=target.doi,
            selected_for_expansion=True,
        )
    )
    db.commit()
    return session.id, target.id


def test_external_citation_csv_import_creates_edges(db_session_factory):
    db = db_session_factory()
    try:
        session_id, _ = _seed_scholar_session(db)
        content = _csv_bytes(
            [
                {
                    "Title": "External Citing Paper",
                    "Authors": "Ada Lovelace; Alan Turing",
                    "Year": "2025",
                    "Source": "External Journal",
                    "DOI": "10.1234/external",
                    "ArticleURL": "https://example.test/paper",
                    "CitesURL": "https://example.test/cites",
                    "GSRank": "1",
                }
            ]
        )

        batch = ExternalCitationImportService(db).import_csv(
            session_kind="scholar_analysis",
            session_id=session_id,
            content=content,
            filename="scholar.csv",
            source_name="google_scholar",
        )

        edge = db.query(CitationEdge).one()
        assert batch.imported_count == 1
        assert edge.provider_name == "google_scholar_import"
        assert json.loads(edge.edge_meta_json)["metadata_confidence"] == "imported"
    finally:
        db.close()


def test_external_citation_import_deduplicates_by_doi(db_session_factory):
    db = db_session_factory()
    try:
        session_id, target_id = _seed_scholar_session(db)
        citing = Publication(
            title="OpenAlex Citing Paper",
            normalized_title=normalize_title_for_match("OpenAlex Citing Paper"),
            doi="10.1234/shared",
        )
        db.add(citing)
        db.flush()
        db.add(
            CitationEdge(
                scholar_session_id=session_id,
                cited_publication_id=target_id,
                citing_publication_id=citing.id,
                provider_name="openalex",
            )
        )
        db.commit()

        batch = ExternalCitationImportService(db).import_csv(
            session_kind="scholar_analysis",
            session_id=session_id,
            content=_csv_bytes(
                [
                    {
                        "Title": "Different Title",
                        "Authors": "A. Author",
                        "Year": "2025",
                        "Source": "Venue",
                        "DOI": "10.1234/shared",
                    }
                ]
            ),
            filename="scholar.csv",
            source_name="google_scholar",
        )

        assert db.query(CitationEdge).count() == 1
        assert batch.matched_existing_count == 1
    finally:
        db.close()


def test_external_citation_import_deduplicates_by_title(db_session_factory):
    db = db_session_factory()
    try:
        session_id, target_id = _seed_scholar_session(db)
        citing = Publication(
            title="Same Normalized Title",
            normalized_title=normalize_title_for_match("Same Normalized Title"),
            year=2024,
        )
        db.add(citing)
        db.flush()
        db.add(
            CitationEdge(
                scholar_session_id=session_id,
                cited_publication_id=target_id,
                citing_publication_id=citing.id,
                provider_name="openalex",
            )
        )
        db.commit()

        batch = ExternalCitationImportService(db).import_csv(
            session_kind="scholar_analysis",
            session_id=session_id,
            content=_csv_bytes(
                [
                    {
                        "Title": "Same Normalized Title",
                        "Authors": "A. Author",
                        "Year": "2024",
                        "Source": "Venue",
                        "DOI": "",
                    }
                ]
            ),
            filename="scholar.csv",
            source_name="external_import",
        )

        assert db.query(CitationEdge).count() == 1
        assert batch.matched_existing_count == 1
    finally:
        db.close()


def test_external_citation_import_batch_summary_and_rows(db_session_factory):
    db = db_session_factory()
    try:
        session_id, _ = _seed_scholar_session(db)
        batch = ExternalCitationImportService(db).import_csv(
            session_kind="scholar_analysis",
            session_id=session_id,
            content=_csv_bytes(
                [
                    {
                        "Title": "Good Citing Paper",
                        "Authors": "A. Author",
                        "Year": "2024",
                        "Source": "Venue",
                        "DOI": "10.1/good",
                    },
                    {
                        "Title": "",
                        "Authors": "",
                        "Year": "",
                        "Source": "",
                        "DOI": "",
                    },
                ]
            ),
            filename="scholar.csv",
            source_name="external_import",
        )
        rows = ExternalCitationImportService(db).rows_for_batch(batch.id)

        assert batch.total_rows == 2
        assert batch.imported_count == 1
        assert batch.skipped_count == 1
        assert rows[0].match_status == "imported"
        assert rows[1].match_reason == "missing_title"
    finally:
        db.close()


def test_external_import_edges_enter_deep_analysis_queue(db_session_factory, tmp_path):
    db = db_session_factory()
    try:
        session_id, _ = _seed_scholar_session(db)
        ExternalCitationImportService(db).import_csv(
            session_kind="scholar_analysis",
            session_id=session_id,
            content=_csv_bytes(
                [
                    {
                        "Title": "Queue Candidate From Import",
                        "Authors": "A. Author",
                        "Year": "2024",
                        "Source": "Venue",
                        "DOI": "10.1/queue",
                    }
                ]
            ),
            filename="scholar.csv",
            source_name="google_scholar",
        )
        queue_service = ScholarQueueService(
            repository=ScholarQueueRepository(db),
            pdf_library_service=PdfLibraryService(
                repository=PdfRepository(db),
                library_dirs=[],
                index_path=Path(tmp_path / "index.json"),
                max_scan_files=100,
                match_threshold=0.8,
            ),
        )

        items = queue_service.build_queue(session_id)

        assert len(items) == 1
        assert items[0].provider_name == "google_scholar_import"
    finally:
        db.close()


def test_page_shows_openalex_vs_external_counts(client, db_session_factory):
    db = db_session_factory()
    try:
        session_id, _ = _seed_scholar_session(db)
        ExternalCitationImportService(db).import_csv(
            session_kind="scholar_analysis",
            session_id=session_id,
            content=_csv_bytes(
                [
                    {
                        "Title": "Imported Citing Paper",
                        "Authors": "A. Author",
                        "Year": "2024",
                        "Source": "Venue",
                        "DOI": "10.1/imported",
                    }
                ]
            ),
            filename="scholar.csv",
            source_name="google_scholar",
        )
    finally:
        db.close()

    response = client.get(f"/scholar-sessions/{session_id}")

    assert response.status_code == 200
    assert "OpenAlex 总引用数" in response.text
    assert "Google Scholar / 外部导入" in response.text
    assert "外部导入来源" in response.text
