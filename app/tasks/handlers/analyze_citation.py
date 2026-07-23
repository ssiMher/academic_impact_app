"""Analyze a citing paper's extracted text into structured evidence."""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.analysis.candidate_spans import find_candidate_spans
from app.analysis.citation_anchor import build_target_citation_anchor
from app.analysis.evidence_highlighting import build_highlight_keywords
from app.analysis.evidence_scoring import score_finding
from app.analysis.prompt_builder import build_citation_analysis_prompt
from app.models import (
    AnalysisTask,
    CitingPaper,
    FulltextAnalysisResult,
    PaperAnalysisSession,
    PdfAsset,
    StrongEvidence,
)
from app.providers.llm_provider import get_llm_provider
from app.schemas.llm import LlmCitationAnalysisRequest


MIN_STRONG_EVIDENCE_SCORE = 0.6


def handle_analyze_citation(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != "citing_paper":
        raise ValueError("analyze_citation only supports citing_paper tasks")

    citing_paper = db.get(CitingPaper, task.session_id)
    if citing_paper is None:
        raise ValueError(f"CitingPaper {task.session_id} was not found")

    pdf_asset = db.get(PdfAsset, citing_paper.pdf_asset_id) if citing_paper.pdf_asset_id else None
    if pdf_asset is None or pdf_asset.extract_status != "succeeded" or not pdf_asset.extracted_text_path:
        raise ValueError("CitingPaper does not have succeeded extracted text")

    paper_session = db.get(PaperAnalysisSession, citing_paper.paper_session_id)
    if paper_session is None:
        raise ValueError(f"PaperAnalysisSession {citing_paper.paper_session_id} was not found")

    extracted_text = Path(pdf_asset.extracted_text_path).read_text(encoding="utf-8")
    anchor = build_target_citation_anchor(paper_session.query_text)
    candidate_spans = find_candidate_spans(extracted_text, anchor)
    build_citation_analysis_prompt(anchor=anchor, candidate_spans=candidate_spans)
    parsed_result = get_llm_provider().analyze_citation(
        LlmCitationAnalysisRequest(
            target_title=anchor.title,
            candidate_spans=[span.text for span in candidate_spans],
        )
    )

    fulltext_result = FulltextAnalysisResult(
        citing_paper_id=citing_paper.id,
        analysis_scope="citation_context",
        status="succeeded",
        parsed_result_json=parsed_result.model_dump_json(),
    )
    db.add(fulltext_result)
    db.flush()

    for finding in parsed_result.findings:
        if not finding.citation_text:
            continue
        score = score_finding(finding)
        if score.score < MIN_STRONG_EVIDENCE_SCORE:
            continue
        highlight_keywords = build_highlight_keywords(
            citation_text=finding.citation_text,
            keywords=finding.keywords,
        )
        db.add(
            StrongEvidence(
                fulltext_result_id=fulltext_result.id,
                aspect=finding.evidence_type,
                stance=finding.stance,
                mention_type=finding.mention_type,
                citation_text=finding.citation_text,
                highlight_keywords_json=json.dumps(highlight_keywords),
                score=score.score,
                evidence_strength=score.evidence_strength,
            )
        )

    citing_paper.analysis_status = "analyzed"
    task.progress_total = len(parsed_result.findings)
    task.progress_current = len(parsed_result.findings)
    task.stage = "analyzing_citation"
    task.stage_message = "Citation analysis completed."
    db.commit()
