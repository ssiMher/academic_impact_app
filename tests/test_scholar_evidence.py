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
    HighlightCard,
    PdfAsset,
    Publication,
    ScholarAnalysisSession,
    StrongEvidence,
)
from app.providers.errors import ProviderException
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.repositories.task_repo import TaskRepository
from app.analysis.prompt_builder import build_fulltext_direct_prompt
from app.analysis.citation_anchor import (
    extract_target_reference_contexts,
    find_target_reference_anchor,
    reference_entries_by_marker,
)
from app.schemas.llm import TemplateDirectEvidence
from app.analysis.template_direct_postprocess import (
    postprocess_template_direct_payload,
)
from app.services.evidence_service import EvidenceService
from app.services.scholar_fulltext_service import ScholarFulltextService
from app.schemas.provider import ProviderErrorCode
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from app.tasks.handlers.analyze_scholar_queue import handle_analyze_scholar_queue
from app.schemas.llm import CitationAnalysisResponse, TemplateDirectAnalysisResult
from app.services.highlight_card_service import HighlightCardService
from app.services.template_direct_persistence_service import (
    TemplateDirectPersistenceService,
)
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


def set_model_template_decision(
    provider,
    template_ids,
    *,
    evidence_indexes=None,
    satisfied=True,
    reason="The evidence satisfies the active template.",
):
    indexes = (
        list(range(len(provider.response.evidences)))
        if evidence_indexes is None
        else evidence_indexes
    )
    for index in indexes:
        evidence = provider.response.evidences[index]
        evidence.matched_template_ids = list(template_ids) if satisfied else []
        evidence.template_satisfied = satisfied
        evidence.template_match_reason = reason if satisfied else ""
        evidence.template_failure_reason = "" if satisfied else reason


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


class RecoveringTemplateDirectProvider:
    provider_name = "recovering-template-direct-llm"

    def __init__(self, response):
        self.response = TemplateDirectAnalysisResult.model_validate(response)
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            raise ProviderException(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "truncated template-direct JSON",
                self.provider_name,
                raw_output_preview='{"evidences": [{"evidence_quote": "cut',
                parse_error="Unterminated string",
            )
        return self.response


class RecoveringTransientNetworkProvider:
    provider_name = "recovering-network-llm"

    def __init__(self, response):
        self.response = TemplateDirectAnalysisResult.model_validate(response)
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            raise ProviderException(
                ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                "temporary network failure",
                self.provider_name,
            )
        return self.response


class FailingIfCalledLlmProvider:
    provider_name = "should-not-be-called"

    def analyze_citation(self, request):
        raise AssertionError("LLM should not be called")


def template_direct_payload(
    *,
    marker: str = "[23]",
    quote: str = "Target Paper is discussed as a capability source [23].",
    claim_type: str = "capability_recognition",
    recommendation: str = "include",
):
    return {
        "target_reference_marker": marker,
        "target_reference_entry": f"{marker} Target Paper. doi:10.1145/target",
        "paper_level_summary_zh": "引用论文已完成全文模板直读分析。",
        "evidences": [
            {
                "recommendation": recommendation,
                "claim_type": claim_type,
                "evidence_quote": quote,
                "evidence_context": f"In the body, {quote} The surrounding context explains the claim.",
                "reference_entry": f"{marker} Target Paper. doi:10.1145/target",
                "why_this_judgment_zh": "正文通过目标引用编号锚定目标论文，并说明能力判断。",
                "copy_ready_zh": "引用论文在正文中明确讨论目标论文的能力表现，可纳入报告。",
                "confidence": "high",
            }
        ],
    }


def test_reference_anchor_falls_back_when_references_heading_is_missing():
    fulltext = (
        "Wang et al. [26] proposed a moving label detection mechanism that "
        "improves detection efficiency.\n\n"
        "[24] A. Other, “Earlier RFID sensing,” IEEE Trans. Mobile Comput., "
        "vol. 18, no. 1, pp. 1-12, 2019.\n"
        "[25] B. Other, “Collision decoding,” Proc. ACM MobiCom, pp. 20-31, 2020.\n"
        "[26] C. Wang et al., “Probing into the physical layer: Moving tag "
        "detection for large-scale RFID systems,” IEEE Trans. Mobile Comput., "
        "vol. 19, no. 5, pp. 1200-1215, May 2020.\n"
        "[27] D. Other, “Backscatter systems,” IEEE INFOCOM, pp. 40-50, 2021.\n"
    )

    anchor = find_target_reference_anchor(
        fulltext,
        "Probing into the Physical Layer: Moving Tag Detection for Large-Scale RFID Systems",
        cited_authors=["Chuyu Wang"],
    )
    entries = reference_entries_by_marker(fulltext)
    contexts = extract_target_reference_contexts(fulltext, "26")

    assert anchor is not None
    assert anchor.reference_marker == "26"
    assert "Probing into the physical layer" in entries["26"]
    assert len(contexts) == 1
    assert "proposed a moving label detection mechanism" in contexts[0].context_text
    assert "IEEE Trans. Mobile Comput." not in contexts[0].context_text


def test_reference_fallback_does_not_treat_body_marker_as_bibliography():
    fulltext = (
        "[26] demonstrates an effective sensing method in the main body.\n"
        "The following paragraph continues the scientific discussion without "
        "a bibliography or publication metadata."
    )

    assert reference_entries_by_marker(fulltext) == {}
    assert find_target_reference_anchor(fulltext, "Effective Sensing Method") is None


def test_result_844_resolved_marker_survives_glued_reference_formatting():
    target_title = (
        "Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing "
        "Sub-mm Level Vibration"
    )
    target_entry = (
        "[57] Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying Chen, "
        "Yanling Bu,KaiZhang,SangluLu,Thru-the-walleavesdroppingonloudspeakers "
        "viaRFIDbycapturingsub-mmlevelvibration, 2022."
    )
    quote = (
        "[57] demonstrates the possibility of using low-cost and easily "
        "overlooked RFID tags to effectively perform through-the-wall "
        "eavesdropping. A battery-free method called Tag-Bug is proposed."
    )
    payload = postprocess_template_direct_payload(
        {
            "target_reference_marker": "[57]",
            "target_reference_entry": target_entry,
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "capability_recognition",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": (
                        "Chuyu Wang, Lei Xie, Yuancan Lin, Wei Wang, Yingying "
                        "Chen, Yanling Bu, Kai Zhang, Sanglu Lu, Thru-the-wall "
                        "Eavesdropping on Loudspeakers via RFID by Capturing "
                        "Sub-mm Level Vibration, 2022."
                    ),
                    "why_this_judgment_zh": "正文明确展示目标论文的能力。",
                    "copy_ready_zh": "后续论文明确肯定该方法的穿墙窃听能力。",
                    "confidence": "high",
                }
            ],
        },
        citing_paper_title="A Survey",
        cited_paper_title=target_title,
        target_reference_marker="[57]",
        target_reference_entry=target_entry,
        reference_entries_by_marker={"57": target_entry},
        target_reference_resolved=True,
    )
    evidence = payload["evidences"][0]

    assert evidence["reference_match_status"] == "matched"
    assert evidence["reference_alignment_method"] in {
        "normalized_title_match",
        "marker_resolver_match",
    }
    assert evidence["recommendation"] == "include"
    assert evidence["claim_type"] != "false_positive"
    assert evidence["original_claim_type"] == "capability_recognition"
    assert evidence["final_claim_type"] != "false_positive"


