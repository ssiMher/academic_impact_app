"""Repository for scholar highlight cards."""

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeepAnalysisQueueItem, HighlightCard, StrongEvidence


class HighlightCardRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_eligible_evidence(
        self,
        scholar_session_id: int,
    ) -> List[Tuple[StrongEvidence, DeepAnalysisQueueItem]]:
        statement = (
            select(StrongEvidence, DeepAnalysisQueueItem)
            .join(
                DeepAnalysisQueueItem,
                StrongEvidence.queue_item_id == DeepAnalysisQueueItem.id,
            )
            .where(
                StrongEvidence.scholar_session_id == scholar_session_id,
                StrongEvidence.citation_text.is_not(None),
                StrongEvidence.citation_text != "",
                StrongEvidence.review_status.not_in({"rejected", "false_positive"}),
            )
        )
        rows = list(self.db.execute(statement).all())
        return sorted(
            rows,
            key=lambda row: (
                1 if row[0].review_status == "important" else 0,
                1 if row[0].review_status == "accepted" else 0,
                row[0].score or 0,
                -row[0].id,
            ),
            reverse=True,
        )

    def find_by_evidence_id(self, evidence_id: int) -> Optional[HighlightCard]:
        statement = select(HighlightCard).where(
            HighlightCard.strong_evidence_id == evidence_id
        )
        return self.db.scalars(statement).first()

    def create_card(self, **values) -> HighlightCard:
        card = HighlightCard(**values)
        self.db.add(card)
        self.db.flush()
        return card

    def get_card(self, card_id: int) -> Optional[HighlightCard]:
        return self.db.get(HighlightCard, card_id)

    def list_cards(self, scholar_session_id: int) -> List[HighlightCard]:
        statement = (
            select(HighlightCard)
            .where(HighlightCard.scholar_session_id == scholar_session_id)
            .order_by(HighlightCard.sort_order.asc(), HighlightCard.id.asc())
        )
        return list(self.db.scalars(statement))
