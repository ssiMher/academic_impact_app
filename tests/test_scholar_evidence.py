import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Tuple

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
    CitationEdge,
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    PdfAsset,
    Publication,
    ScholarAnalysisSession,
    StrongEvidence,
)
from app.providers.errors import ProviderException
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.repositories.task_repo import TaskRepository
from app.analysis.prompt_builder import build_fulltext_direct_prompt
from app.services.evidence_service import EvidenceService
from app.services.scholar_fulltext_service import ScholarFulltextService
from app.schemas.provider import ProviderErrorCode
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from app.tasks.handlers.analyze_scholar_queue import handle_analyze_scholar_queue
from app.schemas.llm import CitationAnalysisResponse, TemplateDirectAnalysisResult
from app.services.highlight_card_service import HighlightCardService
from app.services.template_service import TemplateService


GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "scholar_evidence"


class StaticLlmProvider:
    provider_name = "static-golden-llm"

    def __init__(self, response):
        self.response = CitationAnalysisResponse.model_validate(response)

    def analyze_citation(self, request):
        return self.response


class CapturingLlmProvider:
    provider_name = "capturing-llm"

    def __init__(self, response):
        self.response = CitationAnalysisResponse.model_validate(response)
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        return self.response


class CapturingTemplateDirectProvider:
    provider_name = "capturing-template-direct-llm"

    def __init__(self, response):
        self.response = TemplateDirectAnalysisResult.model_validate(response)
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        return self.response


class RaisingSchemaErrorLlmProvider:
    provider_name = "schema-error-llm"

    def analyze_citation(self, request):
        raise ProviderException(
            ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
            "LLM provider returned output that does not match the citation analysis schema.",
            self.provider_name,
            raw_output_preview='{"unexpected": true}',
            schema_error="findings field required",
        )


class RawSchemaErrorLlmProvider:
    provider_name = "raw-schema-error-llm"

    def __init__(self, raw_output: str, schema_error: str = "missing required fields"):
        self.raw_output = raw_output
        self.schema_error = schema_error

    def analyze_citation(self, request):
        raise ProviderException(
            ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
            "LLM provider returned output that does not match the citation analysis schema.",
            self.provider_name,
            raw_output_preview=self.raw_output,
            schema_error=self.schema_error,
        )


class FailingIfCalledLlmProvider:
    provider_name = "should-not-be-called"

    def analyze_citation(self, request):
        raise AssertionError("LLM should not be called")


def template_direct_payload(
    *,
    marker: str = "[23]",
    quote: str = "Target Paper is discussed as a capability source [23].",
):
    return {
        "target_reference_marker": marker,
        "target_reference_entry": f"{marker} Target Paper. doi:10.1145/target",
        "paper_level_summary_zh": "引用论文已完成全文模板直读分析。",
        "evidences": [
            {
                "recommendation": "include",
                "claim_type": "capability_recognition",
                "evidence_quote": quote,
                "evidence_context": f"In the body, {quote} The surrounding context explains the claim.",
                "reference_entry": f"{marker} Target Paper. doi:10.1145/target",
                "why_this_judgment_zh": "正文通过目标引用编号锚定目标论文，并说明能力判断。",
                "copy_ready_zh": "引用论文在正文中明确讨论目标论文的能力表现，可纳入报告。",
                "confidence": "high",
            }
        ],
    }


def load_golden_case(case_name: str):
    return json.loads((GOLDEN_DIR / f"{case_name}.json").read_text(encoding="utf-8"))


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


def seed_queue_item(
    db: Session,
    tmp_path: Path,
    *,
    selected: bool = True,
    pdf_ready: bool = True,
    text: Optional[str] = None,
    title: str = "Independent Citing Paper",
    target_title: str = "Cited Scholar Paper",
    citing_authors: Optional[list] = None,
    cited_authors: Optional[list] = None,
    third_party_status: str = "third_party",
    self_citation_status: str = "not_self_citation",
) -> Tuple[int, int]:
    citing_authors = citing_authors or ["Lin Chen"]
    cited_authors = cited_authors or ["Grace Hopper"]
    session = ScholarAnalysisSession(
        display_name="Grace Hopper",
        status="queued",
        publication_count=1,
        citation_edge_count=1,
    )
    cited = Publication(
        title=target_title,
        year=2021,
        venue="Journal of Scholarly Systems",
        authors_json=json.dumps(cited_authors),
    )
    citing = Publication(
        title=title,
        year=2025,
        venue="Science",
        authors_json=json.dumps(citing_authors),
    )
    db.add_all([session, cited, citing])
    db.flush()

    edge = CitationEdge(
        scholar_session_id=session.id,
        cited_publication_id=cited.id,
        citing_publication_id=citing.id,
        provider_name="fake",
        self_citation_status=self_citation_status,
        third_party_status=third_party_status,
    )
    db.add(edge)
    db.flush()

    pdf_asset_id = None
    readiness = "need_pdf"
    if pdf_ready:
        extracted_path = tmp_path / f"extracted-{citing.id}.txt"
        extracted_path.write_text(
            text
            or (
                "Cited Scholar Paper is a method foundation for this new system. "
                "This citation evidence explains why the target paper is important."
            ),
            encoding="utf-8",
        )
        pdf_path = tmp_path / f"stored-{citing.id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% fake scholar evidence pdf\n")
        asset = PdfAsset(
            storage_path=str(pdf_path),
            original_filename="manual.pdf",
            mime_type="application/pdf",
            size_bytes=pdf_path.stat().st_size,
            sha256=f"sha-{citing.id}",
            source_type="upload",
            extract_status="succeeded",
            extracted_text_path=str(extracted_path),
        )
        db.add(asset)
        db.flush()
        pdf_asset_id = asset.id
        readiness = "manual_pdf"

    item = DeepAnalysisQueueItem(
        scholar_session_id=session.id,
        citation_edge_id=edge.id,
        cited_publication_id=cited.id,
        citing_publication_id=citing.id,
        queue_status="selected" if selected else "pending",
        priority_score=42,
        priority_reasons_json=json.dumps([{"reason": "test", "delta": 42}]),
        third_party_status=third_party_status,
        self_citation_status=self_citation_status,
        pdf_readiness_status=readiness,
        pdf_asset_id=pdf_asset_id,
        venue="Science",
        venue_tier="A",
        citing_paper_title=citing.title,
        cited_paper_title=cited.title,
        citing_authors_json=json.dumps(citing_authors),
        cited_authors_json=json.dumps(cited_authors),
        year=2025,
        provider_name="fake",
    )
    db.add(item)
    db.commit()
    return session.id, item.id


def analyze_golden_case(db, tmp_path, monkeypatch, case):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(case["fake_llm_response"]),
    )
    session_id, item_id = seed_queue_item(
        db,
        tmp_path,
        text=" ".join(case["candidate_spans"]),
        title=case["citing_paper"]["title"],
        target_title=case["target_paper"]["title"],
        citing_authors=case["citing_paper"]["authors"],
        third_party_status=case["citing_paper"]["third_party_status"],
        self_citation_status=case["citing_paper"]["self_citation_status"],
    )
    ScholarFulltextService(db).analyze_queue_items(
        session_id=session_id,
        queue_item_ids=[item_id],
        analysis_scope="scholar_queue",
    )
    return session_id, item_id


