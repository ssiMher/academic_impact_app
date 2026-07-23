import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.candidate_spans import find_candidate_spans
from app.analysis.citation_anchor import (
    build_target_citation_anchor,
    citation_text_has_target_anchor,
    extract_alias_contexts,
    extract_target_reference_contexts,
    find_target_reference_anchor,
)
from app.analysis.evidence_highlighting import build_highlight_keywords
from app.analysis.evidence_scoring import score_finding
from app.analysis.llm_parser import parse_llm_response
from app.db.base import Base
from app.models import (
    AnalysisTask,
    CitingPaper,
    FulltextAnalysisResult,
    PaperAnalysisSession,
    PdfAsset,
    Publication,
    StrongEvidence,
)
from app.schemas.llm import CitationAnalysisResponse, LlmFinding
from app.tasks.handlers.analyze_citation import handle_analyze_citation
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from app.repositories.task_repo import TaskRepository
from app.services.task_service import TaskService


def test_candidate_span定位_around_target_anchor():
    anchor = build_target_citation_anchor("Evidence-Aware Citation Analysis")
    text = (
        "Unrelated introduction. "
        "Evidence-Aware Citation Analysis is treated as a method foundation "
        "for evaluating third-party citation evidence. "
        "Another unrelated sentence."
    )

    spans = find_candidate_spans(text, anchor)

    assert len(spans) == 1
    assert "method foundation" in spans[0].text
    assert spans[0].start < spans[0].end


def test_fake_llm_output_parse_success():
    payload = {
        "findings": [
            {
                "evidence_type": "method_foundation",
                "stance": "positive",
                "mention_type": "strong",
                "citation_text": "The target paper is a method foundation.",
                "reasoning": "It describes a concrete methodological dependency.",
                "keywords": ["method foundation", "target paper"],
            }
        ]
    }

    result = parse_llm_response(json.dumps(payload))

    assert result.findings[0].evidence_type == "method_foundation"
    assert result.findings[0].stance == "positive"


def test_fake_llm_output_parse_rejects_unknown_evidence_type():
    payload = {
        "findings": [
            {
                "evidence_type": "made_up_type",
                "stance": "positive",
                "mention_type": "strong",
                "citation_text": "Some text",
                "reasoning": "Invalid label.",
                "keywords": [],
            }
        ]
    }

    with pytest.raises(ValidationError):
        parse_llm_response(json.dumps(payload))


def test_llm_parser_strips_think_tags():
    raw = (
        "<think>I should reason privately.</think>"
        '{"findings": []}'
    )

    result = parse_llm_response(raw)

    assert result.findings == []


def test_llm_parser_extracts_fenced_json():
    raw = '```json\n{"findings": []}\n```'

    result = parse_llm_response(raw)

    assert result.findings == []


def test_llm_parser_extracts_json_after_natural_language():
    raw = 'Here is the result:\n{"findings": []}'

    result = parse_llm_response(raw)

    assert result.findings == []


def test_llm_parser_normalizes_evidence_key_to_findings():
    raw = json.dumps(
        {
            "evidence": [
                {
                    "evidence_type": "method_foundation",
                    "stance": "positive",
                    "mention_type": "strong",
                    "citation_text": "The target paper is a method foundation.",
                    "reasoning": "Specific support.",
                    "keywords": ["method foundation"],
                }
            ]
        }
    )

    result = parse_llm_response(raw)

    assert len(result.findings) == 1
    assert result.findings[0].evidence_type == "method_foundation"


def test_llm_parser_normalizes_finding_field_aliases():
    raw = json.dumps(
        {
            "findings": [
                {
                    "aspect": "method_foundation",
                    "stance": "positive",
                    "mention_type": "explicit_target",
                    "quote": "The target paper is a method foundation.",
                    "reason": "The quote names a concrete method dependency.",
                    "highlight_keywords": ["method foundation"],
                }
            ]
        }
    )

    result = parse_llm_response(raw)

    finding = result.findings[0]
    assert finding.evidence_type == "method_foundation"
    assert finding.citation_text == "The target paper is a method foundation."
    assert finding.reasoning == "The quote names a concrete method dependency."
    assert finding.keywords == ["method foundation"]


def test_llm_no_evidence_text_becomes_empty_findings():
    result = parse_llm_response("No evidence found")

    assert result.findings == []


def test_grouped_citation_is_not_scored_as_strong_evidence():
    finding = LlmFinding(
        evidence_type="important_author_citation",
        stance="neutral",
        mention_type="grouped_citation",
        citation_text="Several systems are cited together [1, 2, 3].",
        reasoning="The citation is grouped and does not make a specific claim.",
        keywords=["several systems"],
    )

    score = score_finding(finding)

    assert score.score < 0.6
    assert score.evidence_strength == "weak"


