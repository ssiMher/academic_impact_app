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
    CitationAuthorAnnotation,
    DeepAnalysisQueueItem,
    HighlightCard,
    NotableAuthor,
    StrongEvidence,
)
from app.services.highlight_card_service import HighlightCardService
from app.services.honor_csv_service import (
    HonorCsvImportError,
    HonorCsvImportService,
    extract_citing_title_from_info,
)
from tests.test_highlight_cards_and_scholar_report import seed_evidence
from tests.test_scholar_evidence import seed_queue_item


CSV_HEADER = (
    "Honor/Category,Citing Author,Citing Author Affiliation,Citing Paper Info,"
    "My Cited Paper Title,My Cited Paper Venue,My Cited Paper Year\n"
)


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


def test_honor_csv_import_validates_required_columns(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, __import__("pathlib").Path("/tmp"))
        service = HonorCsvImportService(db)
        with pytest.raises(HonorCsvImportError):
            service.import_csv(session_id=session_id, content=b"only,one,column\n")


def test_honor_csv_import_creates_notable_authors(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        summary = HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    assert summary.created_notable_authors == 1
    with Session(db_session_factory.kw["bind"]) as db:
        author = db.query(NotableAuthor).one()
    assert author.name == "Ramesh Govindan"
    assert author.fellow_status == "IEEE Fellow"


def test_honor_csv_import_extracts_citing_title_from_info():
    title = extract_citing_title_from_info(
        "[MobiCom '23 Inproceedings] UbiPose: Towards Ubiquitous Outdoor AR Pose Tracking using Aerial Meshes."
    )
    assert title == "UbiPose: Towards Ubiquitous Outdoor AR Pose Tracking using Aerial Meshes"


def test_honor_csv_import_matches_queue_item_by_citing_and_cited_title(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "ACM Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        summary = HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    assert summary.matched_count == 1
    with Session(db_session_factory.kw["bind"]) as db:
        annotation = db.query(CitationAuthorAnnotation).one()
    assert annotation.queue_item_id == item_id
    assert annotation.match_status == "matched"


def test_honor_csv_import_marks_queue_item_important(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        item = db.get(DeepAnalysisQueueItem, item_id)

    assert item.user_review_status == "important"


def test_honor_csv_import_adds_priority_reason(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        item = db.get(DeepAnalysisQueueItem, item_id)

    assert "notable_author: IEEE Fellow" in item.priority_reasons_json


def test_honor_csv_import_ambiguous_match_requires_review(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "ACM Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Similar Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, title="Similar Citing Paper A")
        _, second_item_id = seed_queue_item(db, tmp_path, title="Similar Citing Paper B")
        second_item = db.get(DeepAnalysisQueueItem, second_item_id)
        second_item.scholar_session_id = session_id
        db.commit()
        summary = HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    assert summary.ambiguous_count == 1


def test_honor_csv_import_unmatched_rows_reported(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "ACM Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Missing Paper.,"
        + "Missing Target,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        summary = HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    assert summary.unmatched_count == 1


def test_queue_page_shows_notable_author_badge(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    response = client.get(f"/scholar-sessions/{session_id}/queue")

    assert response.status_code == 200
    assert "IEEE Fellow" in response.text
    assert "重要引用" in response.text


def test_honor_import_warns_when_no_queue_items(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        from app.models import ScholarAnalysisSession

        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        session_id = session.id
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Missing Paper.,"
        + "Missing Target,Venue,2024\n"
    ).encode("utf-8")

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "当前尚未构建深度分析队列" in response.text


def test_honor_import_rematch_after_queue_built(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        from app.models import ScholarAnalysisSession

        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        session_id = session.id

    client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )
    with Session(db_session_factory.kw["bind"]) as db:
        seed_session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.scholar_session_id = session_id
        db.commit()

    response = client.post(f"/scholar-sessions/{session_id}/import-honor-csv/rematch")

    assert response.status_code == 200
    assert "成功匹配" in response.text


def test_important_filter_uses_annotation_is_important(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=important")

    assert response.status_code == 200
    assert "Independent Citing Paper" in response.text


def test_honor_csv_matched_item_appears_in_important_view(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    response = client.get(f"/scholar-sessions/{session_id}/queue?view=important")

    assert response.status_code == 200
    assert "IEEE Fellow" in response.text


def test_unmatched_reason_no_queue_items(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        from app.models import ScholarAnalysisSession

        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        session_id = session.id
        content = (
            CSV_HEADER
            + "IEEE Fellow,Ramesh Govindan,USC,"
            + "[MobiCom '23 Inproceedings] Missing Paper.,"
            + "Missing Target,Venue,2024\n"
        ).encode("utf-8")
        summary = HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    assert summary.unmatched_rows[0]["unmatched_reason"] == "no_queue_items"


def test_unmatched_reason_no_match_above_threshold(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Missing Paper.,"
        + "Missing Target,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        summary = HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    assert summary.unmatched_rows[0]["unmatched_reason"] == "no_match_above_threshold"


def test_honor_csv_extracts_citing_venue_from_citing_paper_info():
    from app.services.honor_csv_service import parse_citing_paper_info

    parsed = parse_citing_paper_info(
        "[MobiCom '23 Inproceedings] UbiPose: Towards Ubiquitous Outdoor AR Pose Tracking using Aerial Meshes."
    )

    assert parsed["citing_venue_short"] == "MobiCom"
    assert parsed["citing_year"] == 2023


def test_honor_csv_does_not_use_my_cited_venue_as_citing_venue(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,TMC,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        item = db.get(DeepAnalysisQueueItem, item_id)

    assert item.venue == "Science"


def test_honor_csv_backfills_unknown_citing_venue(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.venue = None
        db.commit()
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        db.refresh(item)

    assert item.venue == "MobiCom"


def test_honor_csv_does_not_override_existing_openalex_venue(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.venue = "OpenAlex Venue"
        db.commit()
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        db.refresh(item)

    assert item.venue == "OpenAlex Venue"


def test_queue_page_shows_csv_backfilled_venue(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.venue = None
        db.commit()
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    response = client.get(f"/scholar-sessions/{session_id}/queue")

    assert response.status_code == 200
    assert "MobiCom" in response.text
    assert "来源：CSV 导入" in response.text


def test_report_card_uses_backfilled_citing_venue(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_evidence(db, tmp_path)
        item = db.query(DeepAnalysisQueueItem).filter_by(scholar_session_id=session_id).first()
        item.venue = None
        if item.citing_publication_id:
            from app.models import Publication

            publication = db.get(Publication, item.citing_publication_id)
            if publication is not None:
                publication.venue = None
        db.commit()
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        card = HighlightCardService(db).generate_cards_from_evidence(session_id)[0]

    assert card.venue == "MobiCom"


def test_evidence_page_shows_notable_author_badge(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_evidence(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "重要引用作者" in response.text
    assert "IEEE Fellow" in response.text


def test_report_workspace_uses_notable_author_info(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_evidence(db, tmp_path)
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        HighlightCardService(db).generate_cards_from_evidence(session_id)

    response = client.get(f"/scholar-sessions/{session_id}/report-workspace")

    assert response.status_code == 200
    assert "Ramesh Govindan" in response.text
    assert "IEEE Fellow" in response.text


def test_honor_csv_import_does_not_overwrite_rejected_review_status(db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.user_review_status = "rejected"
        db.commit()
        HonorCsvImportService(db).import_csv(session_id=session_id, content=content)
        db.refresh(item)

    assert item.user_review_status == "rejected"


def test_honor_csv_import_escapes_html(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,<script>alert(1)</script>,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_honor_import_result_shows_citing_paper_title(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "Independent Citing Paper" in response.text


def test_honor_import_result_shows_cited_paper_title(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Independent Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "Cited Scholar Paper" in response.text


def test_honor_import_result_shows_original_csv_paper_info(client, db_session_factory, tmp_path):
    paper_info = "[MobiCom '23 Inproceedings] Independent Citing Paper."
    content = (
        CSV_HEADER
        + f"IEEE Fellow,Ramesh Govindan,USC,{paper_info},"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "MobiCom" in response.text
    assert "Independent Citing Paper." in response.text


def test_honor_import_unmatched_row_shows_parsed_titles(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "IEEE Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Missing Paper.,"
        + "Missing Target,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "Missing Paper" in response.text
    assert "Missing Target" in response.text


def test_honor_import_ambiguous_row_shows_candidates(client, db_session_factory, tmp_path):
    content = (
        CSV_HEADER
        + "ACM Fellow,Ramesh Govindan,USC,"
        + "[MobiCom '23 Inproceedings] Similar Citing Paper.,"
        + "Cited Scholar Paper,Venue,2024\n"
    ).encode("utf-8")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, title="Similar Citing Paper A")
        _, second_item_id = seed_queue_item(db, tmp_path, title="Similar Citing Paper B")
        second_item = db.get(DeepAnalysisQueueItem, second_item_id)
        second_item.scholar_session_id = session_id
        db.commit()

    response = client.post(
        f"/scholar-sessions/{session_id}/import-honor-csv",
        files={"file": ("honors.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert "Similar Citing Paper A" in response.text or "Similar Citing Paper B" in response.text