def _postprocess_anchor_case(
    *,
    quote,
    context=None,
    claim_type="through_wall_eavesdropping",
    recommendation="include",
    target_marker="[57]",
    reference_entries=None,
):
    target_title = (
        "Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing "
        "Sub-mm Level Vibration"
    )
    target_entry = (
        "[57] C. Wang, L. Xie, Y. Lin, W. Wang, Y. Chen, Y. Bu, K. Zhang, "
        "S. Lu. Thru-the-wall Eavesdropping on Loudspeakers via RFID by "
        "Capturing Sub-mm Level Vibration. 2022."
    )
    return postprocess_template_direct_payload(
        {
            "target_reference_marker": target_marker,
            "target_reference_entry": target_entry,
            "evidences": [
                {
                    "recommendation": recommendation,
                    "claim_type": claim_type,
                    "evidence_quote": quote,
                    "evidence_context": context if context is not None else quote,
                    "reference_entry": target_entry,
                    "why_this_judgment_zh": "正文描述目标方法的具体能力。",
                    "copy_ready_zh": "后续工作明确描述了目标方法的能力。",
                    "confidence": "high",
                }
            ],
        },
        citing_paper_title="A Survey",
        cited_paper_title=target_title,
        target_reference_marker=target_marker,
        target_reference_entry=target_entry,
        reference_entries_by_marker=reference_entries or {"57": target_entry},
        cited_paper_authors=["Chuyu Wang", "Lei Xie"],
        cited_paper_year=2022,
        target_reference_resolved=True,
    )["evidences"][0]


def test_same_paragraph_unique_method_name_inherits_target_anchor():
    anchor = (
        "[57] demonstrates an effective through-the-wall eavesdropping "
        "capability. A battery-free method called Tag-Bug is proposed."
    )
    quote = "Tag-Bug captures loudspeaker vibrations through a nearby RFID tag."
    evidence = _postprocess_anchor_case(
        quote=quote,
        context=f"{anchor} {quote}",
        claim_type="rfid_loudspeaker_vibration",
    )

    assert evidence["target_anchor_inherited"] is True
    assert evidence["target_anchor_status"] == "inherited_named_method"
    assert evidence["reference_match_status"] == "matched"
    assert evidence["recommendation"] == "include"


def test_cross_paragraph_method_name_does_not_inherit_target_anchor():
    anchor = "[57] introduces a battery-free method called Tag-Bug."
    quote = "Tag-Bug captures loudspeaker vibrations through a nearby RFID tag."
    evidence = _postprocess_anchor_case(
        quote=quote,
        context=f"{anchor}\n\n{quote}",
        claim_type="rfid_loudspeaker_vibration",
    )

    assert evidence["target_anchor_inherited"] is False
    assert evidence["recommendation"] == "exclude"
    assert "target_anchor_missing" in evidence["postprocess_reason"]


def test_other_marker_between_anchor_and_method_blocks_inheritance():
    anchor = "[57] introduces a battery-free method called Tag-Bug."
    quote = "Tag-Bug captures loudspeaker vibrations through a nearby RFID tag."
    evidence = _postprocess_anchor_case(
        quote=quote,
        context=f"{anchor} Another system [23] uses radar. {quote}",
        claim_type="rfid_loudspeaker_vibration",
        reference_entries={
            "23": "[23] A. Other. A radar system.",
            "57": (
                "[57] C. Wang et al. Thru-the-wall Eavesdropping on "
                "Loudspeakers via RFID by Capturing Sub-mm Level Vibration."
            ),
        },
    )

    assert evidence["target_anchor_inherited"] is False
    assert evidence["recommendation"] == "exclude"


def test_quote_with_other_marker_remains_false_positive():
    evidence = _postprocess_anchor_case(
        quote="Based on the Schrödinger equation [23], the system is modeled.",
        claim_type="method_use",
        reference_entries={
            "23": "[23] E. Schrödinger. An equation for wave mechanics.",
            "57": (
                "[57] C. Wang et al. Thru-the-wall Eavesdropping on "
                "Loudspeakers via RFID by Capturing Sub-mm Level Vibration."
            ),
        },
    )

    assert evidence["reference_match_status"] == "mismatch"
    assert evidence["recommendation"] == "exclude"
    assert evidence["claim_type"] == "false_positive"
    assert "reference_mismatch" in evidence["filter_reason_codes"]


def test_grouped_target_marker_uses_model_recommendation():
    evidence = _postprocess_anchor_case(
        quote=(
            "Prior systems [56], [57] demonstrate effective acoustic sensing."
        ),
        claim_type="positive_evaluation",
        reference_entries={
            "56": "[56] A. Other. Another system.",
            "57": (
                "[57] C. Wang et al. Thru-the-wall Eavesdropping on "
                "Loudspeakers via RFID by Capturing Sub-mm Level Vibration."
            ),
        },
    )

    assert evidence["grouped_citation"] is True
    assert evidence["recommendation"] == "include"
    assert "grouped_citation_requires_review" not in evidence.get(
        "postprocess_reason", ""
    )


def test_nearby_limitation_context_does_not_overwrite_capability_quote():
    quote = "Jingyi et al. [57] measure 6-DoF position with moire patterns."
    context = (
        "Earlier approaches have limited measurable degrees of freedom. "
        f"{quote}"
    )
    evidence = _postprocess_anchor_case(
        quote=quote,
        context=context,
        claim_type="capability_recognition",
        recommendation="review",
    )

    assert evidence["final_claim_type"] == "capability_recognition"


def test_reprocessing_stale_mismatch_restores_original_claim_and_canonical_reasons():
    stale = _postprocess_anchor_case(
        quote="[57] demonstrates an effective through-the-wall capability.",
        claim_type="capability_recognition",
    )
    stale.update(
        {
            "claim_type": "false_positive",
            "recommendation": "exclude",
            "reference_match_status": "mismatch",
            "filter_reason_codes": ["reference_mismatch"],
            "failure_reason_codes": ["reference_mismatch"],
            "postprocess_reason": "reference_entry_target_mismatch",
            "template_failure_reason": "正向评价: reference mismatch",
        }
    )
    refreshed = _postprocess_anchor_case(
        quote=stale["evidence_quote"],
        claim_type=stale["claim_type"],
        recommendation=stale["recommendation"],
    )
    # Simulate a persisted result carrying the original/final split.
    refreshed_payload = postprocess_template_direct_payload(
        {
            "target_reference_marker": "[57]",
            "target_reference_entry": stale["normalized_target_reference"],
            "evidences": [stale],
        },
        citing_paper_title="A Survey",
        cited_paper_title=(
            "Thru-the-wall Eavesdropping on Loudspeakers via RFID by "
            "Capturing Sub-mm Level Vibration"
        ),
        target_reference_marker="[57]",
        target_reference_entry=stale["normalized_target_reference"],
        reference_entries_by_marker={
            "57": stale["evidence_reference_entry_raw"]
        },
        target_reference_resolved=True,
    )["evidences"][0]

    assert refreshed["reference_match_status"] == "matched"
    assert refreshed_payload["original_claim_type"] == "capability_recognition"
    assert refreshed_payload["final_claim_type"] != "false_positive"
    assert refreshed_payload["original_recommendation"] == "include"
    assert refreshed_payload["final_recommendation"] == "include"
    assert "reference_mismatch" not in refreshed_payload["filter_reason_codes"]


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