def test_find_target_reference_anchor_by_title():
    text = (
        "Body text.\n"
        "References\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
    )

    anchor = find_target_reference_anchor(
        text,
        "MoiréPose: ultra high precision camera-to-screen pose estimation based on Moiré pattern",
    )

    assert anchor is not None
    assert anchor.reference_marker == "15"
    assert anchor.match_method in {"title_exact", "title_overlap"}


def test_find_target_reference_anchor_by_doi():
    text = (
        "Body text.\n"
        "References\n"
        "[15] J. Ning et al., Some wrapped title text. doi:10.1145/3495243.3560526\n"
    )

    anchor = find_target_reference_anchor(
        text,
        "Different visible title",
        cited_doi="10.1145/3495243.3560526",
    )

    assert anchor is not None
    assert anchor.reference_marker == "15"
    assert anchor.match_method == "doi_exact"


def test_reference_anchor_handles_moire_variants():
    text = (
        "Body text.\n"
        "References\n"
        "[15] J. Ning et al., MoirePose: ultra high precision camera to screen pose estimation based on Moire pattern.\n"
    )

    anchor = find_target_reference_anchor(
        text,
        "MoiréPose: ultra high precision camera-to-screen pose estimation based on Moir´e pattern",
    )

    assert anchor is not None
    assert anchor.reference_marker_text == "[15]"


def test_citation_text_has_exact_marker():
    assert citation_text_has_target_anchor("The method in [15] is effective.", "15") is True


def test_citation_text_has_grouped_marker():
    assert citation_text_has_target_anchor("Methods [15], [16], [17] are compared.", "15") is True
    assert citation_text_has_target_anchor("Methods [14, 15, 16] are compared.", "15") is True


def test_citation_text_has_range_marker():
    assert citation_text_has_target_anchor("Methods [14]-[17] are compared.", "15") is True
    assert citation_text_has_target_anchor("Methods [14–17] are compared.", "15") is True


def test_extract_target_reference_context_exact_marker():
    text = (
        "1 Method\nThe model in [36] defines the spectral peak behavior.\n\n"
        "References\n[36] J. Ning et al., MoirePose.\n"
    )
    contexts = extract_target_reference_contexts(text, "36", window_chars=200)

    assert contexts
    assert contexts[0].context_type in {"exact_marker", "formula_nearby"}
    assert "[36]" in contexts[0].context_text


def test_extract_target_reference_context_grouped_marker():
    text = (
        "2 Analysis\nMethods [35], [36], [37] are compared in this section.\n"
        "References\n[36] J. Ning et al., MoirePose.\n"
    )
    contexts = extract_target_reference_contexts(text, "36", window_chars=200)

    assert contexts
    assert contexts[0].context_type == "grouped_marker"


def test_extract_target_reference_context_range_marker():
    text = (
        "3 Theory\nThe family [34]-[36] is used in the convolution model.\n"
        "References\n[36] J. Ning et al., MoirePose.\n"
    )
    contexts = extract_target_reference_contexts(text, "36", window_chars=200)

    assert contexts
    assert contexts[0].context_type == "formula_nearby"
    assert contexts[0].contains_formula is True


def test_reference_context_excludes_references_section():
    text = (
        "Body text without marker.\n"
        "References\n"
        "[36] J. Ning et al., MoirePose.\n"
    )
    contexts = extract_target_reference_contexts(text, "36", window_chars=200)

    assert contexts == []


def test_extract_alias_context_for_no_marker_mentions():
    text = (
        "4 Discussion\nNing et al. 2022 provide the theoretical basis for this camera-to-screen pose estimation model.\n"
        "References\n[36] J. Ning et al., MoirePose.\n"
    )
    contexts = extract_alias_contexts(text, ["Ning et al. 2022", "MoiréPose"], window_chars=220)

    assert contexts
    assert contexts[0].context_type == "alias_context"


def test_keyword_highlighting_uses_citation_text_and_keywords():
    keywords = build_highlight_keywords(
        citation_text="The target paper is a method foundation for this system.",
        keywords=["method foundation", "target paper", "missing"],
    )

    assert keywords == ["method foundation", "target paper"]


def test_analyze_citation_handler_generates_result_and_strong_evidence(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        text_path = tmp_path / "citing.txt"
        citation_text = (
            "Evidence-Aware Citation Analysis is a method foundation for our "
            "third-party citation evidence workflow."
        )
        text_path.write_text(citation_text, encoding="utf-8")

        session = PaperAnalysisSession(
            query_text="Evidence-Aware Citation Analysis",
            query_kind="title",
            status="created",
        )
        publication = Publication(title="Citing publication")
        pdf_asset = PdfAsset(
            storage_path=str(tmp_path / "paper.pdf"),
            original_filename="paper.pdf",
            extract_status="succeeded",
            extracted_text_path=str(text_path),
        )
        db.add_all([session, publication, pdf_asset])
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            analysis_status="discovered",
            pdf_asset_id=pdf_asset.id,
        )
        db.add(citing_paper)
        db.flush()
        task = AnalysisTask(
            session_kind="citing_paper",
            session_id=citing_paper.id,
            task_type="analyze_citation",
            status="running",
        )
        db.add(task)
        db.commit()

        handle_analyze_citation(db, task)

        result = db.query(FulltextAnalysisResult).one()
        evidences = db.query(StrongEvidence).all()
    finally:
        db.close()

    assert result.status == "succeeded"
    assert result.analysis_scope == "citation_context"
    assert len(evidences) == 1
    assert evidences[0].mention_type == "strong"
    assert evidences[0].citation_text == citation_text
    assert evidences[0].score >= 0.6
    assert "method foundation" in evidences[0].highlight_keywords_json