def test_analyze_selected_ready_queue_items(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

        item = db.get(DeepAnalysisQueueItem, item_id)

    assert summary["succeeded"] == 1
    assert summary["skipped"] == 0
    assert item.queue_status == "analyzed"


def test_skip_need_pdf_queue_items(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

    assert summary["succeeded"] == 0
    assert summary["skipped"] == 1
    assert db.query(FulltextAnalysisResult).count() == 0
    assert db.query(StrongEvidence).count() == 0


def test_generate_fulltext_result_for_queue_item(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        result = db.query(FulltextAnalysisResult).one()

    assert result.scholar_session_id == session_id
    assert result.queue_item_id == item_id
    assert result.citation_edge_id is not None
    assert result.status == "succeeded"
    assert json.loads(result.candidate_spans_json)


def test_generate_strong_evidence_from_fake_llm(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.scholar_session_id == session_id
    assert evidence.queue_item_id == item_id
    assert evidence.aspect == "method_foundation"
    assert evidence.score is not None and evidence.score >= 0.6


def test_fulltext_direct_scope_skips_candidate_spans(db_session_factory, tmp_path, monkeypatch):
    def fail_candidate_spans(*args, **kwargs):
        raise AssertionError("candidate spans should not be used for fulltext_direct")

    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.find_candidate_spans",
        fail_candidate_spans,
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=(
                "Cited Scholar Paper is explicitly discussed as a method foundation "
                "for the new citing system."
            ),
        )
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert summary["succeeded"] == 1


def test_fulltext_direct_reads_extracted_text_and_records_chars(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingLlmProvider({"findings": []})
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    full_text = "Cited Scholar Paper appears in the extracted text."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=full_text)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)

    assert provider.requests[0].full_text == full_text
    assert diagnostics["fulltext_chars"] == len(full_text)


def test_fulltext_direct_prompt_contains_full_text(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingLlmProvider({"findings": []})
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    full_text = "The complete extracted text says Cited Scholar Paper is the key comparison."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=full_text)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert provider.requests
    prompt = provider.requests[0].prompt_text
    assert "You are analyzing the citing paper full text." in prompt
    assert "CITING_PAPER_TITLE: Independent Citing Paper" in prompt
    assert "CITED_PAPER_TITLE: Cited Scholar Paper" in prompt
    assert "FULL_EXTRACTED_TEXT:" in prompt
    assert full_text in prompt


def test_prompt_includes_target_reference_contexts_before_fulltext(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingLlmProvider({"findings": []})
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    full_text = (
        "2 Theory\nThe convolution model in [36] defines the frequency difference behavior.\n\n"
        "References\n[36] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )

    prompt = provider.requests[0].prompt_text
    assert "TARGET_REFERENCE_CONTEXTS:" in prompt
    assert "TARGET_REFERENCE_MARKER: [36]" in prompt
    assert prompt.index("TARGET_REFERENCE_CONTEXTS:") < prompt.index("FULL_EXTRACTED_TEXT:")


def test_prompt_rule_theoretical_formula_context_with_marker(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingLlmProvider({"findings": []})
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    full_text = (
        "The equation in [36] defines the spectral model and convolution behavior.\n\n"
        "References\n[36] J. Ning et al., MoirePose.\n"
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=full_text, target_title="MoiréPose")
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )

    prompt = provider.requests[0].prompt_text
    assert "theoretical_foundation or method_foundation" in prompt
    assert "If citation_text contains TARGET_REFERENCE_MARKER" in prompt


def test_fulltext_direct_prompt_forbids_reference_entries():
    prompt = build_fulltext_direct_prompt(
        citing_paper_title="Citing Paper",
        cited_paper_title="MoiréPose",
        target_reference_marker="[15]",
        target_reference_entry="[15] J. Ning et al., MoirePose ...",
        full_text="Body text",
    )

    assert "Do not use bibliography/reference-list entries as findings." in prompt
    assert "citation_text must come from the main body discussion" in prompt
    assert "If the only occurrence of the cited paper is in References" in prompt
    assert "TARGET_REFERENCE_MARKER: [15]" in prompt
    assert "If a grouped citation contains TARGET_REFERENCE_MARKER" in prompt
    assert '"evidence_type"' in prompt
    assert '"mention_type"' in prompt


def test_fulltext_direct_does_not_call_llm_with_empty_text(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: FailingIfCalledLlmProvider(),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        pdf_asset = db.get(PdfAsset, item.pdf_asset_id)
        Path(pdf_asset.extracted_text_path).write_text("", encoding="utf-8")
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert summary["failed"] == 1
    assert "empty_extracted_text" in summary["warnings"][0]


def test_fulltext_direct_respects_max_chars(db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        SimpleNamespace(
            fulltext_direct_max_chars=10,
            llm_provider="fake",
            llm_model="fake-model",
        ),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="This full text is definitely longer than ten characters.",
        )
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert summary["failed"] == 1
    assert "fulltext_too_long_for_direct_analysis" in summary["warnings"][0]


def test_fulltext_direct_writes_failed_result_on_schema_error(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RaisingSchemaErrorLlmProvider(),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        parsed = json.loads(result.parsed_result_json)
        diagnostics = json.loads(result.candidate_spans_json)

    assert summary["failed"] == 1
    assert result.analysis_scope == "fulltext_direct"
    assert result.status == "failed"
    assert result.error_message
    assert diagnostics["fulltext_chars"] > 0
    assert parsed["error"] == "provider_schema_error"
    assert parsed["raw_output_preview"] == '{"unexpected": true}'
    assert parsed["schema_error"] == "findings field required"


def test_fulltext_direct_records_analysis_scope(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)

    assert result.analysis_scope == "fulltext_direct"
    assert diagnostics["mode"] == "fulltext_direct"
    assert diagnostics["fulltext_chars"] > 0


def test_fulltext_anchor_direct_records_anchor_diagnostics(
    db_session_factory,
    tmp_path,
):
    full_text = (
        "1 Theory\nThe convolution model in [36] defines the spectral peak behavior.\n\n"
        "References\n[36] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)

    assert result.analysis_scope == "fulltext_anchor_direct"
    assert diagnostics["target_reference_marker"] == "[36]"
    assert diagnostics["reference_anchor_found"] is True
    assert diagnostics["target_reference_context_count"] >= 1
    assert diagnostics["prompt_contains_target_contexts"] is True


def test_fulltext_direct_result_scope_is_fulltext_direct(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()

    assert result.analysis_scope == "fulltext_direct"


def test_fulltext_direct_generates_strong_evidence_from_fake_llm(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=(
                "Cited Scholar Paper is a method foundation for the full text direct "
                "analysis workflow."
            ),
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert "Cited Scholar Paper" in evidence.citation_text
    assert evidence.highlight_keywords_json


def test_fulltext_direct_empty_findings_explained_on_evidence_page(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider({"findings": []}),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "analysis_scope: fulltext_direct" in response.text
    assert "llm_findings_count: 0" in response.text
    assert "全文已分析，但模型没有发现可保存的正文强证据。" in response.text


def test_evidence_empty_state_shows_diagnostics(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider({"findings": []}),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "Analysis diagnostics" in response.text
    assert "fulltext_result_count: 1" in response.text
    assert "latest fulltext result id" in response.text
    assert "generated_strong_evidence_count" in response.text
    assert "filtered_findings_count" in response.text


def test_evidence_page_in_chinese(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, pdf_ready=False)

    response = client.get(f"/scholar-sessions/{session_id}/evidence")

    assert response.status_code == 200
    assert "学者证据" in response.text
    assert "正式证据视图" in response.text
    assert "没有引用论文 PDF 已就绪" in response.text
    assert "展开调试信息" in response.text


def test_evidence_page_shows_llm_findings_without_strong_evidence(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper is mentioned together with several related systems [1, 2, 3]."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "important_author_citation",
                        "stance": "neutral",
                        "mention_type": "grouped_citation",
                        "citation_text": quote,
                        "reasoning": "Grouped citation should be manually reviewed.",
                        "keywords": ["related systems"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "llm_findings_count" in response.text
    assert "The LLM found possible citation-related findings, but none passed the strong evidence filters" in response.text
    assert "filtered_findings_count" in response.text


def test_evidence_page_shows_filter_reason_distribution(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper is a background mention in related work."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "Background only.",
                        "keywords": ["background"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "过滤原因分布" in response.text
    assert "background_neutral" in response.text


def test_evidence_page_shows_filtered_findings_when_no_strong_evidence(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper is a background mention in related work."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "Background only.",
                        "keywords": ["background"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "逐条 finding 过滤诊断" in response.text
    assert "filter_reason=background_neutral" in response.text


def test_evidence_debug_shows_schema_error(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RaisingSchemaErrorLlmProvider(),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "status: failed" in response.text
    assert "raw_output_preview" in response.text
    assert "unexpected" in response.text
    assert "true" in response.text
    assert "schema_error" in response.text
    assert "findings field required" in response.text


def test_schema_error_shows_raw_response_preview(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RaisingSchemaErrorLlmProvider(),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "raw_output_preview" in response.text


def test_analysis_debug_page_redacts_sensitive_info(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        result = FulltextAnalysisResult(
            scholar_session_id=session_id,
            queue_item_id=item_id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope="fulltext_direct",
            status="failed",
            candidate_spans_json=json.dumps({"mode": "fulltext_direct", "fulltext_chars": 120}),
            parsed_result_json=json.dumps(
                {
                    "error": "provider_schema_error",
                    "raw_output_preview": "api_key=sk-testsecret123 authorization: Bearer sk-token999",
                    "schema_error": "api_key=sk-testsecret123 missing field",
                }
            ),
            error_message="Provider schema error.",
        )
        db.add(result)
        db.commit()

    response = client.get(f"/scholar-sessions/{session_id}/analysis-debug")

    assert response.status_code == 200
    assert "Analysis Debug" in response.text
    assert "raw_output_preview" in response.text
    assert "schema_error" in response.text
    assert "sk-testsecret123" not in response.text
    assert "sk-token999" not in response.text
    assert "[redacted" in response.text
    assert str(tmp_path) not in response.text


def test_debug_prompt_saving_disabled_by_default(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        SimpleNamespace(
            fulltext_direct_max_chars=120000,
            llm_provider="fake",
            llm_model="fake-model",
            debug_save_llm_prompts=False,
            debug_llm_dir=str(tmp_path / "debug"),
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert payload["prompt_debug_enabled"] is False
    assert payload.get("prompt_debug_file") in {None, ""}
    assert not (tmp_path / "debug").exists()


def test_debug_prompt_saving_writes_prompt_response_and_metadata(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "debug-llm"
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        SimpleNamespace(
            fulltext_direct_max_chars=120000,
            llm_provider="fake",
            llm_model="fake-model",
            debug_save_llm_prompts=True,
            debug_llm_dir=str(debug_dir),
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
            task_id=77,
        )
        result = db.query(FulltextAnalysisResult).one()
        payload = json.loads(result.candidate_spans_json)

    result_dir = debug_dir / f"result_{result.id}"
    assert payload["prompt_debug_file"] == "prompt.txt"
    assert payload["raw_response_debug_file"] == "raw_response.txt"
    assert payload["normalized_response_debug_file"] == "normalized_response.json"
    assert payload["metadata_debug_file"] == "metadata.json"
    assert (result_dir / "prompt.txt").exists()
    assert (result_dir / "raw_response.txt").exists()
    assert (result_dir / "normalized_response.json").exists()
    metadata = json.loads((result_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["task_id"] == 77
    assert metadata["queue_item_id"] == item_id


def test_debug_prompt_saving_redacts_api_key(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "debug-redact"
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        SimpleNamespace(
            fulltext_direct_max_chars=120000,
            llm_provider="fake",
            llm_model="fake-model",
            debug_save_llm_prompts=True,
            debug_llm_dir=str(debug_dir),
        ),
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RawSchemaErrorLlmProvider(
            'authorization: Bearer sk-secret-token-123456 {"findings":[]}',
            schema_error="api_key=sk-secret-token-123456 missing",
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()

    raw_text = (debug_dir / f"result_{result.id}" / "raw_response.txt").read_text(encoding="utf-8")
    metadata = (debug_dir / f"result_{result.id}" / "metadata.json").read_text(encoding="utf-8")
    assert "sk-secret-token-123456" not in raw_text
    assert "authorization" in raw_text.lower()
    assert "sk-secret-token-123456" not in metadata


def test_analysis_debug_shows_prompt_and_response_links(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "debug-links"
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        SimpleNamespace(
            fulltext_direct_max_chars=120000,
            llm_provider="fake",
            llm_model="fake-model",
            debug_save_llm_prompts=True,
            debug_llm_dir=str(debug_dir),
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/analysis-debug")

    assert response.status_code == 200
    assert "下载完整 Prompt" in response.text
    assert "查看 Raw response" in response.text
    assert "查看 Parsed findings" in response.text


def test_analysis_debug_shows_prompt_preview(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "debug-preview"
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        SimpleNamespace(
            fulltext_direct_max_chars=120000,
            llm_provider="fake",
            llm_model="fake-model",
            debug_save_llm_prompts=True,
            debug_llm_dir=str(debug_dir),
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/analysis-debug")

    assert response.status_code == 200
    assert "查看 Prompt 摘要" in response.text
    assert "FULL_EXTRACTED_TEXT:" in response.text


def test_analysis_debug_shows_target_reference_contexts(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingLlmProvider({"findings": []})
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    full_text = (
        "2 Theory\nThe convolution model in [36] defines the frequency difference behavior.\n\n"
        "References\n[36] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/analysis-debug")

    assert response.status_code == 200
    assert "TARGET_REFERENCE_CONTEXTS" in response.text
    assert "目标引用编号" in response.text
    assert "[36]" in response.text


def test_schema_repair_removes_reference_only_finding(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    raw_output = json.dumps(
        {
            "findings": [
                {
                    "citation_text": (
                        "J. Ning et al., “MoiréPose: ultra high precision "
                        "camera-to-screen pose estimation based on Moiré pattern,” "
                        "in Proc. Annu. Int. Conf. Mob. Comput. Netw., 2022, pp. 106–119."
                    )
                },
                {
                    "citation_text": (
                        "The aliasing pattern is sensitive to the pose of the target, "
                        "introducing the potential of an ultraprecise out-of-plane rotation measurement."
                    )
                },
            ]
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RawSchemaErrorLlmProvider(raw_output),
    )
    full_text = (
        "The aliasing pattern is sensitive to the pose of the target, introducing "
        "the potential of an ultraprecise out-of-plane rotation measurement.\n\n"
        "References\n"
        "J. Ning et al., “MoiréPose: ultra high precision camera-to-screen pose "
        "estimation based on Moiré pattern,” in Proc. Annu. Int. Conf. Mob. Comput. "
        "Netw., 2022, pp. 106–119."
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        parsed = json.loads(result.parsed_result_json)

    assert summary["succeeded"] == 1
    assert result.status == "succeeded"
    assert parsed["findings"] == []
    assert db.query(StrongEvidence).count() == 0


def test_schema_repair_fills_supported_missing_fields(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper is a method foundation for this camera pose analysis workflow."
    raw_output = json.dumps({"findings": [{"citation_text": quote}]})
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RawSchemaErrorLlmProvider(raw_output),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        parsed = json.loads(result.parsed_result_json)
        evidence = db.query(StrongEvidence).one()

    assert summary["succeeded"] == 1
    assert parsed["findings"][0]["evidence_type"] == "method_foundation"
    assert parsed["findings"][0]["stance"] == "positive"
    assert parsed["findings"][0]["mention_type"] == "explicit_target"
    assert evidence.aspect == "method_foundation"


def test_missing_required_fields_triggers_repair(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper provides a detailed comparison with prior camera pose systems."
    raw_output = json.dumps(
        {
            "findings": [
                {
                    "quote": quote,
                    "reason": "The quote says it provides a detailed comparison.",
                    "highlight_keywords": ["detailed comparison"],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RawSchemaErrorLlmProvider(raw_output),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        parsed = json.loads(db.query(FulltextAnalysisResult).one().parsed_result_json)

    assert parsed["findings"][0]["citation_text"] == quote
    assert parsed["findings"][0]["evidence_type"] == "detailed_comparison"
    assert parsed["findings"][0]["keywords"] == ["detailed comparison"]


def test_reference_entry_not_saved_as_strong_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    reference_quote = (
        "J. Ning et al., “MoiréPose: ultra high precision camera-to-screen pose "
        "estimation based on Moiré pattern,” in Proc. Annu. Int. Conf. Mob. Comput. "
        "Netw., 2022, pp. 106–119."
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "reference_only",
                        "citation_text": reference_quote,
                        "reasoning": "This is only a reference entry.",
                        "keywords": ["MoiréPose"],
                    }
                ]
            }
        ),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=f"References\n{reference_quote}",
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert db.query(FulltextAnalysisResult).count() == 1
    assert db.query(StrongEvidence).count() == 0


def test_background_neutral_finding_filtered_with_reason(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper is mentioned in the background section of related work."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "This is a background mention.",
                        "keywords": ["background"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert payload["finding_diagnostics"][0]["filter_reason"] == "background_neutral"


def test_related_work_with_target_marker_can_be_representative_work(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Other work explores estimating pose leveraging moire patterns' high sensitivity "
        "to the camera's pose changes [60], and improving pose tracking using inertial sensors."
    )
    full_text = (
        f"{quote}\n\nReferences\n"
        "[60] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "This is representative or field positioning evidence for moire-based pose estimation.",
                        "keywords": ["high sensitivity", "pose changes"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "representative_work"
    assert evidence.evidence_strength in {"weak", "moderate"}


def test_background_neutral_without_target_marker_still_filtered(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Other work explores estimating pose leveraging moire patterns' high sensitivity to the camera's pose changes."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "Background mention without target marker.",
                        "keywords": ["high sensitivity"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=quote)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert db.query(StrongEvidence).count() == 0
    assert (
        payload["finding_diagnostics"][0]["filter_reason"]
        == "no_target_reference_marker_available"
    )


def test_title_alias_anchor_found_without_reference_marker_generates_medium_representative_work(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Moreover, MoireVision [40] introduces a generalized 6-DoF motion sensing mechanism."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "The sentence names the target method and describes its mechanism.",
                        "keywords": ["generalized 6-DoF motion sensing mechanism"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=quote,
            target_title="MoireVision: generalized 6-DoF motion sensing",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert evidence.aspect == "representative_work"
    assert evidence.evidence_strength == "moderate"
    assert payload["finding_diagnostics"][0]["anchor_validation_reason"] == "title_alias_anchor_found"
    assert payload["finding_diagnostics"][0]["promotion_decision"] == "saved_background_anchor_upgrade"


def test_background_tradeoff_anchor_upgrades_to_limitation_or_negative(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Compared with prior systems, TargetTracker [16] has different design trade-offs in deployment."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "The sentence explicitly compares the target system.",
                        "keywords": ["compared with", "design trade-offs"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=f"{quote}\n\nReferences\n[16] A. Target, TargetTracker: reliable tracking system.\n",
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "limitation_or_negative"
    assert evidence.evidence_strength == "moderate"
    assert "实质性判断线索" in evidence.evidence_reason


def test_background_compared_with_anchor_upgrades_to_detailed_comparison(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Compared with prior systems, TargetTracker [16] achieves a different evaluation profile."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "The sentence explicitly compares the target system.",
                        "keywords": ["compared with", "evaluation profile"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=f"{quote}\n\nReferences\n[16] A. Target, TargetTracker: reliable tracking system.\n",
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "detailed_comparison"
    assert evidence.evidence_strength == "moderate"


def test_background_limitation_anchor_upgrades_to_limitation_or_negative(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "TargetTracker [16] is camera-dependent and sensitive to lighting, motivating later design choices."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "The sentence states constraints of the target system.",
                        "keywords": ["camera-dependent", "sensitive to lighting"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=f"{quote}\n\nReferences\n[16] A. Target, TargetTracker: reliable tracking system.\n",
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "limitation_or_negative"
    assert evidence.stance == "negative"
    assert evidence.evidence_strength == "moderate"


def test_ubipose_moirepose_sentence_generates_representative_work_candidate(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Other work explores estimating pose leveraging moire patterns' high sensitivity "
        "to the camera's pose changes [60], and improving pose tracking using inertial sensors [2, 75, 91]."
    )
    full_text = (
        f"{quote}\n\nReferences\n"
        "[60] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "The cited paper is used as a representative prior work for moire-based pose estimation.",
                        "keywords": ["high sensitivity", "pose changes", "prior work"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            title="Moiré Spectral Augmentation and Masked Frequency Modeling for Document Presentation Attack Detection",
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "representative_work"
    assert evidence.citation_text == quote


def test_reference_entry_not_representative_work(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "[60] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern."
    full_text = f"References\n{quote}\n"
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "representative_work",
                        "stance": "neutral",
                        "mention_type": "reference_only",
                        "citation_text": quote,
                        "reasoning": "Reference entry only.",
                        "keywords": ["prior work"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )

    assert db.query(StrongEvidence).count() == 0


def test_filter_reason_not_promoted_is_not_the_only_reason(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": "Background quote about Cited Scholar Paper.",
                        "reasoning": "Background mention only.",
                        "keywords": ["background"],
                    },
                    {
                        "evidence_type": "method_foundation",
                        "stance": "positive",
                        "mention_type": "method_use",
                        "citation_text": None,
                        "reasoning": "No quote present.",
                        "keywords": ["method"],
                    },
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert "background_neutral" in payload["filter_reason_distribution"]
    assert "no_citation_text" in payload["filter_reason_distribution"]
    assert "not_promoted_or_filtered" not in payload["filter_reason_distribution"]


def test_grouped_negative_with_target_marker_generates_medium_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = (
        "Some methods leverage the aliasing effect [15], [16], [17]. "
        "However, the reported accuracy does not demonstrate superiority over conventional methods."
    )
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
        "[16] Other Work.\n"
        "[17] Another Work.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "limitation_or_negative",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "The grouped aliasing methods include the target paper [15].",
                        "keywords": ["aliasing effect", "reported accuracy"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        evidence = db.query(StrongEvidence).one()
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert evidence.mention_type == "grouped_citation"
    assert evidence.evidence_strength == "moderate"
    assert evidence.anchor_status == "grouped_citation"
    assert payload["finding_diagnostics"][0]["filter_reason"] == "grouped_citation_saved_for_review"
    assert payload["finding_diagnostics"][0]["citation_text_contains_target_marker"] is True


def test_grouped_detailed_comparison_with_target_marker_generates_medium_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = (
        "The aliasing Moire-based methods [14]-[17] yield errors in the range from 0.2 to 2 degrees. "
        "However, in terms of accuracy, they offer no advantage over conventional methods."
    )
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[14] Earlier Work.\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
        "[16] Other Work.\n"
        "[17] Another Work.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "detailed_comparison",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "The grouped Moire-based methods include the target paper [15].",
                        "keywords": ["errors", "accuracy"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "detailed_comparison"
    assert evidence.evidence_strength == "moderate"
    assert evidence.anchor_status == "grouped_citation"


def test_theoretical_foundation_with_target_marker_generates_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "The theoretical foundation of our aliasing model follows [15] closely."
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "theoretical_foundation",
                        "stance": "positive",
                        "mention_type": "method_use",
                        "citation_text": body_quote,
                        "reasoning": "The body quote explicitly anchors the cited paper via [15].",
                        "keywords": ["theoretical foundation"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "theoretical_foundation"
    assert evidence.anchor_status == "body_anchor_found"


def test_finding_without_target_marker_is_filtered(db_session_factory, tmp_path, monkeypatch):
    body_quote = "This sentence discusses a different prior method without the target reference."
    full_text = (
        "The target paper is cited elsewhere [16].\n"
        f"{body_quote}\n\n"
        "References\n"
        "[16] A. Target, TargetTracker: reliable tracking system.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "positive_evaluation",
                        "stance": "positive",
                        "mention_type": "related_work",
                        "citation_text": body_quote,
                        "reasoning": "The sentence is positive but does not cite the target paper.",
                        "keywords": ["different prior method"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)
        evidence_count = db.query(StrongEvidence).count()

    assert evidence_count == 0
    assert diagnostics["finding_diagnostics"][0]["filter_reason"] == "target_anchor_missing"


def test_finding_with_other_reference_marker_is_filtered(db_session_factory, tmp_path, monkeypatch):
    body_quote = "The competing method [20] achieves strong performance in the benchmark."
    full_text = (
        "Target paper appears here [16].\n"
        f"{body_quote}\n\n"
        "References\n"
        "[16] A. Target, TargetTracker: reliable tracking system.\n"
        "[20] B. Other, OtherTag: different tracking system.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "positive_evaluation",
                        "stance": "positive",
                        "mention_type": "related_work",
                        "citation_text": body_quote,
                        "reasoning": "This is about another cited work.",
                        "keywords": ["strong performance"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)
        evidence_count = db.query(StrongEvidence).count()

    assert evidence_count == 0
    assert diagnostics["finding_diagnostics"][0]["filter_reason"] == "cited_other_reference_marker"
    assert diagnostics["finding_diagnostics"][0]["citation_text_contains_other_marker"] is True


def test_display_context_marker_does_not_rescue_wrong_citation_text(db_session_factory, tmp_path, monkeypatch):
    wrong_quote = "The competing method [18] is accurate in dynamic scenes."
    full_text = (
        "The target paper is introduced in this related-work paragraph [16]. "
        f"{wrong_quote}\n\n"
        "References\n"
        "[16] A. Target, TargetTracker: reliable tracking system.\n"
        "[18] C. Other, OtherTracker: alternate tracking system.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "positive_evaluation",
                        "stance": "positive",
                        "mention_type": "related_work",
                        "citation_text": wrong_quote,
                        "reasoning": "The surrounding context contains [16], but this sentence cites [18].",
                        "keywords": ["accurate"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)
        evidence_count = db.query(StrongEvidence).count()

    assert evidence_count == 0
    assert diagnostics["finding_diagnostics"][0]["filter_reason"] == "cited_other_reference_marker"


def test_grouped_citation_with_target_marker_can_be_representative_work(db_session_factory, tmp_path, monkeypatch):
    body_quote = "Related work discusses tracking systems [15], [16], [17] as prior examples."
    full_text = (
        f"{body_quote}\n\n"
        "References\n"
        "[16] A. Target, TargetTracker: reliable tracking system.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "This is related work and representative prior work.",
                        "keywords": ["tracking systems"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "representative_work"
    assert evidence.anchor_status == "grouped_citation"
    assert evidence.evidence_strength == "moderate"


def test_grouped_citation_without_target_marker_filtered(db_session_factory, tmp_path, monkeypatch):
    body_quote = "Related work discusses tracking systems [15], [17] as prior examples."
    full_text = (
        f"{body_quote}\n\n"
        "References\n"
        "[16] A. Target, TargetTracker: reliable tracking system.\n"
        "[17] B. Other, OtherTracker: alternate tracking system.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "This is related work and representative prior work.",
                        "keywords": ["tracking systems"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence_count = db.query(StrongEvidence).count()
        diagnostics = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert evidence_count == 0
    assert diagnostics["finding_diagnostics"][0]["filter_reason"] == "cited_other_reference_marker"


def test_grouped_citation_not_promoted_to_positive_evaluation(db_session_factory, tmp_path, monkeypatch):
    body_quote = "These methods [15], [16], [17] are effective in the tested setting."
    full_text = (
        f"{body_quote}\n\n"
        "References\n"
        "[16] A. Target, TargetTracker: reliable tracking system.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "positive_evaluation",
                        "stance": "positive",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "The positive claim is made over a citation group.",
                        "keywords": ["effective"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="TargetTracker: reliable tracking system",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)
        evidence_count = db.query(StrongEvidence).count()

    assert evidence_count == 0
    assert diagnostics["finding_diagnostics"][0]["filter_reason"] == "grouped_citation_not_promoted_to_strong_claim"


def test_formula_context_with_target_marker_generates_theoretical_foundation(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "Eq. (4) and the convolution model in [36] define the spectral peak and frequency difference assumptions."
    full_text = (
        f"2 Theory\n{body_quote}\n\n"
        "References\n"
        "[36] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "theoretical_foundation",
                        "stance": "neutral",
                        "mention_type": "method_use",
                        "citation_text": body_quote,
                        "reasoning": "The theory section grounds the model in the target reference [36].",
                        "keywords": ["convolution model", "frequency difference", "spectral peak"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "theoretical_foundation"
    assert evidence.anchor_status == "body_anchor_found"


def test_no_body_anchor_not_used_when_marker_present(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "Aliasing methods [15], [16], [17] show no advantage over conventional baselines."
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
        "[16] Other Work.\n"
        "[17] Another Work.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "detailed_comparison",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "The grouped citation includes [15].",
                        "keywords": ["no advantage"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert payload["finding_diagnostics"][0]["filter_reason"] != "no_body_anchor"


def test_no_body_anchor_not_used_when_context_contains_marker(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "yields the spectral peak estimate used in our derivation."
    full_text = (
        "2 Theory\nThe frequency difference model in [36] yields the spectral peak estimate used in our derivation.\n\n"
        "References\n"
        "[36] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "theoretical_foundation",
                        "stance": "neutral",
                        "mention_type": "method_use",
                        "citation_text": body_quote,
                        "reasoning": "This quote comes from the anchored theory context around [36].",
                        "keywords": ["frequency difference", "spectral peak"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert payload["finding_diagnostics"][0]["filter_reason"] == "saved"


def test_grouped_citation_evidence_requires_human_review(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "Grouped comparison [15], [16], [17] shows accuracy limitations."
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
        "[16] Other Work.\n"
        "[17] Another Work.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "limitation_or_negative",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "Grouped citation needs review.",
                        "keywords": ["accuracy limitations"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)

    assert payload["finding_diagnostics"][0]["needs_human_review"] is True


def test_filter_diagnostics_include_target_marker_and_reason(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "Methods [15], [16], [17] are discussed together."
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
        "[16] Other Work.\n"
        "[17] Another Work.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "detailed_comparison",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "Target marker is present.",
                        "keywords": ["discussed together"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        payload = json.loads(db.query(FulltextAnalysisResult).one().candidate_spans_json)
        finding = payload["finding_diagnostics"][0]

    assert finding["target_reference_marker"] == "[15]"
    assert finding["citation_text_contains_target_marker"] is True
    assert finding["filter_reason"] == "grouped_citation_saved_for_review"


def test_general_moire_sentence_not_attributed_without_anchor(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "The aliasing pattern is sensitive to the pose of the target, introducing "
        "the potential of an ultraprecise out-of-plane rotation measurement."
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "method_foundation",
                        "stance": "positive",
                        "mention_type": "method_use",
                        "citation_text": quote,
                        "reasoning": "The sentence is about aliasing but does not name the cited paper.",
                        "keywords": ["aliasing pattern"],
                    }
                ]
            }
        ),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=quote,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert db.query(StrongEvidence).count() == 0


def test_valid_body_quote_generates_strong_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "MoiréPose: ultra high precision camera-to-screen pose estimation based on "
        "Moiré pattern provides a method foundation for our camera calibration pipeline."
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "method_foundation",
                        "stance": "positive",
                        "mention_type": "explicit_target",
                        "citation_text": quote,
                        "reasoning": "The body quote states that the cited paper is a method foundation.",
                        "keywords": ["method foundation", "camera calibration"],
                    }
                ]
            }
        ),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=quote,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.aspect == "method_foundation"
    assert "method foundation" in evidence.citation_text


def test_fulltext_direct_requires_citation_text_for_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "method_foundation",
                        "stance": "positive",
                        "mention_type": "strong",
                        "citation_text": None,
                        "reasoning": "No original text.",
                        "keywords": ["method"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    assert db.query(FulltextAnalysisResult).count() == 1
    assert db.query(StrongEvidence).count() == 0


def test_no_citation_text_no_evidence(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidences = db.query(StrongEvidence).all()

    assert all(evidence.citation_text for evidence in evidences)
    assert all(evidence.aspect != "application_extension" for evidence in evidences)


def test_grouped_citation_not_high_strength_by_default(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidences = db.query(StrongEvidence).all()

    assert all(evidence.mention_type != "grouped_citation" for evidence in evidences)
    assert all(evidence.evidence_strength != "high" for evidence in evidences)


def test_grouped_negative_finding_can_be_saved_as_review_needed_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Cited Scholar Paper and prior methods show clear limitations in grouped comparison [4, 5]."
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "limitation_or_negative",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": quote,
                        "reasoning": "The grouped quote states limitations that require manual attribution review.",
                        "keywords": ["limitations", "grouped comparison"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=f"{quote} Cited Scholar Paper is discussed in the main body.",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )
        evidence = db.query(StrongEvidence).one()

    assert evidence.mention_type == "grouped_citation"
    assert evidence.anchor_status == "grouped_citation"
    assert evidence.review_status == "unreviewed"
    assert "需要人工确认归因范围" in evidence.evidence_reason


def test_evidence_keywords_highlighted(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).one()

    assert "method foundation" in json.loads(evidence.highlight_keywords_json)
    assert "<mark>method foundation</mark>" in evidence.highlighted_text_html


def test_preserve_evidence_review_on_reanalysis(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        service = ScholarFulltextService(db)
        service.analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).one()
        EvidenceService(db).update_evidence_review(evidence.id, "important", "Keep this")

        service.analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidences = db.query(StrongEvidence).all()

    assert len(evidences) == 1
    assert evidences[0].review_status == "important"
    assert evidences[0].user_note == "Keep this"


def test_partial_failure_does_not_fail_entire_batch(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, ready_item_id = seed_queue_item(db, tmp_path, title="Ready Citing Paper")
        _, need_pdf_item_id = seed_queue_item(
            db,
            tmp_path,
            pdf_ready=False,
            title="Need PDF Citing Paper",
        )
        need_pdf_item = db.get(DeepAnalysisQueueItem, need_pdf_item_id)
        need_pdf_item.scholar_session_id = session_id
        db.commit()

        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[ready_item_id, need_pdf_item_id],
            analysis_scope="scholar_queue",
        )

    assert summary["succeeded"] == 1
    assert summary["skipped"] == 1
    assert db.query(StrongEvidence).count() == 1


def test_analyze_scholar_queue_task_handles_partial_failures(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ready_item_id = seed_queue_item(db, tmp_path, title="Ready Task Paper")
        _, need_pdf_item_id = seed_queue_item(
            db,
            tmp_path,
            pdf_ready=False,
            title="Need PDF Task Paper",
        )
        need_pdf_item = db.get(DeepAnalysisQueueItem, need_pdf_item_id)
        need_pdf_item.scholar_session_id = session_id
        db.commit()
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="analyze_scholar_queue",
            status="pending",
            stage="queued",
        )
        db.add(task)
        db.commit()

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        fulltext_count = db.query(FulltextAnalysisResult).count()
        evidence_count = db.query(StrongEvidence).count()

    assert completed.status == "succeeded"
    assert "need_pdf" in completed.stage_message
    assert db.query(StrongEvidence).count() == 1


def test_analyze_task_updates_progress_per_item_and_finishes_at_100_percent(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            title="Realtime Analysis Paper",
        )
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="analyze_scholar_queue",
            payload_json=json.dumps(
                {
                    "analysis_scope": "candidate_spans",
                    "queue_item_ids": [item_id],
                }
            ),
            status="running",
        )
        db.add(task)
        db.commit()

        commits = []
        original_commit = db.commit

        def tracking_commit():
            commits.append(
                (
                    task.progress_current,
                    task.progress_total,
                    task.stage,
                    task.stage_message,
                )
            )
            original_commit()

        monkeypatch.setattr(db, "commit", tracking_commit)

        handle_analyze_scholar_queue(db, task)

        assert any(
            current == 0
            and total == 1
            and stage == "preparing_fulltext_analysis"
            and message == "准备分析 1 篇论文"
            for current, total, stage, message in commits
        )
        assert any(
            current == 0
            and stage == "analyzing_fulltext"
            and "正在分析 1/1：Realtime Analysis Paper" in (message or "")
            for current, _total, stage, message in commits
        )
        assert any(
            current == 1
            and "已分析 1/1：Realtime Analysis Paper" in (message or "")
            for current, _total, _stage, message in commits
        )
        assert task.progress_current == task.progress_total == 1


def test_analyze_queue_processes_selected_reused_pdf_item(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.pdf_readiness_status = "reused_pdf"
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="analyze_scholar_queue",
            status="pending",
            stage="queued",
        )
        db.add(task)
        db.commit()

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        fulltext_count = db.query(FulltextAnalysisResult).count()
        evidence_count = db.query(StrongEvidence).count()

    assert completed.status == "succeeded"
    assert "ready_items=1" in completed.stage_message
    assert "analyzed_count=1" in completed.stage_message
    assert "fulltext_result_count=1" in completed.stage_message
    assert "queue_item:" not in completed.stage_message
    assert fulltext_count == 1
    assert evidence_count == 1


def test_reused_pdf_without_asset_reports_invalid_binding(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.pdf_readiness_status = "reused_pdf"
        db.commit()

        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="candidate_spans",
        )

    assert summary["ready_items"] == 1
    assert summary["skipped"] == 1
    assert "queue_item:%s:invalid_pdf_binding" % item_id in summary["warnings"]


def test_reused_pdf_with_unextracted_asset_reports_extract_not_ready(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.pdf_readiness_status = "reused_pdf"
        asset = db.get(PdfAsset, item.pdf_asset_id)
        asset.extract_status = "pending"
        db.commit()

        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="candidate_spans",
        )

    assert summary["ready_items"] == 1
    assert summary["skipped"] == 1
    assert "queue_item:%s:pdf_extract_not_ready" % item_id in summary["warnings"]


def test_evidence_diagnostics_counts_reused_pdf_as_ready(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.pdf_readiness_status = "reused_pdf"
        db.commit()

    response = client.get(f"/scholar-sessions/{session_id}/evidence")

    assert response.status_code == 200
    assert "已有可分析条目，但尚未运行全文分析。" in response.text
    assert "没有引用论文 PDF 已就绪" not in response.text


def test_analyze_task_summary_reports_failed_items(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, title="Missing Extracted Text")
        item = db.get(DeepAnalysisQueueItem, item_id)
        pdf_asset = db.get(PdfAsset, item.pdf_asset_id)
        Path(pdf_asset.extracted_text_path).unlink()
        task = AnalysisTask(
            session_kind="scholar_analysis",
            session_id=session_id,
            task_type="analyze_scholar_queue",
            status="pending",
            stage="queued",
        )
        db.add(task)
        db.commit()

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

    assert completed.status == "failed"
    assert "failed_item_count=1" in completed.error_message
    assert "fulltext_result_count=0" in completed.error_message
    assert "strong_evidence_count=0" in completed.error_message


def test_analyze_scholar_queue_task_uses_fulltext_direct_scope(
    db_session_factory,
    tmp_path,
):
    full_text = "Cited Scholar Paper is a method foundation in the complete full text."
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=full_text)
        task = ScholarFulltextService(db).enqueue_analyze_queue(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        result = db.query(FulltextAnalysisResult).one()
        diagnostics = json.loads(result.candidate_spans_json)

    assert completed.status == "succeeded"
    assert "analysis_scope=fulltext_direct" in completed.stage_message
    assert f"fulltext_chars={len(full_text)}" in completed.stage_message
    assert result.analysis_scope == "fulltext_direct"
    assert diagnostics["fulltext_chars"] == len(full_text)


def test_scholar_evidence_page_filters(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        EvidenceService(db).update_evidence_review(
            db.query(StrongEvidence).one().id,
            "important",
            "",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?view=important&mode=debug")

    assert response.status_code == 200
    assert "Independent Citing Paper" in response.text
    assert "method_foundation" in response.text
    assert "<mark>method foundation</mark>" in response.text


def test_evidence_review_update(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence_id = db.query(StrongEvidence).one().id

    response = client.post(
        f"/scholar-sessions/{session_id}/evidence/{evidence_id}/review",
        data={"review_status": "accepted", "user_note": "Looks useful"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        evidence = db.get(StrongEvidence, evidence_id)
        assert evidence.review_status == "accepted"
        assert evidence.user_note == "Looks useful"


def test_evidence_page_shows_grouped_citation_warning(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    body_quote = "Methods [15], [16], [17] show accuracy limitations."
    full_text = (
        f"{body_quote}\n\nReferences\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
        "[16] Other Work.\n"
        "[17] Another Work.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "limitation_or_negative",
                        "stance": "negative",
                        "mention_type": "grouped_citation",
                        "citation_text": body_quote,
                        "reasoning": "Grouped citation needs manual attribution review.",
                        "keywords": ["accuracy limitations"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "该证据来自成组引用，可能同时适用于多个被引论文，请人工确认归因范围。" in response.text


def test_evidence_page_shows_representative_work_warning(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Other work explores estimating pose leveraging moire patterns' high sensitivity "
        "to the camera's pose changes [60], and improving pose tracking using inertial sensors [2, 75, 91]."
    )
    full_text = (
        f"{quote}\n\nReferences\n"
        "[60] J. Ning et al., MoirePose: ultra high precision camera-to-screen pose estimation based on Moire pattern.\n"
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: StaticLlmProvider(
            {
                "findings": [
                    {
                        "evidence_type": "background",
                        "stance": "neutral",
                        "mention_type": "related_work",
                        "citation_text": quote,
                        "reasoning": "The cited paper is a representative prior work for moire-based pose estimation.",
                        "keywords": ["high sensitivity", "prior work"],
                    }
                ]
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text=full_text,
            target_title="MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_anchor_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "这是代表性相关工作/领域定位证据，不等同于直接正向评价。" in response.text


def test_evidence_card_has_expand_context_button(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="Before context. Cited Scholar Paper is used directly here. After context.",
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence")

    assert response.status_code == 200
    assert "原文上下文" in response.text
    assert "Before context" in response.text


def test_evidence_context_includes_before_after_text(
    client,
    db_session_factory,
    tmp_path,
):
    text = "Before context. Cited Scholar Paper is a method foundation for our workflow. After context."
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=text)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence")

    assert response.status_code == 200
    assert "Before context" in response.text
    assert "After context" in response.text


def test_highlight_includes_full_sentence_not_only_keywords(
    client,
    db_session_factory,
    tmp_path,
):
    text = "Before context. Cited Scholar Paper is a method foundation for our workflow. After context."
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, text=text)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "<mark>Cited Scholar Paper is a method foundation for our workflow.</mark>" in response.text


def assert_golden_kept(db, case):
    expected = case["expected"]
    evidences = db.query(StrongEvidence).all()
    if expected["keep"]:
        assert evidences, f"{case['name']} should produce evidence"
    else:
        assert not evidences, f"{case['name']} should not produce strong evidence"
        return

    saved_labels = [evidence.aspect for evidence in evidences]
    for label in expected["labels"]:
        assert label in saved_labels
    evidence = evidences[0]
    assert evidence.citation_text
    assert evidence.aspect
    assert evidence.stance
    assert evidence.mention_type
    assert evidence.evidence_reason
    assert evidence.highlight_keywords_json
    assert evidence.score is not None
    assert evidence.evidence_strength == expected["evidence_strength"]
    assert evidence.third_party_status
    for keyword in expected["highlight_keywords"]:
        assert keyword in json.loads(evidence.highlight_keywords_json)


def test_must_not_miss_positive_evaluation(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("positive_evaluation_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)


def test_must_not_miss_first_claim(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("first_or_seminal_claim_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)


def test_must_not_miss_detailed_comparison(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("detailed_comparison_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)


def test_must_not_miss_baseline_or_benchmark(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("baseline_or_benchmark_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)


def test_must_not_miss_theoretical_foundation(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("theoretical_foundation_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)


def test_weak_mention_not_saved_as_strong_evidence(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("weak_mention_should_not_be_strong_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)
        assert db.query(FulltextAnalysisResult).count() == 1


def test_grouped_citation_not_high_strength(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("grouped_citation_should_not_be_high_strength_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, case)
        assert_golden_kept(db, case)
        assert db.query(FulltextAnalysisResult).count() == 1


def test_self_citation_downranked(db_session_factory, tmp_path, monkeypatch):
    self_case = load_golden_case("self_citation_should_be_downranked_case")
    third_party_case = load_golden_case("third_party_positive_case")
    with Session(db_session_factory.kw["bind"]) as db:
        analyze_golden_case(db, tmp_path, monkeypatch, self_case)
        self_score = db.query(StrongEvidence).one().score
        db.query(StrongEvidence).delete()
        db.query(FulltextAnalysisResult).delete()
        db.commit()

        analyze_golden_case(db, tmp_path, monkeypatch, third_party_case)
        third_party_score = db.query(StrongEvidence).one().score

    assert self_score < third_party_score


def test_third_party_evidence_prioritized(db_session_factory, tmp_path, monkeypatch):
    case = load_golden_case("third_party_positive_case")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _item_id = analyze_golden_case(db, tmp_path, monkeypatch, case)
        rows = EvidenceService(db).list_scholar_evidence(session_id, filters={"view": "third_party_only"})

    assert len(rows) == 1
    assert rows[0]["evidence"].third_party_status == "third_party"


def test_evidence_review_supports_corrected_label_and_preserves_it(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        service = ScholarFulltextService(db)
        service.analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence_id = db.query(StrongEvidence).one().id

    response = client.post(
        f"/scholar-sessions/{session_id}/evidence/{evidence_id}/review",
        data={
            "review_status": "needs_discussion",
            "user_note": "Check label",
            "corrected_label": "detailed_comparison",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarFulltextService(db)
        service.analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence = db.get(StrongEvidence, evidence_id)

    assert evidence.review_status == "needs_discussion"
    assert evidence.user_note == "Check label"
    assert evidence.corrected_label == "detailed_comparison"


def test_rejected_evidence_excluded_from_report_candidates(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).one()
        EvidenceService(db).update_evidence_review(evidence.id, "rejected", "Noisy")

        candidates = EvidenceService(db).list_report_candidate_evidence(session_id)

    assert candidates == []


def test_important_evidence_sorts_before_higher_scored_unreviewed(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    first_case = load_golden_case("self_citation_should_be_downranked_case")
    second_case = load_golden_case("third_party_positive_case")
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = analyze_golden_case(db, tmp_path, monkeypatch, first_case)
        important = db.query(StrongEvidence).one()
        EvidenceService(db).update_evidence_review(important.id, "important", "")
        _, second_item_id = seed_queue_item(
            db,
            tmp_path,
            text=" ".join(second_case["candidate_spans"]),
            title=second_case["citing_paper"]["title"],
            target_title=second_case["target_paper"]["title"],
            citing_authors=second_case["citing_paper"]["authors"],
            third_party_status=second_case["citing_paper"]["third_party_status"],
            self_citation_status=second_case["citing_paper"]["self_citation_status"],
        )
        item = db.get(DeepAnalysisQueueItem, second_item_id)
        item.scholar_session_id = session_id
        db.commit()
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: StaticLlmProvider(second_case["fake_llm_response"]),
        )
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[second_item_id],
            analysis_scope="scholar_queue",
        )
        rows = EvidenceService(db).list_scholar_evidence(session_id, filters={"view": "all"})

    assert rows[0]["evidence"].review_status == "important"


def test_evidence_quality_summary_counts_review_and_strength(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).one()
        EvidenceService(db).update_evidence_review(evidence.id, "false_positive", "Bad match")
        summary = EvidenceService(db).quality_summary(session_id)

    assert summary["total_evidence_count"] == 1
    assert summary["false_positive_count"] == 1
    assert summary["third_party_evidence_count"] == 1
    assert summary["high_strength_count"] == 1


def test_scholar_evidence_page_filters_false_positive_and_high_strength(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )
        EvidenceService(db).update_evidence_review(
            db.query(StrongEvidence).one().id,
            "false_positive",
            "Bad match",
        )

    false_positive_response = client.get(
        f"/scholar-sessions/{session_id}/evidence?view=false_positive&mode=debug"
    )
    high_strength_response = client.get(
        f"/scholar-sessions/{session_id}/evidence?view=high_strength&mode=debug"
    )

    assert false_positive_response.status_code == 200
    assert "false_positive_count" in false_positive_response.text
    assert "Bad match" in false_positive_response.text
    assert high_strength_response.status_code == 200
    assert "method_foundation" in high_strength_response.text


def test_fulltext_template_direct_uses_fulltext_and_template(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper. doi:10.1145/target",
            "paper_level_summary_zh": "全文模板分析摘要。",
            "evidences": [],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="Body cites Target Paper [23]. References [23] Target Paper. doi:10.1145/target",
            target_title="Target Paper",
        )
        TemplateService(db).create_custom_template(
            session_id=session_id,
            natural_language_goal="RFID 亚毫米级感知能力佐证",
            template_type="custom",
            positive_keywords=["sub-mm", "RFID"],
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )

    assert result.analysis_scope == "fulltext_template_direct"
    prompt = provider.requests[0].prompt_text
    assert "FULL_EXTRACTED_TEXT" in prompt
    assert "Body cites Target Paper [23]" in prompt
    assert "ACTIVE_EVIDENCE_TEMPLATES" in prompt
    assert "RFID 亚毫米级感知能力佐证" in prompt
    assert "do not write that the cited paper received third-party sub-mm recognition" in prompt


def test_fulltext_template_direct_outputs_reference_entry(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper. doi:10.1145/target",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": "The method follows Target Paper [23].",
                    "evidence_context": "The method follows Target Paper [23] in the system design.",
                    "reference_entry": "[23] Target Paper. doi:10.1145/target",
                    "why_this_judgment_zh": "正文通过 [23] 指向目标论文。",
                    "copy_ready_zh": "引用论文在方法设计中使用了目标论文。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="The method follows Target Paper [23].\n\nReferences\n[23] Target Paper. doi:10.1145/target",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        payload = json.loads(result.parsed_result_json)
        diagnostics = json.loads(result.candidate_spans_json)

    assert payload["target_reference_entry"] == "[23] Target Paper. doi:10.1145/target"
    assert payload["evidences"][0]["reference_entry"] == "[23] Target Paper. doi:10.1145/target"
    assert diagnostics["template_direct_evidence_count"] == 1


def test_template_direct_counts_parsed_evidences_instead_of_legacy_findings(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "发现正文引用，但不满足纳入条件。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": "Target Paper is listed as prior work [23].",
                    "evidence_context": "The related-work section lists Target Paper as prior work [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "这是普通相关工作。",
                    "copy_ready_zh": "不建议作为强证据纳入。",
                    "confidence": "medium",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "Target Paper is listed as prior work [23].\n\n"
                "References\n[23] Target Paper."
            ),
        )
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        result = db.query(FulltextAnalysisResult).one()
        stored_diagnostics = json.loads(result.candidate_spans_json)
        diagnostics = ScholarFulltextService(db).list_analysis_diagnostics(
            session_id
        )[0]

    assert summary["llm_findings_count"] == 1
    assert summary["parsed_evidence_count"] == 1
    assert summary["include_evidence_count"] == 0
    assert summary["review_evidence_count"] == 0
    assert summary["exclude_evidence_count"] == 1
    assert summary["strong_evidence_count"] == 0
    assert stored_diagnostics["llm_findings_count"] == 1
    assert diagnostics["parsed_evidence_count"] == 1
    assert diagnostics["exclude_evidence_count"] == 1

    page = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")
    assert page.status_code == 200
    assert "发现 1 条正文证据，但没有证据满足强证据纳入条件。" in page.text
    assert "模型没有发现正文证据" not in page.text


def test_grouped_citation_only_checks_target_marker_sentence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[14]",
            "target_reference_entry": "[14] C. Wang et al., Target Paper.",
            "paper_level_summary_zh": "目标引用位于独立句子。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": (
                        "An earlier system used another method [13]. "
                        "The target work introduced a concrete mechanism [14]."
                    ),
                    "evidence_context": (
                        "An earlier system used another method [13]. "
                        "The target work introduced a concrete mechanism [14]."
                    ),
                    "reference_entry": "[14] C. Wang et al., Target Paper.",
                    "why_this_judgment_zh": "第二句单独描述目标方法。",
                    "copy_ready_zh": "该论文概括了目标工作的方法机制。",
                    "confidence": "medium",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "An earlier system used another method [13]. "
                "The target work introduced a concrete mechanism [14].\n\n"
                "References\n[13] Other Paper.\n"
                "[14] C. Wang et al., Target Paper."
            ),
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["grouped_citation"] is False
    assert evidence["citation_text_contains_other_marker"] is False
    assert evidence["claim_type"] == "method_summary"


def test_reference_author_attribution_conflict_downgrades_to_review(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[14]",
            "target_reference_entry": "[14] C. Wang et al., Target Paper.",
            "paper_level_summary_zh": "正文作者和参考文献作者冲突。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": "Haibing Wu [14] proposed a concrete sensing method.",
                    "evidence_context": "Haibing Wu [14] proposed a concrete sensing method used by this system.",
                    "reference_entry": "[14] C. Wang et al., Target Paper.",
                    "why_this_judgment_zh": "正文描述了具体方法。",
                    "copy_ready_zh": "引用论文使用了目标方法。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "Haibing Wu [14] proposed a concrete sensing method.\n\n"
                "References\n[14] C. Wang et al., Target Paper."
            ),
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["reference_match_status"] == "matched"
    assert evidence["reference_attribution_conflict"] is True
    assert evidence["reference_attribution_body_author"] == "Wu"
    assert evidence["reference_attribution_entry_author"] == "Wang"
    assert evidence["reference_attribution_reason"] == "body_author_reference_author_mismatch"
    assert evidence["recommendation"] == "review"
    assert evidence["confidence"] != "high"
    assert "reference_attribution_conflict" in evidence["postprocess_reason"]


def test_report_contains_evidence_quote_and_reference_entry(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper. doi:10.1145/target",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "submm_precision_claim",
                    "evidence_quote": "Target Paper achieves sub-mm RFID sensing [23].",
                    "evidence_context": "In evaluation, Target Paper achieves sub-mm RFID sensing [23] under controlled conditions.",
                    "reference_entry": "[23] Target Paper. doi:10.1145/target",
                    "why_this_judgment_zh": "sub-mm 明确作用到 [23]。",
                    "copy_ready_zh": "引用论文明确指出目标论文实现了 sub-mm RFID sensing。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "Target Paper achieves sub-mm RFID sensing [23].\n\n"
                "References\n[23] Target Paper. doi:10.1145/target"
            ),
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "**Target Paper** achieves" in markdown
    assert "对应参考文献" in markdown
    assert "**[23]**" in markdown
    assert "doi:**10.1145/target**" in markdown
    assert "引用论文明确指出目标论文实现了 sub-mm RFID sensing" in markdown


def test_report_contains_why_this_judgment(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "capability_recognition",
                    "evidence_quote": "Target Paper captures loudspeaker vibration [23].",
                    "evidence_context": "Target Paper captures loudspeaker vibration [23] for acoustic sensing.",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "原文明确把 loudspeaker vibration 能力归到 [23]。",
                    "copy_ready_zh": "可复制表述。",
                    "confidence": "medium",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "评价理由" in markdown
    assert "原文明确把 loudspeaker vibration 能力归到 [23]" in markdown


def test_report_excludes_debug_fields(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": "The method uses Target Paper [23].",
                    "evidence_context": "The method uses Target Paper [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "正文锚定 [23]。",
                    "copy_ready_zh": "可复制表述。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "template_failure_reason" not in markdown
    assert "anchor_validation_status" not in markdown
    assert "matched_template_ids" not in markdown
    assert "<!--" not in markdown


def test_first_scope_not_misattributed(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Wang et al.",
            "paper_level_summary_zh": "first 修饰其他系统。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "false_positive",
                    "evidence_quote": "TagMic is the first system, unlike Wang et al. [23].",
                    "evidence_context": "TagMic is the first system, unlike Wang et al. [23].",
                    "reference_entry": "[23] Wang et al.",
                    "why_this_judgment_zh": "first 修饰 TagMic，不修饰 [23]。",
                    "copy_ready_zh": "不应纳入。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Wang et al.")
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "TagMic is the first system" not in markdown
    assert "不纳入证据数：1" in markdown


def test_submm_claim_requires_targeted_submm_evidence(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "sub-mm 未作用到目标论文。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": "Another system has sub-mm accuracy, while Target Paper is cited as related work [23].",
                    "evidence_context": "Another system has sub-mm accuracy, while Target Paper is cited as related work [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "sub-mm 修饰 Another system，不修饰 [23]。",
                    "copy_ready_zh": "只能作为普通相关工作候选。",
                    "confidence": "low",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "## 二、推荐纳入\n\n暂无。" in markdown
    assert "候选复核附录" in markdown
    assert "只能作为普通相关工作候选" in markdown


def test_unresolved_submm_body_claim_goes_to_direct_submm_candidate(db_session_factory, tmp_path, monkeypatch):
    quote = "The authors in [23] achieve thru-the-wall eavesdropping on loudspeakers by capturing sub-mm level vibration of the loudspeaker using RFID."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "强候选。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "正文出现 capturing sub-mm level vibration 并锚定 [23]。",
                    "copy_ready_zh": "需人工核对 reference entry 后使用。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote,
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert evidence["claim_type"] == "submm_precision_claim"
    assert evidence["recommendation"] == "review"
    assert evidence["reference_match_status"] == "unresolved"
    assert "直接亚毫米级佐证候选：需人工核对引用编号" in markdown
    assert "capturing sub-mm level vibration" in markdown


def test_review_items_go_to_appendix_not_main_report(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": "Target Paper appears in related work [23].",
                    "evidence_context": "Target Paper appears in related work [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "普通相关工作。",
                    "copy_ready_zh": "候选复核表述。",
                    "confidence": "low",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    main_section = markdown.split("候选复核附录", 1)[0]
    assert "**Target Paper** appears in related work" not in main_section
    assert "**Target Paper** appears in related work" in markdown


def test_direct_report_ordinary_reference_not_include(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "普通相关工作。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": "Target Paper is discussed as related work [23].",
                    "evidence_context": "Target Paper is discussed as related work [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "普通相关工作。",
                    "copy_ready_zh": "不应进入主报告。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Target Paper is discussed as related work [23].\n\nReferences\n[23] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        payload = json.loads(result.parsed_result_json)

    assert payload["evidences"][0]["claim_type"] == "ordinary_reference"
    assert payload["evidences"][0]["recommendation"] == "review"
    assert "ordinary_reference_not_include" in payload["evidences"][0]["postprocess_reason"]


def test_reference_entry_must_match_target_paper(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Different Toolkit.",
            "paper_level_summary_zh": "参考文献不匹配。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": "The method follows the implementation [23].",
                    "evidence_context": "The method follows the implementation [23].",
                    "reference_entry": "[23] Different Toolkit.",
                    "why_this_judgment_zh": "模型误归因。",
                    "copy_ready_zh": "不应纳入。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="The method follows the implementation [23].\n\nReferences\n[23] Different Toolkit.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "exclude"
    assert evidence["claim_type"] == "false_positive"
    assert "reference_entry_target_mismatch" in evidence["postprocess_reason"]


def test_rfmicro_usrp_reference_not_target_is_excluded(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] USRP reader open source project.",
            "paper_level_summary_zh": "USRP 项目不是目标论文。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": "We implement RF-Mic according to the open source project [23].",
                    "evidence_context": "We implement RF-Mic according to the open source project [23].",
                    "reference_entry": "[23] USRP reader open source project.",
                    "why_this_judgment_zh": "错误将 USRP 项目当成目标论文。",
                    "copy_ready_zh": "不应纳入。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="RF-Mic Target Paper",
            text="We implement RF-Mic according to the open source project [23].\n\nReferences\n[23] USRP reader open source project.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "exclude"
    assert evidence["claim_type"] == "false_positive"
    assert evidence["target_reference_entry_matches_target"] is False


def test_title_only_submm_not_include(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Sub-mm Target Paper.",
            "paper_level_summary_zh": "只有题名包含 sub-mm。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "submm_precision_claim",
                    "evidence_quote": "Sub-mm Target Paper is listed as a related work [4].",
                    "evidence_context": "Sub-mm Target Paper is listed as a related work [4].",
                    "reference_entry": "[4] Sub-mm Target Paper.",
                    "why_this_judgment_zh": "只有题名包含 sub-mm。",
                    "copy_ready_zh": "不应写成第三方亚毫米能力佐证。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Sub-mm Target Paper",
            text="Sub-mm Target Paper is listed as a related work [4].\n\nReferences\n[4] Sub-mm Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "review"
    assert evidence["claim_type"] == "ordinary_reference"
    assert "title_or_reference_only_not_include" in evidence["postprocess_reason"]


def test_submm_body_claim_can_include(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Target Paper.",
            "paper_level_summary_zh": "正文亚毫米能力。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "submm_precision_claim",
                    "evidence_quote": "The system detects sub-millimeter-level vibrations using Target Paper [4].",
                    "evidence_context": "The system detects sub-millimeter-level vibrations using Target Paper [4].",
                    "reference_entry": "[4] Target Paper.",
                    "why_this_judgment_zh": "正文明确 sub-millimeter-level 并锚定 [4]。",
                    "copy_ready_zh": "可作为直接亚毫米能力佐证。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="The system detects sub-millimeter-level vibrations using Target Paper [4].\n\nReferences\n[4] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "include"
    assert evidence["claim_type"] == "submm_precision_claim"


def test_through_wall_body_claim_can_include(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[5]",
            "target_reference_entry": "[5] Target Paper.",
            "paper_level_summary_zh": "穿墙能力。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
                    "evidence_quote": "Target Paper enables through-wall eavesdropping with RFID [5].",
                    "evidence_context": "Target Paper enables through-wall eavesdropping with RFID [5].",
                    "reference_entry": "[5] Target Paper.",
                    "why_this_judgment_zh": "正文明确 through-wall eavesdropping 并锚定 [5]。",
                    "copy_ready_zh": "可作为穿墙窃听能力佐证。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Target Paper enables through-wall eavesdropping with RFID [5].\n\nReferences\n[5] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "include"
    assert evidence["claim_type"] == "through_wall_eavesdropping"


def test_through_wall_ordinary_reference_is_calibrated_to_include(db_session_factory, tmp_path, monkeypatch):
    quote = "Wang et al. [23] extended RFID sensing to enable through-wall eavesdropping."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "能力认可。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "正文说明目标论文扩展 RFID sensing 以实现 through-wall eavesdropping。",
                    "copy_ready_zh": "可作为能力认可佐证。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[23] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "include"
    assert evidence["claim_type"] == "through_wall_eavesdropping"


def test_plain_eavesdropping_without_through_wall_not_include(db_session_factory, tmp_path, monkeypatch):
    quote = (
        "TagBug places RFID tags on the surrounding objects around the loudspeaker "
        "and collects the backscattered RFID signal for eavesdropping [6]."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[6]",
            "target_reference_entry": "[6] Target Paper.",
            "paper_level_summary_zh": "普通 eavesdropping。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "capability_recognition",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[6] Target Paper.",
                    "why_this_judgment_zh": "未给出亚毫米级精度或能力的具体陈述。",
                    "copy_ready_zh": "只能作为候选复核。",
                    "confidence": "medium",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[6] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "review"
    assert evidence["claim_type"] != "through_wall_eavesdropping"
    assert "reason_text_indicates_weak_evidence" in evidence["postprocess_reason"]


def test_limitation_language_downgrades_through_wall_include(db_session_factory, tmp_path, monkeypatch):
    quote = (
        "[23] utilizes RFID tags and cGAN to perform acoustic eavesdropping, "
        "but this approach is less practical as it requires pre-installing RFID tags near the target."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "局限性反馈。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "正文提到 eavesdropping，但同时说明 less practical。",
                    "copy_ready_zh": "该证据包含实用性不足反馈。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[23] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "review"
    assert evidence["claim_type"] == "limitation_feedback"
    assert "limitation_language_not_include" in evidence["postprocess_reason"]


def test_duplicate_evidence_keeps_strongest_claim_type(db_session_factory, tmp_path, monkeypatch):
    quote = "The system detects sub-millimeter-level vibrations using Target Paper [4]."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Target Paper.",
            "paper_level_summary_zh": "重复证据。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[4] Target Paper.",
                    "why_this_judgment_zh": "方法使用。",
                    "copy_ready_zh": "方法使用表述。",
                    "confidence": "high",
                },
                {
                    "recommendation": "include",
                    "claim_type": "submm_precision_claim",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[4] Target Paper.",
                    "why_this_judgment_zh": "直接亚毫米能力。",
                    "copy_ready_zh": "亚毫米能力表述。",
                    "confidence": "high",
                },
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[4] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidences = json.loads(result.parsed_result_json)["evidences"]

    assert len(evidences) == 1
    assert evidences[0]["claim_type"] == "submm_precision_claim"


def test_duplicate_through_wall_evidence_only_appears_once_in_report(db_session_factory, tmp_path, monkeypatch):
    quote = "Wang et al. [23] extended RFID sensing to enable through-wall eavesdropping."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "重复 through-wall 证据。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "普通相关工作。",
                    "copy_ready_zh": "候选。",
                    "confidence": "medium",
                },
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "正文明确 enable through-wall eavesdropping。",
                    "copy_ready_zh": "能力认可佐证。",
                    "confidence": "high",
                },
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[23] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidences = json.loads(result.parsed_result_json)["evidences"]
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert len(evidences) == 1
    assert evidences[0]["claim_type"] == "through_wall_eavesdropping"
    assert "### 1. 穿墙窃听能力佐证" in markdown
    assert "### 2. 穿墙窃听能力佐证" not in markdown


def test_duplicate_template_direct_results_are_deduped_in_report(db_session_factory, tmp_path):
    quote = "Similarly, Wang et al. [102] proposed Tag-Bug to enable thru-the-wall eavesdropping."
    payload = {
        "target_reference_marker": "[102]",
        "target_reference_entry": "[102] Target Paper.",
        "paper_level_summary_zh": "重复结果。",
        "evidences": [
            {
                "recommendation": "include",
                "claim_type": "through_wall_eavesdropping",
                "evidence_quote": quote,
                "evidence_context": quote,
                "reference_entry": "[102] Target Paper.",
                "why_this_judgment_zh": "正文明确 through-wall eavesdropping。",
                "copy_ready_zh": "能力认可佐证。",
                "confidence": "high",
            }
        ],
    }
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            title="Rf sensing security and malicious exploitation",
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[102] Target Paper.",
        )
        item = db.get(DeepAnalysisQueueItem, item_id)
        for _ in range(2):
            db.add(
                FulltextAnalysisResult(
                    scholar_session_id=session_id,
                    queue_item_id=item_id,
                    citation_edge_id=item.citation_edge_id,
                    analysis_scope="fulltext_template_direct",
                    status="succeeded",
                    parsed_result_json=json.dumps(payload, ensure_ascii=False),
                )
            )
        db.commit()
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert markdown.count("Similarly, Wang et al. **[102]** proposed Tag-Bug") == 2
    assert "### 1. 穿墙窃听能力佐证" in markdown
    assert "### 2. 穿墙窃听能力佐证" not in markdown


def test_include_claim_type_must_be_strong(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "局限性不能推荐纳入。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "limitation_feedback",
                    "evidence_quote": "Target Paper has limitations under motion [23].",
                    "evidence_context": "Target Paper has limitations under motion [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "局限性反馈。",
                    "copy_ready_zh": "不能作为正向亮点。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Target Paper has limitations under motion [23].\n\nReferences\n[23] Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "review"
    assert "include_claim_type_not_strong" in evidence["postprocess_reason"]


def test_grouped_citation_without_target_specific_description_not_include(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "成组引用。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "capability_recognition",
                    "evidence_quote": "Prior systems [22], [23], [24] explored RFID sensing.",
                    "evidence_context": "Prior systems [22], [23], [24] explored RFID sensing.",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "成组引用。",
                    "copy_ready_zh": "需要复核。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Prior systems [22], [23], [24] explored RFID sensing.\n\nReferences\n[22] Other.\n[23] Target Paper.\n[24] Another.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "review"
    assert evidence["grouped_citation"] is True
    assert "grouped_citation_requires_review" in evidence["postprocess_reason"]


def test_evidence_reference_entry_uses_citing_paper_raw_reference(db_session_factory, tmp_path, monkeypatch):
    raw_entry = "[57] C. Wang et al., Thru-the-wall Eavesdropping on Loudspeakers via RFID, 2022."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[57]",
            "target_reference_entry": "[57] Normalized Target Reference.",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
                    "evidence_quote": "Target Paper demonstrates through-the-wall eavesdropping [57].",
                    "evidence_context": "Target Paper demonstrates through-the-wall eavesdropping [57].",
                    "reference_entry": "[57] Normalized Target Reference.",
                    "why_this_judgment_zh": "正文锚定 [57]。",
                    "copy_ready_zh": "可纳入。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Thru-the-wall Eavesdropping on Loudspeakers via RFID",
            text=f"Target Paper demonstrates through-the-wall eavesdropping [57].\n\nReferences\n{raw_entry}",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert evidence["evidence_reference_marker"] == "[57]"
    assert evidence["evidence_reference_entry_raw"] == raw_entry
    assert evidence["reference_match_status"] == "matched"
    assert "对应参考文献（引用论文原文 References 中的条目）" in markdown
    assert "C. Wang et al." in markdown
    assert "Thru-the-wall Eavesdropping on Loudspeakers via RFID" in markdown


def test_report_reference_entry_preserves_marker_number(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[6]",
            "target_reference_entry": "[6] Target Paper.",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
                    "evidence_quote": "Target Paper enables through-wall eavesdropping [6].",
                    "evidence_context": "Target Paper enables through-wall eavesdropping [6].",
                    "reference_entry": "[6] Target Paper.",
                    "why_this_judgment_zh": "正文锚定 [6]。",
                    "copy_ready_zh": "可纳入。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Target Paper enables through-wall eavesdropping [6].\n\nReferences\n[6] Target Paper.",
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "**[6]**" in markdown
    assert "Target Paper" in markdown


def test_report_does_not_use_same_normalized_target_reference_for_every_card(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            title="First Citing Paper",
            target_title="Target Paper",
            text="First paper uses Target Paper [4].\n\nReferences\n[4] Target Paper raw entry from citing paper.",
        )
        item = db.get(DeepAnalysisQueueItem, item_id)
        result = FulltextAnalysisResult(
            scholar_session_id=session_id,
            queue_item_id=item_id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope="fulltext_template_direct",
            status="succeeded",
            parsed_result_json=json.dumps(
                {
                    "target_reference_marker": "[4]",
                    "target_reference_entry": "[4] Normalized Target.",
                    "paper_level_summary_zh": "摘要。",
                    "evidences": [
                        {
                            "recommendation": "include",
                            "claim_type": "method_use",
                            "evidence_quote": "First paper uses Target Paper [4].",
                            "evidence_context": "First paper uses Target Paper [4].",
                            "reference_entry": "[4] Normalized Target.",
                            "evidence_reference_marker": "[4]",
                            "evidence_reference_entry_raw": "[4] Target Paper raw entry from citing paper.",
                            "reference_match_status": "matched",
                            "why_this_judgment_zh": "正文锚定 [4]。",
                            "copy_ready_zh": "可纳入。",
                            "confidence": "high",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.add(result)
        db.commit()
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    assert "raw entry from citing paper." in markdown
    assert "[4] Normalized Target." not in markdown


def test_unresolved_reference_marker_goes_to_review(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "无法解析 reference entry。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "method_use",
                    "evidence_quote": "The implementation follows Target Paper [23].",
                    "evidence_context": "The implementation follows Target Paper [23].",
                    "reference_entry": "[23] Target Paper.",
                    "why_this_judgment_zh": "正文锚定 [23]。",
                    "copy_ready_zh": "应降级。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="The implementation follows Target Paper [23].",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["recommendation"] == "review"
    assert evidence["reference_match_status"] == "unresolved"
    assert "reference_entry_unresolved" in evidence["postprocess_reason"]


def test_long_fulltext_uses_compact_fallback(db_session_factory, tmp_path, monkeypatch):
    from app.core.config import settings

    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Target Paper.",
            "paper_level_summary_zh": "compact fallback 摘要。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "submm_precision_claim",
                    "evidence_quote": "The system detects sub-millimeter-level vibrations using Target Paper [4].",
                    "evidence_context": "The system detects sub-millimeter-level vibrations using Target Paper [4].",
                    "reference_entry": "[4] Target Paper.",
                    "why_this_judgment_zh": "正文明确 sub-millimeter-level 并锚定 [4]。",
                    "copy_ready_zh": "可纳入。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.settings",
        replace(settings, fulltext_direct_max_chars=1200),
    )
    long_text = (
        "Abstract\nThis paper studies RFID sensing.\n\n"
        + ("filler text without evidence. " * 200)
        + "\nThe system detects sub-millimeter-level vibrations using Target Paper [4].\n\n"
        + ("more filler. " * 200)
        + "\nReferences\n[4] Target Paper."
    )
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=long_text,
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        diagnostics = json.loads(result.candidate_spans_json)
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert result.analysis_scope == "fulltext_template_direct"
    assert result.status == "succeeded"
    assert diagnostics["compact_fallback"] is True
    assert diagnostics["original_fulltext_too_long"] is True
    assert evidence["recommendation"] == "include"


def test_worker_dispatches_fulltext_template_direct_scope(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(template_direct_payload())
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Target Paper is discussed as a capability source [23]. References [23] Target Paper.",
        )
        task = ScholarFulltextService(db).enqueue_analyze_queue(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        payload = json.loads(task.payload_json)

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        result = db.query(FulltextAnalysisResult).one()

    assert payload["analysis_scope"] == "fulltext_template_direct"
    assert completed.status == "succeeded"
    assert "analysis_scope=fulltext_template_direct" in completed.stage_message
    assert provider.requests[0].analysis_scope == "fulltext_template_direct"
    assert result.analysis_scope == "fulltext_template_direct"


def test_result_scope_is_fulltext_template_direct(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(template_direct_payload())
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )

    assert result.analysis_scope == "fulltext_template_direct"
    assert result.status == "succeeded"


def test_direct_result_schema_has_evidences(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(template_direct_payload())
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        payload = json.loads(result.parsed_result_json)

    assert payload["target_reference_marker"] == "[23]"
    assert payload["target_reference_entry"] == "[23] Target Paper. doi:10.1145/target"
    assert payload["paper_level_summary_zh"]
    assert payload["evidences"]


def test_existing_anchor_direct_result_does_not_skip_template_direct(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(template_direct_payload())
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        item = db.get(DeepAnalysisQueueItem, item_id)
        db.add(
            FulltextAnalysisResult(
                scholar_session_id=session_id,
                queue_item_id=item_id,
                citation_edge_id=item.citation_edge_id,
                analysis_scope="fulltext_anchor_direct",
                status="succeeded",
                parsed_result_json=json.dumps({"findings": []}),
                candidate_spans_json=json.dumps({}),
            )
        )
        item.queue_status = "selected"
        db.commit()

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        assert completed is None
        task = ScholarFulltextService(db).enqueue_analyze_queue(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        scopes = [
            row.analysis_scope
            for row in db.query(FulltextAnalysisResult)
            .order_by(FulltextAnalysisResult.id)
            .all()
        ]

    assert task.payload_json
    assert completed.status == "succeeded"
    assert scopes == ["fulltext_anchor_direct", "fulltext_template_direct"]


def test_template_direct_failure_records_error_message(db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: RaisingSchemaErrorLlmProvider(),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        ScholarFulltextService(db).enqueue_analyze_queue(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )

        completed = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        result = db.query(FulltextAnalysisResult).one()
        parsed = json.loads(result.parsed_result_json)

    assert completed.status == "failed"
    assert "failed_item_count=1" in completed.error_message
    assert result.analysis_scope == "fulltext_template_direct"
    assert result.status == "failed"
    assert result.error_message
    assert parsed["error"] == "provider_schema_error"


def _enable_direct_builtin(db, session_id, template_type):
    service = TemplateService(db)
    builtin = next(
        template
        for template in service.list_builtin_templates()
        if template.template_type == template_type
    )
    return service.enable_template(session_id=session_id, template_id=builtin.id)


def test_template_direct_canonical_claim_and_matched_template_are_persisted(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23] was the first work to recover speech by sensing "
        "speaker vibrations."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "发现明确首次评价。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "first_or_seminal_claim",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "正文明确将 first 作用于目标论文。",
                    "copy_ready_zh": "后续论文明确称目标论文为首次工作。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[23] A. Author. Target Paper.",
        )
        enabled = _enable_direct_builtin(
            db, session_id, "first_or_seminal_claim"
        )
        enabled_id = enabled.id
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["claim_type"] == "first_or_seminal_claim"
    assert evidence["recommendation"] == "include"
    assert evidence["matched_template_ids"] == [enabled_id]
    assert evidence["matched_template_types"] == ["first_or_seminal_claim"]
    assert evidence["template_satisfied"] is True


def test_template_direct_preserves_distinct_evidence_locations_and_multiple_templates(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    first_quote = "Target Paper [23] was the first work to solve this task."
    positive_quote = (
        "Target Paper [23] provides an effective and robust solution with "
        "significantly higher accuracy."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "发现两个不同引用语境。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "first_or_seminal_claim",
                    "evidence_quote": first_quote,
                    "evidence_context": first_quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "首次评价。",
                    "copy_ready_zh": "首次评价证据。",
                    "confidence": "high",
                },
                {
                    "recommendation": "include",
                    "claim_type": "positive_evaluation",
                    "evidence_quote": positive_quote,
                    "evidence_context": positive_quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "明确正向评价。",
                    "copy_ready_zh": "正向评价证据。",
                    "confidence": "high",
                },
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                first_quote
                + "\n\n"
                + positive_quote
                + "\n\nReferences\n[23] A. Author. Target Paper."
            ),
        )
        first = _enable_direct_builtin(
            db, session_id, "first_or_seminal_claim"
        )
        positive = _enable_direct_builtin(
            db, session_id, "positive_evaluation"
        )
        first_id = first.id
        positive_id = positive.id
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidences = json.loads(result.parsed_result_json)["evidences"]

    assert len(evidences) == 2
    assert evidences[0]["matched_template_ids"] == [first_id]
    assert evidences[1]["matched_template_ids"] == [positive_id]
    assert {item["claim_type"] for item in evidences} == {
        "first_or_seminal_claim",
        "positive_evaluation",
    }


def test_template_direct_filter_reasons_are_structured_and_aggregated(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Target Paper is listed among related work [22], [23]."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "仅发现成组普通引用。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "普通 related-work 成组引用。",
                    "copy_ready_zh": "不建议纳入。",
                    "confidence": "low",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[22] Other Paper.\n[23] A. Author. Target Paper.",
        )
        _enable_direct_builtin(db, session_id, "positive_evaluation")
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        result = db.query(FulltextAnalysisResult).order_by(
            FulltextAnalysisResult.id.desc()
        ).first()
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        diagnostics = json.loads(result.candidate_spans_json)
        debug_row = ScholarFulltextService(db).list_analysis_debug_rows(
            session_id
        )[0]

    assert evidence["original_recommendation"] == "exclude"
    assert evidence["final_recommendation"] == "exclude"
    assert evidence["matched_template_ids"] == []
    assert "ordinary_reference" in evidence["failure_reason_codes"]
    assert "grouped_citation_not_allowed" in evidence["failure_reason_codes"]
    assert summary["filtered_findings_count"] == 1
    assert summary["filter_reason_distribution"]["ordinary_reference"] == 1
    assert diagnostics["filter_reason_distribution"]["grouped_citation_not_allowed"] == 1
    assert debug_row["filter_reason_distribution"]["ordinary_reference"] == 1


def test_template_direct_summary_counts_only_current_run_results(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingTemplateDirectProvider(template_direct_payload())
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "Target Paper is discussed as a capability source [23].\n\n"
                "References\n[23] Target Paper. doi:10.1145/target"
            ),
        )
        item = db.get(DeepAnalysisQueueItem, item_id)
        db.add(
            FulltextAnalysisResult(
                scholar_session_id=session_id,
                queue_item_id=item_id,
                citation_edge_id=item.citation_edge_id,
                analysis_scope="fulltext_anchor_direct",
                status="succeeded",
                parsed_result_json=json.dumps({"findings": []}),
                candidate_spans_json=json.dumps({}),
            )
        )
        db.commit()
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )

    assert summary["current_run_result_count"] == 1
    assert summary["current_run_succeeded_count"] == 1
    assert summary["current_run_failed_count"] == 0
    assert summary["session_fulltext_result_count"] == 2
    assert summary["fulltext_result_count"] == 1
