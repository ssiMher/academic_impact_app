"""Business service for ordinary paper analysis sessions."""

from typing import List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AnalysisTask, CitingPaper, PaperAnalysisSession
from app.providers.citation_provider import get_citation_provider
from app.providers.metadata_provider import get_metadata_provider
from app.repositories.paper_session_repo import PaperSessionRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.paper_session import PaperSessionCreate
from app.services.task_service import TaskService


class PaperAnalysisService:
    def __init__(self, repository: PaperSessionRepository) -> None:
        self.repository = repository
        self.citation_provider = get_citation_provider()
        self.metadata_provider = get_metadata_provider()

    def create_session(self, data: PaperSessionCreate) -> PaperAnalysisSession:
        return self.repository.create(data)

    def get_session(self, session_id: int) -> Optional[PaperAnalysisSession]:
        return self.repository.get_by_id(session_id)

    def enqueue_discover_task(self, session_id: int) -> AnalysisTask:
        task_service = TaskService(TaskRepository(self.repository.db))
        return task_service.enqueue(
            session_kind="paper_analysis",
            session_id=session_id,
            task_type="discover_paper",
        )

    def get_recent_tasks(self, session_id: int, limit: int = 5) -> List[AnalysisTask]:
        return TaskRepository(self.repository.db).get_recent_for_session(
            session_kind="paper_analysis",
            session_id=session_id,
            limit=limit,
        )

    def list_citing_papers(self, session_id: int) -> List[CitingPaper]:
        return self.repository.list_citing_papers(session_id)


def get_paper_analysis_service(
    db: Session = Depends(get_db),
) -> PaperAnalysisService:
    repository = PaperSessionRepository(db)
    return PaperAnalysisService(repository)
