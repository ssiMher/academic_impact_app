"""Persist reportable fulltext_template_direct outputs without rerunning the LLM."""

import json
import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models import (
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    HighlightCard,
    StrongEvidence,
)
from app.services.evidence_service import EvidenceService
from app.services.highlight_card_service import HighlightCardService


logger = logging.getLogger(__name__)


class TemplateDirectPersistenceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.evidence_service = EvidenceService(db)

    def preview(self, fulltext_result_id: int) -> Dict[str, Any]:
        result, item, payload = self._load_result(fulltext_result_id)
        candidates = self._eligible_candidates(payload)
        persisted_evidence_count = self._persisted_evidence_count(result.id)
        persisted_card_count = self._persisted_card_count(result.id)
        return {
            "fulltext_result_id": result.id,
            "scholar_session_id": item.scholar_session_id,
            "queue_item_id": item.id,
            "generated_strong_evidence_count": len(candidates),
            "persisted_strong_evidence_count": persisted_evidence_count,
            "strong_evidence_count": persisted_evidence_count,
            "generated_highlight_card_count": len(candidates),
            "persisted_highlight_card_count": persisted_card_count,
            "strong_evidence_persistence_failed_count": 0,
            "highlight_card_persistence_failed_count": 0,
            "candidate_evidences": [
                {
                    "evidence_index": index,
                    "final_claim_type": self._final_claim_type(evidence),
                    "matched_template_ids": self._template_ids(evidence),
                    "evidence_quote": str(evidence.get("evidence_quote") or ""),
                }
                for index, evidence in candidates
            ],
            "warnings": [],
            "failures": [],
            "applied": False,
        }

    def persist(self, fulltext_result_id: int) -> Dict[str, Any]:
        result, item, payload = self._load_result(fulltext_result_id)
        candidates = self._eligible_candidates(payload)
        summary = self.preview(fulltext_result_id)
        summary["applied"] = True
        persisted_evidence_ids: List[int] = []

        for evidence_index, evidence in candidates:
            try:
                strong_evidence = self._upsert_evidence(
                    result=result,
                    item=item,
                    evidence=evidence,
                    evidence_index=evidence_index,
                )
                self.db.commit()
                self.db.refresh(strong_evidence)
                persisted_evidence_ids.append(strong_evidence.id)
            except Exception:
                self.db.rollback()
                logger.exception(
                    "StrongEvidence persistence failed for result=%s evidence_index=%s",
                    result.id,
                    evidence_index,
                )
                summary["strong_evidence_persistence_failed_count"] += 1
                summary["failures"].append(
                    {
                        "kind": "strong_evidence",
                        "evidence_index": evidence_index,
                        "reason": "StrongEvidence persistence failed; see server logs.",
                    }
                )

        summary["generated_highlight_card_count"] = len(persisted_evidence_ids)
        for evidence_id in persisted_evidence_ids:
            try:
                HighlightCardService(self.db).generate_card_from_evidence(
                    item.scholar_session_id,
                    evidence_id,
                )
            except Exception:
                self.db.rollback()
                logger.exception(
                    "HighlightCard persistence failed for result=%s evidence_id=%s",
                    result.id,
                    evidence_id,
                )
                summary["highlight_card_persistence_failed_count"] += 1
                summary["failures"].append(
                    {
                        "kind": "highlight_card",
                        "strong_evidence_id": evidence_id,
                        "reason": "HighlightCard persistence failed; see server logs.",
                    }
                )

        persisted_evidence_count = self._persisted_evidence_count(result.id)
        persisted_card_count = self._persisted_card_count(result.id)
        summary.update(
            {
                "persisted_strong_evidence_count": persisted_evidence_count,
                "strong_evidence_count": persisted_evidence_count,
                "persisted_highlight_card_count": persisted_card_count,
            }
        )
        if summary["strong_evidence_persistence_failed_count"]:
            summary["warnings"].append(
                "Some reportable evidences could not be persisted."
            )
        if summary["highlight_card_persistence_failed_count"]:
            summary["warnings"].append(
                "Some StrongEvidence rows were saved, but card generation failed."
            )
        self._record_summary(result.id, summary)
        return summary

    def _record_summary(
        self,
        fulltext_result_id: int,
        summary: Dict[str, Any],
    ) -> None:
        result = self.db.get(FulltextAnalysisResult, fulltext_result_id)
        if result is None:
            return
        candidate_payload = self._load_json(result.candidate_spans_json)
        for key in (
            "generated_strong_evidence_count",
            "persisted_strong_evidence_count",
            "strong_evidence_count",
            "generated_highlight_card_count",
            "persisted_highlight_card_count",
            "strong_evidence_persistence_failed_count",
            "highlight_card_persistence_failed_count",
            "warnings",
            "failures",
        ):
            candidate_payload[key] = summary.get(key)
        result.candidate_spans_json = json.dumps(
            candidate_payload,
            ensure_ascii=False,
        )
        self.db.commit()

    def _load_result(self, fulltext_result_id: int):
        result = self.db.get(FulltextAnalysisResult, fulltext_result_id)
        if result is None:
            raise ValueError(f"FulltextAnalysisResult {fulltext_result_id} was not found")
        if result.analysis_scope != "fulltext_template_direct":
            raise ValueError("Only fulltext_template_direct results can be regenerated")
        if result.status != "succeeded":
            raise ValueError("Only succeeded fulltext_template_direct results can be regenerated")
        if result.queue_item_id is None:
            raise ValueError("Fulltext result has no queue item")
        item = self.db.get(DeepAnalysisQueueItem, result.queue_item_id)
        if item is None:
            raise ValueError(f"Queue item {result.queue_item_id} was not found")
        payload = self._load_json(result.parsed_result_json)
        return result, item, payload

    def _eligible_candidates(self, payload: dict):
        candidates = []
        for evidence_index, evidence in enumerate(payload.get("evidences", []) or []):
            if not isinstance(evidence, dict):
                continue
            if self._is_reportable(evidence):
                candidates.append((evidence_index, evidence))
        return candidates

    def _is_reportable(self, evidence: dict) -> bool:
        recommendation = str(
            evidence.get("final_recommendation")
            or evidence.get("recommendation")
            or ""
        )
        return (
            recommendation == "include"
            and evidence.get("template_satisfied") is True
            and bool(self._template_ids(evidence))
            and str(
                evidence.get("reference_alignment_status")
                or evidence.get("reference_match_status")
                or ""
            )
            == "matched"
        )

    def _upsert_evidence(
        self,
        *,
        result: FulltextAnalysisResult,
        item: DeepAnalysisQueueItem,
        evidence: dict,
        evidence_index: int,
    ) -> StrongEvidence:
        confidence = str(evidence.get("confidence") or "medium").lower()
        score = {"high": 0.9, "medium": 0.75, "low": 0.6}.get(confidence, 0.75)
        claim_type = self._final_claim_type(evidence)
        stance = str(evidence.get("stance") or "").strip() or (
            "negative" if claim_type == "limitation_feedback" else "positive"
        )
        keywords = self._keyword_list(evidence)
        return self.evidence_service.upsert_scholar_evidence(
            fulltext_result_id=result.id,
            scholar_session_id=item.scholar_session_id,
            queue_item_id=item.id,
            citation_edge_id=item.citation_edge_id,
            aspect=claim_type,
            stance=stance,
            mention_type=str(evidence.get("mention_type") or "template_direct"),
            citation_text=str(evidence.get("evidence_quote") or "").strip(),
            highlight_keywords=keywords,
            evidence_reason=str(
                evidence.get("why_this_judgment_zh")
                or evidence.get("template_match_reason")
                or "Template-direct evidence satisfied the active template."
            ),
            evidence_strength="strong",
            score=score,
            span_index=evidence_index,
            is_self_citation=item.self_citation_status == "self_citation",
            third_party_status=item.third_party_status,
            anchor_status=str(
                evidence.get("target_anchor_status")
                or evidence.get("anchor_status")
                or "body_anchor_found"
            ),
            template_result={
                "matched_template_ids": self._template_ids(evidence),
                "template_match_reason": str(
                    evidence.get("template_match_reason") or ""
                ),
                "template_satisfied": True,
                "template_failure_reason": str(
                    evidence.get("template_failure_reason") or ""
                ),
            },
        )

    def _persisted_evidence_count(self, fulltext_result_id: int) -> int:
        return (
            self.db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == fulltext_result_id)
            .count()
        )

    def _persisted_card_count(self, fulltext_result_id: int) -> int:
        return (
            self.db.query(HighlightCard)
            .join(
                StrongEvidence,
                HighlightCard.strong_evidence_id == StrongEvidence.id,
            )
            .filter(StrongEvidence.fulltext_result_id == fulltext_result_id)
            .count()
        )

    def _template_ids(self, evidence: dict) -> List[int]:
        values = evidence.get("matched_template_ids") or []
        result = []
        for value in values:
            try:
                result.append(int(value))
            except (TypeError, ValueError):
                continue
        return list(dict.fromkeys(result))

    def _keyword_list(self, evidence: dict) -> List[str]:
        for key in ("key_phrases", "highlight_keywords", "keywords"):
            values = evidence.get(key)
            if isinstance(values, list):
                return [str(value) for value in values if str(value).strip()]
        return []

    def _final_claim_type(self, evidence: dict) -> str:
        return str(
            evidence.get("final_claim_type")
            or evidence.get("claim_type")
            or "positive_evaluation"
        )

    def _load_json(self, value: str) -> dict:
        try:
            payload = json.loads(value or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Fulltext result parsed_result_json is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("Fulltext result parsed_result_json is invalid")
        return payload
