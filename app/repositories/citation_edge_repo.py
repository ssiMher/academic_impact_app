"""Repository for scholar citation edges."""

import json
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CitationEdge


class CitationEdgeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        scholar_session_id: int,
        cited_publication_id: int,
        citing_publication_id: int,
        provider_name: str,
        self_citation_status: str = "unknown",
        third_party_status: str = "third_party",
        edge_meta: Optional[dict] = None,
    ) -> CitationEdge:
        existing = self.get_existing(
            scholar_session_id=scholar_session_id,
            cited_publication_id=cited_publication_id,
            citing_publication_id=citing_publication_id,
        )
        if existing is not None:
            return existing

        edge = CitationEdge(
            scholar_session_id=scholar_session_id,
            cited_publication_id=cited_publication_id,
            citing_publication_id=citing_publication_id,
            provider_name=provider_name,
            self_citation_status=self_citation_status,
            third_party_status=third_party_status,
            edge_meta_json=json.dumps(edge_meta or {}),
        )
        self.db.add(edge)
        self.db.flush()
        return edge

    def get_existing(
        self,
        *,
        scholar_session_id: int,
        cited_publication_id: int,
        citing_publication_id: int,
    ) -> Optional[CitationEdge]:
        statement = select(CitationEdge).where(
            CitationEdge.scholar_session_id == scholar_session_id,
            CitationEdge.cited_publication_id == cited_publication_id,
            CitationEdge.citing_publication_id == citing_publication_id,
        )
        return self.db.scalars(statement).first()

    def count_for_session(self, scholar_session_id: int) -> int:
        statement = select(func.count(CitationEdge.id)).where(
            CitationEdge.scholar_session_id == scholar_session_id
        )
        return int(self.db.scalar(statement) or 0)
