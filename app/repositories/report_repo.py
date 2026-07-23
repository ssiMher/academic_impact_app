"""Read-only repository for paper session report exports."""

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CitingPaper,
    FulltextAnalysisResult,
    PaperAnalysisSession,
    Publication,
    StrongEvidence,
)


class ReportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_session(self, session_id: int) -> Optional[PaperAnalysisSession]:
        return self.db.get(PaperAnalysisSession, session_id)

    def list_citing_papers(
        self,
        session_id: int,
    ) -> List[Tuple[CitingPaper, Publication]]:
        statement = (
            select(CitingPaper, Publication)
            .join(Publication, CitingPaper.publication_id == Publication.id)
            .where(CitingPaper.paper_session_id == session_id)
            .order_by(CitingPaper.id.asc())
        )
        return list(self.db.execute(statement).all())

    def list_fulltext_results(
        self,
        session_id: int,
    ) -> List[Tuple[FulltextAnalysisResult, CitingPaper]]:
        statement = (
            select(FulltextAnalysisResult, CitingPaper)
            .join(CitingPaper, FulltextAnalysisResult.citing_paper_id == CitingPaper.id)
            .where(CitingPaper.paper_session_id == session_id)
            .order_by(FulltextAnalysisResult.id.asc())
        )
        return list(self.db.execute(statement).all())

    def list_strong_evidence(
        self,
        session_id: int,
    ) -> List[Tuple[StrongEvidence, FulltextAnalysisResult, CitingPaper, Publication]]:
        statement = (
            select(StrongEvidence, FulltextAnalysisResult, CitingPaper, Publication)
            .join(
                FulltextAnalysisResult,
                StrongEvidence.fulltext_result_id == FulltextAnalysisResult.id,
            )
            .join(CitingPaper, FulltextAnalysisResult.citing_paper_id == CitingPaper.id)
            .join(Publication, CitingPaper.publication_id == Publication.id)
            .where(CitingPaper.paper_session_id == session_id)
            .order_by(StrongEvidence.score.desc(), StrongEvidence.id.asc())
        )
        return list(self.db.execute(statement).all())