def test_template_direct_prompt_uses_resolved_marker_without_references_heading(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[26]",
            "target_reference_entry": (
                "[26] C. Wang et al., Probing into the physical layer: Moving "
                "tag detection for large-scale RFID systems, 2020."
            ),
            "paper_level_summary_zh": "未发现满足模板的强证据。",
            "evidences": [],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    target_title = (
        "Probing into the Physical Layer: Moving Tag Detection for Large-Scale "
        "RFID Systems"
    )
    full_text = (
        "Wang et al. [26] proposed a moving label detection mechanism that "
        "improves detection efficiency.\n\n"
        "[24] A. Other, “Earlier RFID sensing,” IEEE Trans. Mobile Comput., "
        "vol. 18, pp. 1-12, 2019.\n"
        "[25] B. Other, “Collision decoding,” Proc. ACM MobiCom, pp. 20-31, 2020.\n"
        "[26] C. Wang et al., “Probing into the physical layer: Moving tag "
        "detection for large-scale RFID systems,” IEEE Trans. Mobile Comput., "
        "vol. 19, no. 5, pp. 1200-1215, May 2020.\n"
        "[27] D. Other, “Backscatter systems,” IEEE INFOCOM, pp. 40-50, 2021.\n"
    )

    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title=target_title,
            cited_authors=["Chuyu Wang"],
            text=full_text,
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        diagnostics = json.loads(result.candidate_spans_json)

    prompt = provider.requests[0].prompt_text
    assert "DETERMINISTIC_TARGET_REFERENCE_MARKER: [26]" in prompt
    assert "DETERMINISTIC_TARGET_REFERENCE_ENTRY:" in prompt
    assert "DETERMINISTIC_TARGET_REFERENCE_CONTEXTS:" in prompt
    assert "proposed a moving label detection mechanism" in prompt
    assert diagnostics["reference_anchor_source"] == "deterministic_resolver"
    assert diagnostics["target_reference_context_count"] == 1


def test_resolved_capability_summary_can_become_positive_strong_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    target_title = (
        "Probing into the Physical Layer: Moving Tag Detection for Large-Scale "
        "RFID Systems"
    )
    quote = (
        "Wang et al. [26] proposed a moving label detection mechanism, and this "
        "mechanism utilizes the useless collision signal in the RFID system to "
        "achieve time efficiency."
    )
    raw_entry = (
        "[26] C. Wang et al., “Probing into the physical layer: Moving tag "
        "detection for large-scale RFID systems,” IEEE Trans. Mobile Comput., "
        "vol. 19, no. 5, pp. 1200-1215, May 2020."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[26]",
            "target_reference_entry": raw_entry,
            "paper_level_summary_zh": "正文概述目标论文的方法及效率收益。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "capability_summary",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": raw_entry,
                    "why_this_judgment_zh": "正文说明目标机制实现了时间效率提升。",
                    "copy_ready_zh": "后续论文概述了目标方法及其效率价值。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    full_text = (
        f"{quote}\n\n"
        "[24] A. Other, “Earlier RFID sensing,” IEEE Trans. Mobile Comput., "
        "vol. 18, pp. 1-12, 2019.\n"
        "[25] B. Other, “Collision decoding,” Proc. ACM MobiCom, pp. 20-31, 2020.\n"
        f"{raw_entry}\n"
        "[27] D. Other, “Backscatter systems,” IEEE INFOCOM, pp. 40-50, 2021.\n"
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title=target_title,
            cited_authors=["Chuyu Wang"],
            text=full_text,
        )
        builtin = next(
            template
            for template in TemplateService(db).list_builtin_templates()
            if template.template_type == "positive_evaluation"
        )
        enabled = TemplateService(db).enable_template(
            session_id=session_id,
            template_id=builtin.id,
        )
        enabled_id = enabled.id
        set_model_template_decision(provider, [enabled_id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        result_id = result.id
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong = db.query(StrongEvidence).one()

    assert evidence["reference_alignment_status"] == "matched"
    assert evidence["final_recommendation"] == "include"
    assert evidence["template_match_level"] == "strong"
    assert evidence["matched_template_ids"] == [enabled_id]
    assert strong.fulltext_result_id == result_id


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


def test_formal_evidence_list_uses_latest_result_per_queue_item(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        item = db.get(DeepAnalysisQueueItem, item_id)
        older = FulltextAnalysisResult(
            scholar_session_id=session_id,
            queue_item_id=item_id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope="fulltext_template_direct",
            status="succeeded",
            parsed_result_json='{"evidences":[]}',
        )
        newer = FulltextAnalysisResult(
            scholar_session_id=session_id,
            queue_item_id=item_id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope="fulltext_template_direct",
            status="succeeded",
            parsed_result_json='{"evidences":[]}',
        )
        db.add_all([older, newer])
        db.flush()
        evidence_service = EvidenceService(db)
        evidence_service.upsert_scholar_evidence(
            fulltext_result_id=older.id,
            scholar_session_id=session_id,
            queue_item_id=item_id,
            citation_edge_id=item.citation_edge_id,
            aspect="positive_evaluation",
            stance="positive",
            mention_type="template_direct",
            citation_text="Older duplicate quote [23].",
            highlight_keywords=[],
            evidence_reason="older",
            evidence_strength="strong",
            score=0.9,
            span_index=0,
            is_self_citation=False,
            third_party_status="third_party",
        )
        evidence_service.upsert_scholar_evidence(
            fulltext_result_id=newer.id,
            scholar_session_id=session_id,
            queue_item_id=item_id,
            citation_edge_id=item.citation_edge_id,
            aspect="positive_evaluation",
            stance="positive",
            mention_type="template_direct",
            citation_text="Latest canonical quote [23].",
            highlight_keywords=[],
            evidence_reason="latest",
            evidence_strength="strong",
            score=0.9,
            span_index=0,
            is_self_citation=False,
            third_party_status="third_party",
        )
        db.commit()

        rows = evidence_service.list_scholar_evidence(
            session_id,
            filters={"view": "all", "latest_only": True},
        )

    assert [row["evidence"].citation_text for row in rows] == [
        "Latest canonical quote [23]."
    ]


def test_candidate_layers_aggregate_latest_result_for_each_queue_item(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, first_item_id = seed_queue_item(db, tmp_path)
        _, second_item_id = seed_queue_item(db, tmp_path, title="Second citing paper")
        second_item = db.get(DeepAnalysisQueueItem, second_item_id)
        second_item.scholar_session_id = session_id
        payloads = [
            (
                first_item_id,
                {
                    "evidences": [
                        {
                            "final_recommendation": "include",
                            "final_claim_type": "positive_evaluation",
                            "stance": "positive",
                            "evidence_quote": "First evidence [23].",
                            "reference_alignment_status": "matched",
                            "matched_template_ids": [1],
                            "template_satisfied": True,
                        }
                    ]
                },
            ),
            (
                second_item_id,
                {
                    "evidences": [
                        {
                            "final_recommendation": "review",
                            "final_claim_type": "method_summary",
                            "evidence_quote": "Second evidence [23].",
                            "reference_alignment_status": "matched",
                            "matched_template_ids": [2],
                            "template_satisfied": True,
                        }
                    ]
                },
            ),
        ]
        for item_id, payload in payloads:
            db.add(
                FulltextAnalysisResult(
                    scholar_session_id=session_id,
                    queue_item_id=item_id,
                    analysis_scope="fulltext_template_direct",
                    status="succeeded",
                    parsed_result_json=json.dumps(payload),
                )
            )
        db.commit()

        layers = ScholarFulltextService(db).latest_direct_candidate_layers(session_id)

    assert layers["result_count"] == 2
    assert layers["counts"] == {"strong": 1, "review": 1, "excluded": 0}
    assert layers["strong_stance_counts"] == {
        "positive": 1,
        "neutral": 0,
        "negative": 0,
    }


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
                    "claim_type": "method_summary",
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
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "Target Paper appears in related work [23].\n\n"
                "References\n[23] Target Paper."
            ),
        )
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
                    "claim_type": "submm_precision_claim",
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
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                "Target Paper appears in related work [23].\n\n"
                "References\n[23] Target Paper."
            ),
        )
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
                    "claim_type": "submm_precision_claim",
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
    quote = "Target Paper is discussed among prior sensing systems [23]."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "摘要。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": quote,
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
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                f"{quote}\n\n"
                "References\n[23] Target Paper."
            ),
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        markdown = HighlightCardService(db).export_cards_markdown(session_id)

    main_section = markdown.split("候选复核附录", 1)[0]
    assert "**Target Paper** is discussed among prior sensing systems" not in main_section
    assert "**Target Paper** is discussed among prior sensing systems" in markdown


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
    assert evidence["claim_type"] == "submm_precision_claim"
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