def test_invalid_fake_llm_json_marks_task_failed(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        text_path = tmp_path / "citing.txt"
        text_path.write_text(
            "Evidence-Aware Citation Analysis is a method foundation.",
            encoding="utf-8",
        )
        session = PaperAnalysisSession(
            query_text="Evidence-Aware Citation Analysis",
            query_kind="title",
            status="created",
        )
        publication = Publication(title="Citing publication")
        pdf_asset = PdfAsset(
            storage_path=str(tmp_path / "paper.pdf"),
            original_filename="paper.pdf",
            extract_status="succeeded",
            extracted_text_path=str(text_path),
        )
        db.add_all([session, publication, pdf_asset])
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            analysis_status="discovered",
            pdf_asset_id=pdf_asset.id,
        )
        db.add(citing_paper)
        db.commit()

        from app.providers.fake import FakeLlmProvider

        monkeypatch.setattr(
            FakeLlmProvider,
            "analyze_citation",
            lambda self, request: parse_llm_response("{invalid-json"),
        )
        TaskService(TaskRepository(db)).enqueue(
            session_kind="citing_paper",
            session_id=citing_paper.id,
            task_type="analyze_citation",
        )
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
    finally:
        db.close()

    assert task.status == "failed"
    assert task.error_message
    assert "Expecting property name" in task.error_message


def test_findings_without_citation_text_do_not_generate_strong_evidence(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        text_path = tmp_path / "citing.txt"
        text_path.write_text(
            "Evidence-Aware Citation Analysis is a method foundation.",
            encoding="utf-8",
        )
        session = PaperAnalysisSession(
            query_text="Evidence-Aware Citation Analysis",
            query_kind="title",
            status="created",
        )
        publication = Publication(title="Citing publication")
        pdf_asset = PdfAsset(
            storage_path=str(tmp_path / "paper.pdf"),
            original_filename="paper.pdf",
            extract_status="succeeded",
            extracted_text_path=str(text_path),
        )
        db.add_all([session, publication, pdf_asset])
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            analysis_status="discovered",
            pdf_asset_id=pdf_asset.id,
        )
        db.add(citing_paper)
        db.flush()
        task = AnalysisTask(
            session_kind="citing_paper",
            session_id=citing_paper.id,
            task_type="analyze_citation",
            status="running",
        )
        db.add(task)
        db.commit()

        from app.providers.fake import FakeLlmProvider

        monkeypatch.setattr(
            FakeLlmProvider,
            "analyze_citation",
            lambda self, request: CitationAnalysisResponse(
                findings=[
                    LlmFinding(
                        evidence_type="method_foundation",
                        stance="positive",
                        mention_type="strong",
                        citation_text=None,
                        reasoning="No citation text.",
                        keywords=["method foundation"],
                    )
                ]
            ),
        )
        handle_analyze_citation(db, task)
        evidence_count = db.query(StrongEvidence).count()
        result_count = db.query(FulltextAnalysisResult).count()
    finally:
        db.close()

    assert result_count == 1
    assert evidence_count == 0


def test_missing_extracted_text_marks_task_failed_without_evidence(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        session = PaperAnalysisSession(
            query_text="Evidence-Aware Citation Analysis",
            query_kind="title",
            status="created",
        )
        publication = Publication(title="Citing publication")
        pdf_asset = PdfAsset(
            storage_path=str(tmp_path / "paper.pdf"),
            original_filename="paper.pdf",
            extract_status="succeeded",
            extracted_text_path=None,
        )
        db.add_all([session, publication, pdf_asset])
        db.flush()
        citing_paper = CitingPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            analysis_status="discovered",
            pdf_asset_id=pdf_asset.id,
        )
        db.add(citing_paper)
        db.commit()

        TaskService(TaskRepository(db)).enqueue(
            session_kind="citing_paper",
            session_id=citing_paper.id,
            task_type="analyze_citation",
        )
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        evidence_count = db.query(StrongEvidence).count()
    finally:
        db.close()

    assert task.status == "failed"
    assert "succeeded extracted text" in task.error_message
    assert evidence_count == 0
