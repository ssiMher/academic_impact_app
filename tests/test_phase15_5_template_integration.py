import json
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
    AnalysisTask,
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    HighlightCard,
    PdfAsset,
    ScholarAnalysisSession,
    StrongEvidence,
    TemplateMatch,
)
from app.repositories.pdf_repo import PdfRepository
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.repositories.scholar_session_repo import ScholarSessionRepository
from app.repositories.task_repo import TaskRepository
from app.services.highlight_card_service import HighlightCardService
from app.services.pdf_library_service import PdfLibraryService
from app.services.scholar_analysis_service import ScholarAnalysisService
from app.services.scholar_queue_service import ScholarQueueService
from app.services.scholar_report_service import ScholarReportService
from app.services.template_service import TemplateService
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager


class RecordingTemplateLlmProvider:
    provider_name = "recording-template-fake-llm"

    def __init__(self) -> None:
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        citation_text = request.candidate_spans[0]
        return type(
            "CitationAnalysisResponseLike",
            (),
            {
                "findings": [
                    type(
                        "FindingLike",
                        (),
                        {
                            "evidence_type": "detailed_comparison",
                            "stance": "positive",
                            "mention_type": "strong",
                            "citation_text": citation_text,
                            "keywords": ["detailed comparison", "compared"],
                        },
                    )()
                ],
                "model_dump_json": lambda self: json.dumps(
                    {
                        "findings": [
                            {
                                "evidence_type": "detailed_comparison",
                                "stance": "positive",
                                "mention_type": "strong",
                                "citation_text": citation_text,
                                "keywords": ["detailed comparison", "compared"],
                            }
                        ]
                    }
                ),
            },
        )()


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


def make_queue_service(db, tmp_path):
    return ScholarQueueService(
        repository=ScholarQueueRepository(db),
        pdf_library_service=PdfLibraryService(
            repository=PdfRepository(db),
            library_dirs=[],
            index_path=tmp_path / "pdf_index.json",
            max_scan_files=100,
            match_threshold=0.82,
        ),
    )


def run_next_task(db):
    return TaskRunner(
        task_repository=TaskRepository(db),
        task_manager=TaskManager(),
    ).run_once()


def enable_builtin_templates(db, session_id, template_types):
    service = TemplateService(db)
    builtins = service.list_builtin_templates()
    for template_type in template_types:
        template = next(
            template for template in builtins if template.template_type == template_type
        )
        service.enable_template(session_id=session_id, template_id=template.id)


def attach_ready_pdf_to_item(db, tmp_path, item):
    extracted_path = tmp_path / f"phase15-template-{item.id}.txt"
    extracted_text = (
        f"{item.cited_paper_title} is discussed through a detailed comparison. "
        f"The citing authors compared with {item.cited_paper_title} and explain why "
        "the target paper is stronger evidence for impact."
    )
    extracted_path.write_text(extracted_text, encoding="utf-8")
    pdf_path = tmp_path / f"phase15-template-{item.id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% phase15 template integration\n")
    asset = PdfAsset(
        storage_path=str(pdf_path),
        original_filename="template-integration.pdf",
        mime_type="application/pdf",
        size_bytes=pdf_path.stat().st_size,
        sha256=f"phase15-template-{item.id}",
        source_type="upload",
        extract_status="succeeded",
        extracted_text_path=str(extracted_path),
    )
    db.add(asset)
    db.flush()
    item.pdf_asset_id = asset.id
    item.pdf_readiness_status = "manual_pdf"
    item.queue_status = "selected"
    db.commit()
    db.refresh(item)
    return item


def test_template_system_end_to_end_quality_regression(
    db_session_factory,
    tmp_path,
    monkeypatch,
    client,
):
    llm_provider = RecordingTemplateLlmProvider()
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: llm_provider,
    )

    with Session(db_session_factory.kw["bind"]) as db:
        scholar_service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = scholar_service.create_scholar_session("Grace Hopper")
        enable_builtin_templates(
            db,
            session.id,
            ["first_or_seminal_claim", "detailed_comparison"],
        )

        selected_publication_ids = [
            publication.id
            for publication in scholar_service.list_publications(session.id)[:2]
        ]
        scholar_service.enqueue_expand_scholar_citations(
            session.id,
            selected_publication_ids,
        )
        expand_task = run_next_task(db)
        assert expand_task.status == "succeeded"

        queue_service = make_queue_service(db, tmp_path)
        items = queue_service.build_queue(session.id)
        template_matched_items = [
            item for item in items if "template_match:" in item.priority_reasons_json
        ]
        assert template_matched_items
        assert any(
            "detailed_comparison" in item.priority_reasons_json
            for item in template_matched_items
        )

        item = attach_ready_pdf_to_item(db, tmp_path, template_matched_items[0])
        queue_service.update_queue_item_review(item.id, "important", "Template priority")
        queue_service.rebuild_queue(session.id)
        preserved_item = db.get(DeepAnalysisQueueItem, item.id)
        assert preserved_item.user_review_status == "important"
        assert preserved_item.user_note == "Template priority"

        db.add(
            AnalysisTask(
                session_kind="scholar_analysis",
                session_id=session.id,
                task_type="analyze_scholar_queue",
                status="pending",
            )
        )
        db.commit()
        analyze_task = run_next_task(db)
        assert analyze_task.status == "succeeded"

        result = db.query(FulltextAnalysisResult).one()
        evidence = db.query(StrongEvidence).one()
        matches = db.query(TemplateMatch).filter_by(strong_evidence_id=evidence.id).all()
        assert result.prompt_version == "phase13.v1"
        assert evidence.citation_text
        assert evidence.aspect == "detailed_comparison"
        assert matches
        assert "detailed" in matches[0].matched_terms_json.lower()

        assert llm_provider.requests
        prompt_text = llm_provider.requests[0].prompt_text
        assert "Prioritize detailed comparison evidence" in prompt_text
        assert "citation_text" in prompt_text
        assert "grouped citation" in prompt_text
        assert "weak mention" in prompt_text

        evidence_page = client.get(f"/scholar-sessions/{session.id}/evidence?mode=debug")
        assert evidence_page.status_code == 200
        assert "Template match" in evidence_page.text
        assert "template match terms" in evidence_page.text.lower()

        cards = HighlightCardService(db).generate_cards_from_evidence(session.id)
        card = db.query(HighlightCard).one()
        assert cards
        assert card.strong_evidence_id == evidence.id
        assert card.evidence_quote == evidence.citation_text
        assert card.card_type == "detailed_comparison"

        report = ScholarReportService(db).build_report_markdown(session.id)
        assert "尚未运行 fulltext_template_direct 分析" in report
        assert "### detailed_comparison" not in report
        legacy_report = HighlightCardService(db).export_legacy_cards_markdown(session.id)
        assert evidence.citation_text in legacy_report
        assert "Citing paper:" in legacy_report

        saved_session = db.get(ScholarAnalysisSession, session.id)
        assert saved_session.citation_edge_count > 0