def test_model_through_wall_claim_is_preserved(db_session_factory, tmp_path, monkeypatch):
    quote = "Wang et al. [23] extended RFID sensing to enable through-wall eavesdropping."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "能力认可。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
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
                    "recommendation": "review",
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
    assert evidence["recommendation"] == "review"


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
                    "recommendation": "review",
                    "claim_type": "limitation_feedback",
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
    assert evidence["recommendation"] == "review"


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


def test_model_limitation_claim_is_not_retyped_by_backend(db_session_factory, tmp_path, monkeypatch):
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

    assert evidence["recommendation"] == "include"
    assert evidence["claim_type"] == "limitation_feedback"


def test_grouped_citation_without_target_specific_description_not_include(db_session_factory, tmp_path, monkeypatch):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] Target Paper.",
            "paper_level_summary_zh": "成组引用。",
            "evidences": [
                {
                    "recommendation": "review",
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
    assert "grouped_citation_requires_review" not in evidence.get(
        "postprocess_reason",
        "",
    )


def test_grouped_citation_model_attribution_can_generate_strong_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23], together with Other System [22], provides an "
        "effective and robust solution that significantly improves accuracy."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "模型判断评价明确作用到目标论文。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "positive_evaluation",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "句子明确将正向能力评价作用到目标论文。",
                    "copy_ready_zh": "后续论文明确肯定目标论文的能力和效果。",
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
            text=(
                f"{quote}\n\nReferences\n"
                "[22] B. Author. Other System.\n"
                "[23] A. Author. Target Paper."
            ),
        )
        enabled = _enable_direct_builtin(db, session_id, "positive_evaluation")
        set_model_template_decision(provider, [enabled.id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = db.query(StrongEvidence).count()

    assert evidence["grouped_citation"] is True
    assert evidence["final_recommendation"] == "include"
    assert evidence["template_match_level"] == "strong"
    assert strong_count == 1


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


def test_template_direct_retries_once_after_truncated_schema_output(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = RecoveringTemplateDirectProvider(template_direct_payload())
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )

    assert result.status == "succeeded"
    assert len(provider.requests) == 2
    assert "RETRY AFTER INVALID OR TRUNCATED JSON" in provider.requests[1].prompt_text


def test_template_direct_retries_transient_network_failure(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = RecoveringTransientNetworkProvider(template_direct_payload())
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.time.sleep",
        lambda _seconds: None,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        _session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )

    assert result.status == "succeeded"
    assert len(provider.requests) == 2


def test_template_direct_negative_template_persists_strong_negative_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23] is less practical because it requires "
        "pre-installed tags."
    )
    provider = CapturingTemplateDirectProvider(
        template_direct_payload(
            claim_type="limitation_feedback",
            recommendation="exclude",
            quote=quote,
        )
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
            text=f"{quote}\n\nReferences\n[23] A. Author. Target Paper.",
        )
        enabled = _enable_direct_builtin(
            db,
            session_id,
            "limitation_or_negative",
        )
        enabled_id = enabled.id
        set_model_template_decision(provider, [enabled_id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong = db.query(StrongEvidence).one()

    assert evidence["matched_template_ids"] == [enabled_id]
    assert evidence["final_claim_type"] == "limitation_feedback"
    assert evidence["final_recommendation"] == "include"
    assert evidence["stance"] == "negative"
    assert strong.aspect == "limitation_feedback"
    assert strong.stance == "negative"
    assert "limitation_feedback_not_positive" not in evidence[
        "filter_reason_codes"
    ]


def test_template_direct_custom_neutral_evidence_persists_neutral_stance(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Target Paper [23] estimates 6-DoF pose from moire patterns."
    provider = CapturingTemplateDirectProvider(
        template_direct_payload(
            claim_type="custom_template_evidence",
            recommendation="review",
            quote=quote,
        )
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
            text=f"{quote}\n\nReferences\n[23] A. Author. Target Paper.",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="中性评价",
            natural_language_goal="判断引用是否既不属于正向评价也不属于负面评价",
            auto_include_in_report=True,
        )
        template_id = template.id
        set_model_template_decision(provider, [template_id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong = db.query(StrongEvidence).one()
        card = db.query(HighlightCard).one()

    assert evidence["matched_template_ids"] == [template_id]
    assert evidence["final_recommendation"] == "include"
    assert evidence["stance"] == "neutral"
    assert strong.stance == "neutral"
    assert json.loads(strong.matched_template_ids_json) == [template_id]
    assert card.stance == "neutral"
    assert card.card_type == "neutral_evaluation"
    assert card.title.startswith("中性评价：")


def test_direct_model_attitude_decision_is_not_overridden_by_keywords(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23] has showcased the power of the proposed mechanism "
        "for accurate motion sensing."
    )
    reference_entry = "[23] A. Author. Target Paper. 2022."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        positive = _enable_direct_builtin(
            db,
            session_id,
            "positive_evaluation",
        )
        neutral = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="中性评价",
            natural_language_goal="判断引用是否既不属于正向评价也不属于负面评价",
            auto_include_in_report=True,
        )
        positive_id = positive.id
        neutral_id = neutral.id
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "模型错误地把显式正向评价标为中性。",
                "evidences": [
                    {
                        "recommendation": "include",
                        "claim_type": "capability_summary",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "正文概述目标能力。",
                        "copy_ready_zh": "目标论文能力得到后续工作认可。",
                        "confidence": "high",
                        "matched_template_ids": [neutral.id],
                        "template_match_reason": "模型误判为中性能力总结。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong = db.query(StrongEvidence).one()

    assert evidence["matched_template_ids"] == [neutral_id]
    assert evidence["strong_matched_template_ids"] == [neutral_id]
    assert positive_id not in evidence["matched_template_ids"]
    assert evidence["final_claim_type"] == "capability_summary"
    assert evidence["final_recommendation"] == "include"
    assert evidence["stance"] == "neutral"
    assert json.loads(strong.matched_template_ids_json) == [neutral_id]


def test_direct_final_dedup_keeps_one_strong_evidence_per_template_claim_cluster(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    reference_entry = "[23] A. Author. Target Paper. 2022."
    quotes = [
        "The spatial frequency is modeled as f = |f1-f2| [23].",
        "The combined optical intensity is the product of two signals [23].",
        "The frequency vector is decomposed along the X and Y axes [23].",
    ]

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="\n".join(quotes) + f"\n\nReferences\n{reference_entry}",
        )
        theoretical = _enable_direct_builtin(
            db,
            session_id,
            "theoretical_foundation",
        )
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "同一理论推导被拆成三个相邻证据句。",
                "evidences": [
                    {
                        "recommendation": "include",
                        "claim_type": "theoretical_foundation",
                        "evidence_quote": quote,
                        "evidence_context": " ".join(quotes),
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "目标论文被用于同一段理论推导。",
                        "copy_ready_zh": "后续论文引用目标论文展开理论推导。",
                        "confidence": "high",
                        "matched_template_ids": [theoretical.id],
                        "template_match_reason": "同一段落中的理论建模证据。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                    for quote in quotes
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidences = json.loads(result.parsed_result_json)["evidences"]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )
        card_count = db.query(HighlightCard).count()

    assert len(evidences) == 1
    assert evidences[0]["final_claim_type"] == "theoretical_foundation"
    assert evidences[0]["final_recommendation"] == "include"
    assert evidences[0]["deduplicated_cluster_size"] == 3
    assert strong_count == 1
    assert card_count == 1


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
        set_model_template_decision(provider, [enabled_id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        persisted = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .one()
        )
        card = (
            db.query(HighlightCard)
            .filter(HighlightCard.strong_evidence_id == persisted.id)
            .one()
        )

    assert evidence["claim_type"] == "first_or_seminal_claim"
    assert evidence["recommendation"] == "include"
    assert evidence["matched_template_ids"] == [enabled_id]
    assert evidence["matched_template_types"] == ["first_or_seminal_claim"]
    assert evidence["template_satisfied"] is True
    assert persisted.queue_item_id == item_id
    assert persisted.aspect == "first_or_seminal_claim"
    assert json.loads(persisted.matched_template_ids_json) == [enabled_id]
    assert card.card_type == "first_or_seminal_claim"
    assert card.include_in_report is True


def test_template_direct_persists_only_final_include_evidence_and_card(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    include_quote = (
        "Target Paper [23] provides an effective and robust capability."
    )
    excluded_quote = "Another method [17] is used for an unrelated equation."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "一条纳入，一条排除。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "positive_evaluation",
                    "evidence_quote": include_quote,
                    "evidence_context": include_quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "正文明确正向评价目标论文。",
                    "copy_ready_zh": "后续论文明确认可目标论文的能力。",
                    "confidence": "high",
                },
                {
                    "recommendation": "exclude",
                    "claim_type": "false_positive",
                    "evidence_quote": excluded_quote,
                    "evidence_context": excluded_quote,
                    "reference_entry": "[17] B. Author. Other Paper.",
                    "why_this_judgment_zh": "引用编号不属于目标论文。",
                    "copy_ready_zh": "不纳入。",
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
                f"{include_quote}\n{excluded_quote}\n\nReferences\n"
                "[17] B. Author. Other Paper.\n"
                "[23] A. Author. Target Paper."
            ),
        )
        enabled = _enable_direct_builtin(db, session_id, "positive_evaluation")
        enabled_id = enabled.id
        set_model_template_decision(provider, [enabled_id], evidence_indexes=[0])
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        result = (
            db.query(FulltextAnalysisResult)
            .filter(FulltextAnalysisResult.queue_item_id == item_id)
            .order_by(FulltextAnalysisResult.id.desc())
            .first()
        )
        persisted = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .all()
        )
        cards = (
            db.query(HighlightCard)
            .join(
                StrongEvidence,
                HighlightCard.strong_evidence_id == StrongEvidence.id,
            )
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .all()
        )
        formal_rows = EvidenceService(db).list_scholar_evidence(
            session_id,
            filters={"latest_only": True},
        )

    assert summary["generated_strong_evidence_count"] == 1
    assert summary["persisted_strong_evidence_count"] == 1
    assert summary["strong_evidence_count"] == 1
    assert summary["generated_highlight_card_count"] == 1
    assert summary["persisted_highlight_card_count"] == 1
    assert len(persisted) == 1
    assert persisted[0].citation_text == include_quote
    assert json.loads(persisted[0].matched_template_ids_json) == [enabled_id]
    assert len(cards) == 1
    assert cards[0].narrative_zh == "后续论文明确认可目标论文的能力。"
    assert cards[0].body_markdown == "后续论文明确认可目标论文的能力。"
    assert len(formal_rows) == 1
    assert (
        formal_rows[0]["judgment_basis"]["narrative_zh"]
        == "后续论文明确认可目标论文的能力。"
    )
    assert (
        formal_rows[0]["judgment_basis"]["judgment_basis_zh"]
        == "正文明确正向评价目标论文。"
    )


def test_template_direct_persistence_failure_is_not_reported_as_success(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Target Paper [23] provides an effective capability."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "发现正向证据。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "positive_evaluation",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "正文明确认可目标能力。",
                    "copy_ready_zh": "后续论文明确认可目标能力。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        EvidenceService,
        "upsert_scholar_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated insert failure")
        ),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n[23] A. Author. Target Paper.",
        )
        enabled = _enable_direct_builtin(db, session_id, "positive_evaluation")
        set_model_template_decision(provider, [enabled.id])
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        persisted_count = db.query(StrongEvidence).count()

    assert summary["generated_strong_evidence_count"] == 1
    assert summary["persisted_strong_evidence_count"] == 0
    assert summary["strong_evidence_count"] == 0
    assert summary["strong_evidence_persistence_failed_count"] == 1
    assert summary["warnings"]
    assert persisted_count == 0


def test_template_direct_card_failure_keeps_persisted_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Target Paper [23] provides an effective capability."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "发现正向证据。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "positive_evaluation",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "正文明确认可目标能力。",
                    "copy_ready_zh": "后续论文明确认可目标能力。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        HighlightCardService,
        "generate_card_from_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated card failure")
        ),
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n[23] A. Author. Target Paper.",
        )
        enabled = _enable_direct_builtin(db, session_id, "positive_evaluation")
        set_model_template_decision(provider, [enabled.id])
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        evidence_count = db.query(StrongEvidence).count()
        card_count = db.query(HighlightCard).count()

    assert summary["persisted_strong_evidence_count"] == 1
    assert summary["persisted_highlight_card_count"] == 0
    assert summary["highlight_card_persistence_failed_count"] == 1
    assert summary["warnings"]
    assert evidence_count == 1
    assert card_count == 0


