"""Service helpers for scholar evidence persistence and review."""

import json
from typing import Dict, Iterable, List, Optional

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.evidence_highlighting import build_highlighted_text_html
from app.analysis.card_builder import card_type_for_evidence, generate_impact_narrative
from app.analysis.target_anchor_validation import validate_citation_target_anchor
from app.db.session import get_db
from app.models import AnalysisTemplate, CitationAuthorAnnotation, DeepAnalysisQueueItem, FulltextAnalysisResult, PdfAsset, StrongEvidence
from app.services.context_service import build_context_preview
from app.services.template_service import TemplateService


class EvidenceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_scholar_evidence(
        self,
        *,
        fulltext_result_id: int,
        scholar_session_id: int,
        queue_item_id: int,
        citation_edge_id: int,
        aspect: str,
        stance: str,
        mention_type: str,
        citation_text: str,
        highlight_keywords: Iterable[str],
        evidence_reason: str,
        evidence_strength: str,
        score: float,
        span_index: Optional[int],
        is_self_citation: bool,
        third_party_status: str,
        anchor_status: str = "matched",
        template_result: Optional[dict] = None,
    ) -> StrongEvidence:
        existing = self._find_duplicate(
            queue_item_id=queue_item_id,
            citation_edge_id=citation_edge_id,
            aspect=aspect,
            stance=stance,
            mention_type=mention_type,
            citation_text=citation_text,
        )
        keywords = list(highlight_keywords)
        values = {
            "fulltext_result_id": fulltext_result_id,
            "scholar_session_id": scholar_session_id,
            "queue_item_id": queue_item_id,
            "citation_edge_id": citation_edge_id,
            "aspect": aspect,
            "stance": stance,
            "mention_type": mention_type,
            "citation_text": citation_text,
            "highlighted_text_html": build_highlighted_text_html(
                citation_text=citation_text,
                keywords=keywords,
            ),
            "highlight_keywords_json": json.dumps(keywords),
            "evidence_reason": evidence_reason,
            "evidence_strength": evidence_strength,
            "score": score,
            "span_index": span_index,
            "anchor_status": anchor_status,
            "is_self_citation": is_self_citation,
            "third_party_status": third_party_status,
        }
        if template_result is not None:
            values.update(
                {
                    "matched_template_ids_json": json.dumps(
                        template_result.get("matched_template_ids", []),
                        ensure_ascii=False,
                    ),
                    "template_match_reason": template_result.get("template_match_reason", ""),
                    "template_satisfied": bool(template_result.get("template_satisfied", False)),
                    "template_failure_reason": template_result.get("template_failure_reason", ""),
                }
            )
        if existing is None:
            evidence = StrongEvidence(**values)
            self.db.add(evidence)
            self.db.flush()
            return evidence

        for key, value in values.items():
            if key in {"review_status", "user_note"}:
                continue
            setattr(existing, key, value)
        return existing

    def list_scholar_evidence(
        self,
        session_id: int,
        *,
        filters: Optional[Dict[str, str]] = None,
        pagination: Optional[dict] = None,
    ) -> List[dict]:
        view = (filters or {}).get("view", "all")
        latest_only = bool((filters or {}).get("latest_only", False))
        latest_result_by_item = {}
        if latest_only:
            latest_result_by_item = {
                int(queue_item_id): int(result_id)
                for queue_item_id, result_id in self.db.execute(
                    select(
                        FulltextAnalysisResult.queue_item_id,
                        func.max(FulltextAnalysisResult.id),
                    )
                    .where(
                        FulltextAnalysisResult.scholar_session_id == session_id,
                        FulltextAnalysisResult.analysis_scope
                        == "fulltext_template_direct",
                        FulltextAnalysisResult.status == "succeeded",
                    )
                    .group_by(FulltextAnalysisResult.queue_item_id)
                ).all()
                if queue_item_id is not None and result_id is not None
            }
        statement = (
            select(StrongEvidence, DeepAnalysisQueueItem)
            .join(
                DeepAnalysisQueueItem,
                StrongEvidence.queue_item_id == DeepAnalysisQueueItem.id,
            )
            .where(StrongEvidence.scholar_session_id == session_id)
        )
        rows = []
        changed = False
        for evidence, item in self.db.execute(statement).all():
            latest_result_id = latest_result_by_item.get(item.id)
            if latest_result_id is not None and evidence.fulltext_result_id != latest_result_id:
                continue
            if not self._matches_view(evidence, item, view):
                continue
            context_preview = self._context_preview(evidence)
            anchor_validation = self._anchor_validation(evidence, item)
            if (
                not anchor_validation.is_valid
                and anchor_validation.anchor_validation_status != "unknown"
                and evidence.review_status not in {"false_positive", "rejected"}
            ):
                evidence.review_status = "false_positive"
                evidence.anchor_status = anchor_validation.anchor_validation_status
                evidence.evidence_strength = "none"
                evidence.score = 0
                evidence.user_note = f"{evidence.user_note or ''} anchor_validation: {anchor_validation.anchor_validation_reason}".strip()
                changed = True
            card_type = card_type_for_evidence(evidence)
            narrative = generate_impact_narrative(
                evidence=evidence,
                item=item,
                card_type=card_type,
                context_preview=context_preview,
                notable_author=None,
            )
            direct_evidence = self._template_direct_evidence(evidence)
            if direct_evidence:
                model_reason = str(
                    direct_evidence.get("why_this_judgment_zh") or ""
                ).strip()
                model_evaluation = str(
                    direct_evidence.get("copy_ready_zh") or ""
                ).strip()
                if model_reason:
                    narrative["why_this_judgment"] = model_reason
                    narrative["judgment_basis_zh"] = model_reason
                if model_evaluation:
                    narrative["narrative_zh"] = model_evaluation
                    narrative["evidence_claim_zh"] = model_evaluation
                    narrative["copy_ready_statement"] = model_evaluation
                    narrative["copy_ready_statement_zh"] = model_evaluation
            narrative.update(
                {
                    "matched_template_ids": self._load_json_list(evidence.matched_template_ids_json),
                    "matched_template_names": self._template_names_for_evidence(evidence),
                    "template_match_reason": evidence.template_match_reason or "",
                    "template_satisfied": evidence.template_satisfied,
                    "template_failure_reason": evidence.template_failure_reason or "",
                    "target_reference_marker": anchor_validation.target_reference_marker,
                    "citation_text_contains_target_marker": anchor_validation.citation_text_contains_target_marker,
                    "citation_text_contains_other_marker": anchor_validation.citation_text_contains_other_marker,
                    "anchor_validation_status": anchor_validation.anchor_validation_status,
                    "anchor_validation_reason": anchor_validation.anchor_validation_reason,
                }
            )
            rows.append(
                {
                    "evidence": evidence,
                    "item": item,
                    "template_matches": TemplateService(self.db).list_matches_for_evidence(evidence.id),
                    "notable_annotations": self._list_notable_annotations(item.id),
                    "context_preview": context_preview,
                    "judgment_basis": narrative,
                }
            )
        if changed:
            self.db.commit()
        return sorted(
            rows,
            key=lambda row: (
                1 if row["evidence"].review_status == "important" else 0,
                row["evidence"].score or 0,
                -row["evidence"].id,
            ),
            reverse=True,
        )

    def _template_direct_evidence(self, evidence: StrongEvidence) -> dict:
        result = self.db.get(FulltextAnalysisResult, evidence.fulltext_result_id)
        if result is None or result.analysis_scope != "fulltext_template_direct":
            return {}
        payload = self._load_json(result.parsed_result_json)
        evidences = payload.get("evidences")
        if not isinstance(evidences, list):
            return {}
        index = evidence.span_index
        if not isinstance(index, int) or not 0 <= index < len(evidences):
            return {}
        direct_evidence = evidences[index]
        return direct_evidence if isinstance(direct_evidence, dict) else {}

    def update_evidence_review(
        self,
        evidence_id: int,
        review_status: str,
        user_note: str,
        corrected_label: Optional[str] = None,
    ) -> StrongEvidence:
        evidence = self.db.get(StrongEvidence, evidence_id)
        if evidence is None:
            raise ValueError(f"StrongEvidence {evidence_id} was not found")
        evidence.review_status = review_status
        evidence.user_note = user_note
        evidence.corrected_label = corrected_label
        self.db.commit()
        self.db.refresh(evidence)
        return evidence

    def list_report_candidate_evidence(self, session_id: int) -> List[StrongEvidence]:
        statement = select(StrongEvidence).where(
            StrongEvidence.scholar_session_id == session_id,
            StrongEvidence.review_status.not_in({"rejected", "false_positive"}),
        )
        evidences = list(self.db.scalars(statement))
        return sorted(
            evidences,
            key=lambda evidence: (
                1 if evidence.review_status == "important" else 0,
                evidence.score or 0,
                -evidence.id,
            ),
            reverse=True,
        )

    def quality_summary(self, session_id: int) -> Dict[str, int]:
        statement = select(StrongEvidence).where(
            StrongEvidence.scholar_session_id == session_id
        )
        evidences = list(self.db.scalars(statement))
        return {
            "total_evidence_count": len(evidences),
            "accepted_count": self._count_review(evidences, "accepted"),
            "rejected_count": self._count_review(evidences, "rejected"),
            "important_count": self._count_review(evidences, "important"),
            "false_positive_count": self._count_review(evidences, "false_positive"),
            "unreviewed_count": self._count_review(evidences, "unreviewed"),
            "third_party_evidence_count": sum(
                1 for evidence in evidences if evidence.third_party_status == "third_party"
            ),
            "self_citation_evidence_count": sum(
                1 for evidence in evidences if evidence.is_self_citation
            ),
            "high_strength_count": sum(
                1 for evidence in evidences if evidence.evidence_strength == "strong"
            ),
            "medium_strength_count": sum(
                1 for evidence in evidences if evidence.evidence_strength == "moderate"
            ),
            "low_strength_count": sum(
                1 for evidence in evidences if evidence.evidence_strength == "weak"
            ),
        }

    def _find_duplicate(
        self,
        *,
        queue_item_id: int,
        citation_edge_id: int,
        aspect: str,
        stance: str,
        mention_type: str,
        citation_text: str,
    ) -> Optional[StrongEvidence]:
        statement = select(StrongEvidence).where(
            StrongEvidence.queue_item_id == queue_item_id,
            StrongEvidence.citation_edge_id == citation_edge_id,
            StrongEvidence.aspect == aspect,
            StrongEvidence.stance == stance,
            StrongEvidence.mention_type == mention_type,
            StrongEvidence.citation_text == citation_text,
        )
        return self.db.scalars(statement).first()

    def _matches_view(
        self,
        evidence: StrongEvidence,
        item: DeepAnalysisQueueItem,
        view: str,
    ) -> bool:
        if view in {"all", ""}:
            return True
        if view in {"accepted", "important", "unreviewed", "false_positive"}:
            return evidence.review_status == view
        if view == "positive":
            return evidence.stance == "positive"
        if view == "high_strength":
            return evidence.evidence_strength == "strong"
        if view == "third_party_only":
            return evidence.third_party_status == "third_party"
        if view == "exclude_self_citation":
            return not evidence.is_self_citation
        if view in {
            "first_or_seminal_claim",
            "detailed_comparison",
            "baseline_or_benchmark",
            "method_foundation",
            "theoretical_foundation",
        }:
            return evidence.aspect == view
        return True

    def _count_review(self, evidences: List[StrongEvidence], review_status: str) -> int:
        return sum(1 for evidence in evidences if evidence.review_status == review_status)

    def _list_notable_annotations(self, queue_item_id: int):
        statement = (
            select(CitationAuthorAnnotation)
            .where(
                CitationAuthorAnnotation.queue_item_id == queue_item_id,
                CitationAuthorAnnotation.is_important.is_(True),
                CitationAuthorAnnotation.match_status == "matched",
            )
            .order_by(CitationAuthorAnnotation.id.asc())
        )
        return list(self.db.scalars(statement))

    def _anchor_validation(self, evidence: StrongEvidence, item: DeepAnalysisQueueItem):
        result = self.db.get(FulltextAnalysisResult, evidence.fulltext_result_id)
        diagnostics = self._load_json(result.candidate_spans_json if result else None)
        return validate_citation_target_anchor(
            citation_text=evidence.citation_text or "",
            target_reference_marker=diagnostics.get("target_reference_marker"),
            cited_paper_title=item.cited_paper_title,
            cited_authors_json=item.cited_authors_json,
        )

    def _context_preview(self, evidence: StrongEvidence):
        result = self.db.get(FulltextAnalysisResult, evidence.fulltext_result_id)
        if result is None or result.queue_item_id is None:
            return build_context_preview(extracted_text_path=None, citation_text="")
        item = self.db.get(DeepAnalysisQueueItem, result.queue_item_id)
        if item is None or not item.pdf_asset_id:
            return build_context_preview(extracted_text_path=None, citation_text="")
        asset = self.db.get(PdfAsset, item.pdf_asset_id)
        return build_context_preview(
            extracted_text_path=asset.extracted_text_path if asset else None,
            citation_text=evidence.citation_text or "",
            diagnostics=result.candidate_spans_json,
            target_reference_marker=self._load_json(result.candidate_spans_json).get("target_reference_marker"),
            highlight_terms=self._load_json_list(evidence.highlight_keywords_json),
        )

    def _load_json(self, value: Optional[str]):
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _template_names_for_evidence(self, evidence: StrongEvidence) -> List[str]:
        names = []
        for template_id in self._load_json_list(evidence.matched_template_ids_json):
            try:
                template = self.db.get(AnalysisTemplate, int(template_id))
            except (TypeError, ValueError):
                template = None
            if template is not None:
                names.append(template.description or template.name)
        return names

    def _load_json_list(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []


def get_evidence_service(db: Session = Depends(get_db)) -> EvidenceService:
    return EvidenceService(db)
