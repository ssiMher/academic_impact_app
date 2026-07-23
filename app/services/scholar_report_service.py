"""Build scholar impact report exports from existing evidence and cards."""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import (
    CitationEdge,
    DeepAnalysisQueueItem,
    HighlightCard,
    Publication,
    ScholarAnalysisSession,
    ScholarPublication,
    StrongEvidence,
)
from app.services.highlight_card_service import HighlightCardService


class ScholarReportNotFoundError(ValueError):
    pass


class ScholarReportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.card_service = HighlightCardService(db)

    def build_report_markdown(self, session_id: int) -> str:
        session = self.db.get(ScholarAnalysisSession, session_id)
        if session is None:
            raise ScholarReportNotFoundError(f"ScholarAnalysisSession {session_id} was not found")
        return self.card_service.export_cards_markdown(session_id)

    def build_structured_json(self, session_id: int) -> str:
        return json.dumps(
            self.build_structured_data(session_id),
            ensure_ascii=False,
            indent=2,
        )

    def build_structured_data(self, session_id: int) -> Dict[str, Any]:
        session = self.db.get(ScholarAnalysisSession, session_id)
        if session is None:
            raise ScholarReportNotFoundError(f"ScholarAnalysisSession {session_id} was not found")
        cards = [
            card for card in self.card_service.list_cards(session_id)
            if self._is_reportable_card(card)
        ]
        evidences = self._list_report_evidence(session_id)
        return {
            "exports": {
                "schema_version": "phase14",
                "generated_at": datetime.utcnow().isoformat(),
                "formats": [
                    "report.md",
                    "structured.json",
                    "highlight_cards.csv",
                    "highlight_cards.md",
                ],
            },
            "scholar_session": self._session_to_dict(session),
            "publications_summary": self._publication_summary(session_id),
            "citation_edges_summary": self._citation_edges_summary(session_id),
            "queue_summary": self._queue_summary(session_id),
            "evidence_summary": self._evidence_summary(evidences),
            "strong_evidence": [self._evidence_to_dict(evidence) for evidence in evidences],
            "highlight_cards": [self._card_to_dict(card) for card in cards],
        }

    def write_report_markdown(self, session_id: int) -> Path:
        path = self._session_export_dir(session_id) / "report.md"
        path.write_text(self.build_report_markdown(session_id), encoding="utf-8")
        return path

    def write_structured_json(self, session_id: int) -> Path:
        path = self._session_export_dir(session_id) / "structured.json"
        path.write_text(self.build_structured_json(session_id), encoding="utf-8")
        return path

    def _list_report_evidence(self, session_id: int) -> List[StrongEvidence]:
        statement = select(StrongEvidence).where(
            StrongEvidence.scholar_session_id == session_id,
            StrongEvidence.review_status.not_in({"rejected", "false_positive"}),
        )
        return list(self.db.scalars(statement))

    def _session_to_dict(self, session: ScholarAnalysisSession) -> Dict[str, Any]:
        return {
            "id": session.id,
            "display_name": session.display_name,
            "dblp_id": session.dblp_id,
            "openalex_id": session.openalex_id,
            "scopus_author_id": session.scopus_author_id,
            "status": session.status,
            "publication_count": session.publication_count,
            "citation_edge_count": session.citation_edge_count,
        }

    def _publication_summary(self, session_id: int) -> Dict[str, Any]:
        rows = list(
            self.db.scalars(
                select(ScholarPublication).where(ScholarPublication.scholar_session_id == session_id)
            )
        )
        return {
            "count": len(rows),
            "items": [
                {
                    "id": row.id,
                    "publication_id": row.publication_id,
                    "title": row.title,
                    "year": row.year,
                    "venue": row.venue,
                    "doi": row.doi,
                }
                for row in rows
            ],
        }

    def _citation_edges_summary(self, session_id: int) -> Dict[str, Any]:
        count = self.db.scalar(
            select(func.count(CitationEdge.id)).where(
                CitationEdge.scholar_session_id == session_id
            )
        )
        return {"count": count or 0}

    def _queue_summary(self, session_id: int) -> Dict[str, Any]:
        rows = list(
            self.db.scalars(
                select(DeepAnalysisQueueItem).where(DeepAnalysisQueueItem.scholar_session_id == session_id)
            )
        )
        return {
            "count": len(rows),
            "analyzed_queue_count": sum(1 for item in rows if item.queue_status == "analyzed"),
            "selected_count": sum(1 for item in rows if item.queue_status == "selected"),
        }

    def _evidence_to_dict(self, evidence: StrongEvidence) -> Dict[str, Any]:
        return {
            "id": evidence.id,
            "fulltext_result_id": evidence.fulltext_result_id,
            "queue_item_id": evidence.queue_item_id,
            "citation_edge_id": evidence.citation_edge_id,
            "aspect": evidence.aspect,
            "stance": evidence.stance,
            "mention_type": evidence.mention_type,
            "citation_text": evidence.citation_text,
            "highlight_keywords": self._load_json_list(evidence.highlight_keywords_json),
            "evidence_reason": evidence.evidence_reason,
            "evidence_strength": evidence.evidence_strength,
            "score": evidence.score,
            "review_status": evidence.review_status,
            "third_party_status": evidence.third_party_status,
        }

    def _evidence_summary(self, evidences: List[StrongEvidence]) -> Dict[str, int]:
        return {
            "strong_evidence_count": len(evidences),
            "important_evidence_count": sum(
                1 for evidence in evidences if evidence.review_status == "important"
            ),
        }

    def _card_to_dict(self, card: HighlightCard) -> Dict[str, Any]:
        evidence = self.db.get(StrongEvidence, card.strong_evidence_id)
        return {
            "id": card.id,
            "strong_evidence_id": card.strong_evidence_id,
            "source_evidence_id": card.source_evidence_id,
            "card_type": card.card_type,
            "title": card.title,
            "subtitle": card.subtitle,
            "narrative_zh": card.narrative_zh,
            "narrative_en": card.narrative_en,
            "body_markdown": card.body_markdown,
            "evidence_quote": card.evidence_quote,
            "highlighted_quote_html": card.highlighted_quote_html,
            "source_citing_paper_title": card.source_citing_paper_title,
            "source_cited_paper_title": card.source_cited_paper_title,
            "citing_authors_json": self._load_json_list(card.citing_authors_json),
            "notable_author_name": card.notable_author_name,
            "notable_author_affiliation": card.notable_author_affiliation,
            "notable_author_role": card.notable_author_role,
            "fellow_status": card.fellow_status,
            "venue": card.venue,
            "venue_tier": card.venue_tier,
            "aspect": card.aspect,
            "stance": card.stance,
            "evidence_strength": card.evidence_strength,
            "score": card.score,
            "sort_order": card.sort_order,
            "is_user_edited": card.is_user_edited,
            "include_in_report": card.include_in_report,
            "review_status": card.review_status,
            "evidence": self._evidence_to_dict(evidence) if evidence else {},
        }

    def _is_reportable_card(self, card: HighlightCard) -> bool:
        if not card.include_in_report:
            return False
        evidence = self.db.get(StrongEvidence, card.strong_evidence_id)
        if evidence is None:
            return False
        if evidence.review_status in {"rejected", "false_positive"}:
            return False
        if not evidence.citation_text:
            return False
        return True

    def _load_json_list(self, value: Optional[str]) -> List[Any]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _session_export_dir(self, session_id: int) -> Path:
        path = Path(settings.export_dir) / f"scholar_session_{session_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path


def get_scholar_report_service(db: Session = Depends(get_db)) -> ScholarReportService:
    return ScholarReportService(db)