def test_template_direct_regeneration_is_idempotent(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Target Paper [23] provides an effective capability."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[23]",
            "target_reference_entry": "[23] A. Author. Target Paper.",
            "paper_level_summary_zh": "发现正向证据。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "positive_evaluation",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[23] A. Author. Target Paper.",
                    "why_this_judgment_zh": "正文明确认可目标能力。",
                    "copy_ready_zh": "后续论文明确认可目标能力。",
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
            text=f"{quote}\n\nReferences\n[23] A. Author. Target Paper.",
        )
        enabled = _enable_direct_builtin(db, session_id, "positive_evaluation")
        set_model_template_decision(provider, [enabled.id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        service = TemplateDirectPersistenceService(db)
        first = service.persist(result.id)
        second = service.persist(result.id)
        evidence_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )
        card_count = (
            db.query(HighlightCard)
            .join(
                StrongEvidence,
                HighlightCard.strong_evidence_id == StrongEvidence.id,
            )
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert first["persisted_strong_evidence_count"] == 1
    assert second["persisted_strong_evidence_count"] == 1
    assert evidence_count == 1
    assert card_count == 1


def test_equivalent_reanalysis_quote_updates_card_to_latest_evidence(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    short_quote = (
        "Target Paper [23] extracts phase profiles to improve detection efficiency."
    )
    expanded_quote = (
        "In mobile tag detection, Target Paper [23] extracts phase profiles "
        "to improve detection efficiency."
    )

    def provider_for(quote, confidence, template_id):
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": "[23] A. Author. Target Paper.",
                "paper_level_summary_zh": "发现正向证据。",
                "evidences": [
                    {
                        "recommendation": "include",
                        "claim_type": "positive_evaluation",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": "[23] A. Author. Target Paper.",
                        "why_this_judgment_zh": "正文明确说明效率提升。",
                        "copy_ready_zh": "后续论文明确肯定目标方法的效率价值。",
                        "confidence": confidence,
                    }
                ],
            }
        )
        set_model_template_decision(provider, [template_id])
        return provider

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=(
                f"{expanded_quote}\n\n"
                "References\n[23] A. Author. Target Paper."
            ),
        )
        enabled = _enable_direct_builtin(db, session_id, "positive_evaluation")

        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider_for(short_quote, "medium", enabled.id),
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        item = db.get(DeepAnalysisQueueItem, item_id)
        item.queue_status = "selected"
        db.commit()

        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider_for(expanded_quote, "high", enabled.id),
        )
        latest_result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        latest_evidence = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == latest_result.id)
            .one()
        )
        cards = db.query(HighlightCard).all()

    assert len(cards) == 1
    assert cards[0].strong_evidence_id == latest_evidence.id
    assert cards[0].evidence_quote == expanded_quote


