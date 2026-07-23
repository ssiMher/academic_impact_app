"""Repository for paper analysis sessions."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CitingPaper, PaperAnalysisSession
from app.schemas.paper_session import PaperSessionCreate


class PaperSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: PaperSessionCreate) -> PaperAnalysisSession:
        session = PaperAnalysisSession(
            query_text=data.query_text,
            query_kind=data.query_kind,
            status="created",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_by_id(self, session_id: int) -> Optional[PaperAnalysisSession]:
        return self.db.get(PaperAnalysisSession, session_id)

    def list_citing_papers(self, session_id: int) -> List[CitingPaper]:
        statement = (
            select(CitingPaper)
            .where(CitingPaper.paper_session_id == session_id)
            .order_by(CitingPaper.id.asc())
        )
        return list(self.db.scalars(statement))