def test_template_direct_regeneration_preview_does_not_write(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
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
                    "evidences": [
                        {
                            "final_recommendation": "include",
                            "final_claim_type": "positive_evaluation",
                            "evidence_quote": "Target Paper [23] is effective.",
                            "reference_alignment_status": "matched",
                            "matched_template_ids": [89],
                            "template_satisfied": True,
                        }
                    ]
                }
            ),
        )
        db.add(result)
        db.commit()

        preview = TemplateDirectPersistenceService(db).preview(result.id)
        evidence_count = db.query(StrongEvidence).count()
        card_count = db.query(HighlightCard).count()

    assert preview["applied"] is False
    assert preview["generated_strong_evidence_count"] == 1
    assert preview["candidate_evidences"][0]["matched_template_ids"] == [89]
    assert evidence_count == 0
    assert card_count == 0


def test_result_844_like_evidence_matches_positive_template_and_is_strong(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    target_title = (
        "Thru-the-wall Eavesdropping on Loudspeakers via RFID by Capturing "
        "Sub-mm Level Vibration"
    )
    quote = (
        "[57] demonstrates the possibility of using low-cost and easily "
        "overlooked RFID tags to effectively perform through-the-wall "
        "eavesdropping. A battery-free method called Tag-Bug is proposed."
    )
    reference_entry = (
        "[57] C. Wang et al. Thru-the-wall Eavesdropping on Loudspeakers via "
        "RFID by Capturing Sub-mm Level Vibration. 2022."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[57]",
            "target_reference_entry": reference_entry,
            "paper_level_summary_zh": "发现明确的正向能力评价。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "through_wall_eavesdropping",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": reference_entry,
                    "why_this_judgment_zh": "demonstrates 和 effectively 明确认可能力。",
                    "copy_ready_zh": "后续研究明确肯定目标方法的穿墙能力。",
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
            target_title=target_title,
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        enabled = _enable_direct_builtin(
            db,
            session_id,
            "positive_evaluation",
        )
        enabled_id = enabled.id
        set_model_template_decision(provider, [enabled_id])
        summary = ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="fulltext_template_direct",
        )
        result = (
            db.query(FulltextAnalysisResult)
            .filter(FulltextAnalysisResult.queue_item_id == item_id)
            .order_by(FulltextAnalysisResult.id.desc())
            .first()
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["matched_template_ids"] == [enabled_id]
    assert evidence["template_satisfied"] is True
    assert evidence["claim_type"] == "through_wall_eavesdropping"
    assert evidence["recommendation"] == "include"
    assert summary["strong_evidence_count"] == 1


def test_direct_model_template_include_is_not_downgraded_by_legacy_type_rules(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    target_title = (
        "MoiréPose: Ultra High Precision Camera-to-Screen Pose Estimation "
        "Based on Moiré Pattern"
    )
    quote = (
        "The second type of MSPs is generated due to the frequency difference "
        "between the displaying and imaging devices in the recapturing process [36]."
    )
    context = (
        f"{quote} According to Eq. (3), the spectral model shows a convolution "
        "operation between two Dirac comb functions."
    )
    reference_entry = (
        "[36] J. Ning et al. MoiréPose: Ultra High Precision Camera-to-Screen "
        "Pose Estimation Based on Moiré Pattern. 2022."
    )

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title=target_title,
            text=f"{context}\n\nReferences\n{reference_entry}",
        )
        template = _enable_direct_builtin(
            db,
            session_id,
            "theoretical_foundation",
        )
        template_id = template.id
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[36]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "目标论文被用于后续理论建模。",
                "evidences": [
                    {
                        "recommendation": "include",
                        "claim_type": "theoretical_foundation",
                        "evidence_quote": quote,
                        "evidence_context": context,
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "正文明确将目标论文用于频域模型推导。",
                        "copy_ready_zh": "后续论文将目标论文作为理论建模依据。",
                        "confidence": "high",
                        "matched_template_ids": [template_id],
                        "template_match_reason": "正文符合理论基础模板的自然语言目标。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert evidence["original_recommendation"] == "include"
    assert evidence["matched_template_ids"] == [template_id]
    assert evidence["strong_matched_template_ids"] == [template_id]
    assert evidence["template_match_level"] == "strong"
    assert evidence["final_recommendation"] == "include"
    assert evidence["final_claim_type"] == "theoretical_foundation"
    assert strong_count == 1


def test_direct_model_unsatisfied_template_stays_review(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23] may improve sensing accuracy, although the "
        "attribution remains unclear."
    )
    reference_entry = "[23] A. Author. Target Paper. 2022."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        template = _enable_direct_builtin(
            db,
            session_id,
            "positive_evaluation",
        )
        template_id = template.id
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "发现需复核的正向评价候选。",
                "evidences": [
                    {
                        "recommendation": "review",
                        "claim_type": "positive_evaluation",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "表述可能为正向，但作用域仍需复核。",
                        "copy_ready_zh": "该候选需完成人工核对后再纳入。",
                        "confidence": "medium",
                        "matched_template_ids": [],
                        "template_match_reason": "",
                        "template_satisfied": False,
                        "template_failure_reason": "语义相关但归因仍不确定。",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert evidence["matched_template_ids"] == []
    assert evidence["strong_matched_template_ids"] == []
    assert evidence["template_match_level"] == "none"
    assert evidence["final_recommendation"] == "review"
    assert strong_count == 0


def test_direct_model_satisfied_positive_template_is_included(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23] has showcased the power of the proposed mechanism "
        "and provides an effective solution."
    )
    reference_entry = "[23] A. Author. Target Paper. 2022."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        positive = _enable_direct_builtin(
            db,
            session_id,
            "positive_evaluation",
        )
        positive_id = positive.id
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "正文包含明确正向评价。",
                "evidences": [
                    {
                        "recommendation": "review",
                        "claim_type": "positive_evaluation",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "原文明确肯定目标方法的能力。",
                        "copy_ready_zh": "后续工作明确认可了目标方法的能力。",
                        "confidence": "high",
                        "matched_template_ids": [positive_id],
                        "template_match_reason": "明确满足正向评价模板。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert evidence["original_recommendation"] == "review"
    assert evidence["strong_matched_template_ids"] == [positive_id]
    assert evidence["final_recommendation"] == "include"
    assert evidence["final_claim_type"] == "positive_evaluation"
    assert strong_count == 1


def test_direct_model_satisfied_theory_template_is_included(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Following Target Paper [23], the spatial frequency is modeled as "
        "f = |f1-f2|."
    )
    reference_entry = "[23] A. Author. Target Paper. 2022."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        theoretical = _enable_direct_builtin(
            db,
            session_id,
            "theoretical_foundation",
        )
        theoretical_id = theoretical.id
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "目标论文被用于理论公式。",
                "evidences": [
                    {
                        "recommendation": "review",
                        "claim_type": "theoretical_foundation",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "正文基于目标论文给出公式。",
                        "copy_ready_zh": "后续工作将目标论文用于模型推导。",
                        "confidence": "high",
                        "matched_template_ids": [theoretical_id],
                        "template_match_reason": "满足理论基础模板。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["strong_matched_template_ids"] == [theoretical_id]
    assert evidence["final_recommendation"] == "include"
    assert evidence["final_claim_type"] == "theoretical_foundation"


def test_direct_model_satisfied_negative_template_is_included(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Target Paper [23] is limited by low sample rates, which are "
        "insufficient for reconstructing high-frequency signals."
    )
    reference_entry = "[23] A. Author. Target Paper. 2022."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        negative = _enable_direct_builtin(
            db,
            session_id,
            "limitation_or_negative",
        )
        negative_id = negative.id
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": reference_entry,
                "paper_level_summary_zh": "正文明确描述目标方法的局限。",
                "evidences": [
                    {
                        "recommendation": "review",
                        "claim_type": "limitation_feedback",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": reference_entry,
                        "why_this_judgment_zh": "低采样率构成明确局限。",
                        "copy_ready_zh": "后续工作指出了目标方法的采样率限制。",
                        "confidence": "high",
                        "matched_template_ids": [negative_id],
                        "template_match_reason": "满足负面/局限评价模板。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["strong_matched_template_ids"] == [negative_id]
    assert evidence["final_recommendation"] == "include"
    assert evidence["final_claim_type"] == "limitation_feedback"
    assert evidence["stance"] == "negative"


def test_direct_model_template_include_cannot_bypass_reference_alignment(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    target_entry = "[23] A. Author. Target Paper. 2022."
    other_entry = "[24] B. Author. Other Paper. 2023."
    quote = "Other Paper [24] provides an effective and accurate method."

    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n{target_entry}\n{other_entry}",
        )
        template = _enable_direct_builtin(
            db,
            session_id,
            "positive_evaluation",
        )
        provider = CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[23]",
                "target_reference_entry": target_entry,
                "paper_level_summary_zh": "模型错误地选择了其他论文。",
                "evidences": [
                    {
                        "recommendation": "include",
                        "claim_type": "positive_evaluation",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": other_entry,
                        "why_this_judgment_zh": "该句实际描述其他论文。",
                        "copy_ready_zh": "不应纳入。",
                        "confidence": "high",
                        "matched_template_ids": [template.id],
                        "template_match_reason": "模型声称满足正向评价。",
                        "template_satisfied": True,
                        "template_failure_reason": "",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            "app.services.scholar_fulltext_service.get_llm_provider",
            lambda: provider,
        )

        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert evidence["reference_alignment_status"] == "mismatch"
    assert evidence["final_recommendation"] == "exclude"
    assert evidence["final_claim_type"] == "false_positive"
    assert strong_count == 0


def test_missing_model_template_decision_stays_review_without_backend_inference(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    target_title = "Probing into the Physical Layer: Moving Tag Detection"
    quote = (
        "Wang et al. [16] extract the phase profile and backscatter link "
        "frequency to distinguish moving tags by location."
    )
    reference_entry = (
        "[16] C. Wang et al. Probing into the Physical Layer: "
        "Moving Tag Detection. 2020."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[16]",
            "target_reference_entry": reference_entry,
            "paper_level_summary_zh": "正文概述目标论文的方法。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": reference_entry,
                    "why_this_judgment_zh": "属于目标方法的具体概述。",
                    "copy_ready_zh": "后续论文概述了目标论文的移动标签检测方法。",
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
            target_title=target_title,
            text=f"{quote}\n\nReferences\n{reference_entry}",
        )
        _enable_direct_builtin(
            db,
            session_id,
            "positive_evaluation",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert evidence["matched_template_ids"] == []
    assert evidence["template_satisfied"] is False
    assert evidence["template_match_level"] == "none"
    assert evidence["template_decision_source"] == "llm_missing_template_decision"
    assert "model did not return" in evidence["template_failure_reason"]
    assert evidence["final_recommendation"] == "review"
    assert strong_count == 0


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
        set_model_template_decision(
            provider,
            [first_id],
            evidence_indexes=[0],
            reason="The first-work statement directly targets the cited paper.",
        )
        set_model_template_decision(
            provider,
            [positive_id],
            evidence_indexes=[1],
            reason="The positive assessment directly targets the cited paper.",
        )
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


def test_template_direct_candidate_schema_preserves_high_recall_fact_fields():
    evidence = TemplateDirectEvidence.model_validate(
        {
            "recommendation": "exclude",
            "claim_type": "capability_summary",
            "evidence_quote": "Wang et al. [26] proposed a detection mechanism.",
            "evidence_context": "The related paragraph provides more detail.",
            "why_this_judgment_zh": "正文概述目标方法。",
            "copy_ready_zh": "候选证据，需确定性校验。",
            "confidence": "medium",
            "surrounding_context": "Full surrounding paragraph.",
            "citation_markers": ["[26]"],
            "claimed_target_marker": "[26]",
            "attribution_scope": "single_target",
            "grouped_or_single": "single",
            "semantic_relation": "method_summary",
            "model_confidence": 0.72,
            "candidate_reason": "Describes the target method.",
        }
    )

    payload = evidence.model_dump()
    assert payload["citation_markers"] == ["[26]"]
    assert payload["candidate_reason"] == "Describes the target method."
    assert payload["model_confidence"] == 0.72


def test_aligned_capability_summary_without_template_becomes_review_candidate(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Wang et al. [26] proposed a moving label detection mechanism that "
        "uses collision signals to improve time efficiency."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[26]",
            "target_reference_entry": "[26] G. Hopper. Target Paper.",
            "paper_level_summary_zh": "发现方法能力概述。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "capability_summary",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[26] G. Hopper. Target Paper.",
                    "why_this_judgment_zh": "正文具体概述目标方法。",
                    "copy_ready_zh": "该条作为候选复核。",
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
            text=f"{quote}\n\nReferences\n[26] G. Hopper. Target Paper.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        payload = json.loads(result.parsed_result_json)
        evidence = payload["evidences"][0]
        counts = ScholarFulltextService(db)._direct_evidence_counts(payload)

    assert evidence["final_recommendation"] == "review"
    assert evidence["template_satisfied"] is False
    assert "candidate_requires_matching_template" in evidence["filter_reason_codes"]
    assert counts["extracted_candidate_count"] == 1
    assert counts["aligned_candidate_count"] == 1
    assert counts["template_eligible_candidate_count"] == 1
    assert counts["template_matched_candidate_count"] == 0
    assert counts["final_review_count"] == 1


def test_enabled_method_capability_template_can_promote_aligned_candidate(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Wang et al. [26] proposed a moving label detection mechanism that "
        "uses collision signals to improve time efficiency."
    )
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[26]",
            "target_reference_entry": "[26] G. Hopper. Target Paper.",
            "paper_level_summary_zh": "发现方法能力概述。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "capability_summary",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[26] G. Hopper. Target Paper.",
                    "why_this_judgment_zh": "正文具体概述目标方法。",
                    "copy_ready_zh": "后续论文具体概述了目标论文提出的机制。",
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
            text=f"{quote}\n\nReferences\n[26] G. Hopper. Target Paper.",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="方法或能力概述",
            natural_language_goal="识别正文对目标论文方法、机制或能力的具体概述。",
            template_type="method_or_capability_summary",
            require_target_marker=True,
            allow_grouped_citation=False,
        )
        template_id = template.id
        set_model_template_decision(provider, [template_id])
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .all()
        )

    assert evidence["matched_template_ids"] == [template_id]
    assert evidence["template_satisfied"] is True
    assert evidence["final_recommendation"] == "include"
    assert len(strong) == 1


def test_model_can_reject_ambiguous_grouped_method_candidate(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Prior systems [25], [26] proposed several sensing mechanisms."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[26]",
            "target_reference_entry": "[26] G. Hopper. Target Paper.",
            "paper_level_summary_zh": "成组引用。",
            "evidences": [
                {
                    "recommendation": "exclude",
                    "claim_type": "capability_summary",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[26] G. Hopper. Target Paper.",
                    "why_this_judgment_zh": "无法单独归因。",
                    "copy_ready_zh": "不纳入。",
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
            text=(
                f"{quote}\n\nReferences\n"
                "[25] A. Author. Other Work.\n"
                "[26] G. Hopper. Target Paper."
            ),
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="方法或能力概述",
            natural_language_goal="识别目标论文的方法或能力概述。",
            template_type="method_or_capability_summary",
            require_target_marker=True,
            allow_grouped_citation=False,
        )
        set_model_template_decision(
            provider,
            [template.id],
            satisfied=False,
            reason="The grouped statement does not attribute the method to the target alone.",
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        strong_count = (
            db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )

    assert evidence["final_recommendation"] != "include"
    assert evidence["template_satisfied"] is False
    assert evidence["template_match_level"] == "none"
    assert evidence["template_strongly_satisfied"] is False
    assert strong_count == 0


def test_evidence_page_shows_review_candidate_layer_and_missing_dimension(
    client,
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = (
        "Wang et al. [26] proposed a moving label detection mechanism that "
        "uses collision signals."
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: CapturingTemplateDirectProvider(
            {
                "target_reference_marker": "[26]",
                "target_reference_entry": "[26] G. Hopper. Target Paper.",
                "paper_level_summary_zh": "方法概述候选。",
                "evidences": [
                    {
                        "recommendation": "exclude",
                        "claim_type": "capability_summary",
                        "evidence_quote": quote,
                        "evidence_context": quote,
                        "reference_entry": "[26] G. Hopper. Target Paper.",
                        "why_this_judgment_zh": "正文具体概述目标方法。",
                        "copy_ready_zh": "候选复核。",
                        "confidence": "medium",
                    }
                ],
            }
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=f"{quote}\n\nReferences\n[26] G. Hopper. Target Paper.",
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )

    response = client.get(f"/scholar-sessions/{session_id}/evidence")

    assert response.status_code == 200
    assert "候选证据层" in response.text
    assert "正向强证据" in response.text
    assert "中性强证据" in response.text
    assert "负面强证据" in response.text
    assert "正文是方法或能力概述，但未满足当前评价模板的明确条件" in response.text
    assert quote in response.text


def test_grouped_candidate_missing_dimension_is_decided_by_model(
    db_session_factory,
):
    with Session(db_session_factory.kw["bind"]) as db:
        row = ScholarFulltextService(db)._direct_candidate_view_row(
            {
                "final_recommendation": "review",
                "final_claim_type": "positive_evaluation",
                "evidence_quote": "Target Paper [22], [23] is effective.",
                "reference_alignment_status": "matched",
                "grouped_citation": True,
                "matched_template_ids": [1],
                "template_satisfied": True,
            }
        )

    assert row["missing_dimension"] == ""
    assert "成组引用无法单独归因" not in row["missing_dimension"]


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
    assert evidence["original_claim_type"] == "ordinary_reference"
    assert evidence["final_claim_type"] == "ordinary_reference"
    assert evidence["matched_template_ids"] == []
    assert evidence["filter_reason_codes"] == evidence["failure_reason_codes"]
    assert "ordinary_reference" in evidence["failure_reason_codes"]
    assert "grouped_citation_not_allowed" not in evidence["failure_reason_codes"]
    assert summary["filtered_findings_count"] == 1
    assert summary["filter_reason_distribution"]["ordinary_reference"] == 1
    assert (
        diagnostics["filter_reason_distribution"].get(
            "grouped_citation_not_allowed",
            0,
        )
        == 0
    )
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
