"""Business service for scholar analysis MVP flows."""

import re
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.models import (
    AnalysisTask,
    CitationEdge,
    CitationAuthorAnnotation,
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    ScholarAnalysisSession,
    ScholarPublication,
    StrongEvidence,
)
from app.models.constants import SCHOLAR_ANALYSIS_SESSION_KIND, is_pdf_ready_status
from app.providers.author_provider import get_author_provider
from app.providers.base import AuthorProvider
from app.repositories.scholar_session_repo import ScholarSessionRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.scholar_session import ScholarSessionCreate
from app.services.task_service import TaskService
from app.services.external_citation_import_service import ExternalCitationImportService


class ScholarAnalysisService:
    def __init__(
        self,
        repository: ScholarSessionRepository,
        author_provider: Optional[AuthorProvider] = None,
    ) -> None:
        self.repository = repository
        self.author_provider = author_provider or get_author_provider()

    def create_scholar_session(self, author_ref: str) -> ScholarAnalysisSession:
        data = ScholarSessionCreate(author_ref=author_ref.strip())
        author_identity = self.author_provider.resolve_author(data.author_ref)
        return self.repository.create_with_publications(author_identity)

    def list_publications(self, session_id: int) -> List[ScholarPublication]:
        return self.repository.list_publications(session_id)

    def enqueue_expand_scholar_citations(
        self,
        session_id: int,
        publication_ids: List[int],
        limit_per_publication: Optional[int] = None,
    ) -> AnalysisTask:
        if not publication_ids:
            raise ValueError("At least one publication must be selected for expansion")
        if self.repository.get_by_id(session_id) is None:
            raise ValueError(f"ScholarAnalysisSession {session_id} was not found")

        self.repository.mark_selected_for_expansion(
            session_id=session_id,
            publication_ids=publication_ids,
        )
        limit = self._citation_expansion_limit(limit_per_publication)
        return TaskService(TaskRepository(self.repository.db)).enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="expand_scholar_citations",
            payload={"limit_per_publication": limit},
        )

    def enqueue_expand_and_build_scholar_queue(
        self,
        session_id: int,
        publication_ids: List[int],
        limit_per_publication: Optional[int] = None,
    ) -> AnalysisTask:
        if not publication_ids:
            raise ValueError("At least one publication must be selected for expansion")
        if self.repository.get_by_id(session_id) is None:
            raise ValueError(f"ScholarAnalysisSession {session_id} was not found")

        self.repository.mark_selected_for_expansion(
            session_id=session_id,
            publication_ids=publication_ids,
        )
        limit = self._citation_expansion_limit(limit_per_publication)
        task = TaskService(TaskRepository(self.repository.db)).enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="expand_and_build_scholar_queue",
            payload={"limit_per_publication": limit},
        )
        task.stage_message = "阶段 1：扩展引用"
        self.repository.db.commit()
        self.repository.db.refresh(task)
        return task

    def _citation_expansion_limit(self, value: Optional[int]) -> int:
        raw_limit = value if value is not None and value > 0 else settings.citation_expansion_default_limit
        return min(raw_limit, settings.citation_expansion_max_limit)

    def get_scholar_detail(self, session_id: int) -> Optional[dict]:
        session = self.repository.get_by_id(session_id)
        if session is None:
            return None
        self._refresh_display_name_if_needed(session)

        return {
            "session": session,
            "publications": self.repository.list_publications(session_id),
            "recent_tasks": TaskRepository(self.repository.db).get_recent_for_session(
                session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
                session_id=session_id,
                limit=5,
            ),
            "workflow_stats": self._workflow_stats(session_id),
            "citation_expansion_summary": self._citation_expansion_summary(session_id),
            "honor_import_summary": self._honor_import_summary(session_id),
        }

    def _citation_expansion_summary(self, session_id: int) -> dict:
        tasks = TaskRepository(self.repository.db).get_recent_for_session(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            limit=20,
        )
        latest_message = ""
        for task in tasks:
            if task.task_type in {"expand_scholar_citations", "expand_and_build_scholar_queue"} and task.stage_message:
                latest_message = task.stage_message
                break
        total = self._extract_stage_int(latest_message, "openalex_cited_by_count")
        fetched = self._extract_stage_int(latest_message, "fetched")
        limit = self._extract_stage_int(latest_message, "limit")
        complete = self._extract_stage_bool(latest_message, "complete")
        openalex_edge_count = self.repository.db.query(CitationEdge).filter_by(
            scholar_session_id=session_id,
            provider_name="openalex",
        ).count()
        return {
            "provider": "openalex" if "provider=openalex" in latest_message else "",
            "openalex_cited_by_count": total,
            "expanded_citation_edges_count": openalex_edge_count,
            "external_import_count": ExternalCitationImportService(self.repository.db).external_count_for_session(
                session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
                session_id=session_id,
            ),
            "fetched_count": fetched,
            "citation_expansion_limit": limit,
            "citation_expansion_complete": complete,
            "external_citation_count_source": "Google Scholar",
            "external_citation_count_value": None,
            "incomplete": bool(total and openalex_edge_count and openalex_edge_count < total),
        }

    def _extract_stage_int(self, message: str, key: str) -> Optional[int]:
        match = re.search(rf"{re.escape(key)}=(\d+)", message or "")
        return int(match.group(1)) if match else None

    def _extract_stage_bool(self, message: str, key: str) -> Optional[bool]:
        match = re.search(rf"{re.escape(key)}=(true|false)", message or "", flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).lower() == "true"

    def _workflow_stats(self, session_id: int) -> dict:
        session = self.repository.get_by_id(session_id)
        queue_items = self.repository.db.query(DeepAnalysisQueueItem).filter_by(
            scholar_session_id=session_id
        ).all()
        return {
            "deep_analysis_queue_count": len(queue_items),
            "citation_edge_count": session.citation_edge_count if session is not None else 0,
            "pdf_ready_count": sum(
                1
                for item in queue_items
                if is_pdf_ready_status(item.pdf_readiness_status)
            ),
            "analyzed_item_count": sum(
                1 for item in queue_items if item.queue_status == "analyzed"
            ),
            "failed_item_count": sum(
                1 for item in queue_items if item.queue_status == "failed"
            ),
            "fulltext_result_count": self.repository.db.query(FulltextAnalysisResult)
            .filter_by(scholar_session_id=session_id)
            .count(),
            "strong_evidence_count": self.repository.db.query(StrongEvidence)
            .filter_by(scholar_session_id=session_id)
            .count(),
        }

    def _honor_import_summary(self, session_id: int) -> dict:
        annotations = (
            self.repository.db.query(CitationAuthorAnnotation)
            .filter_by(scholar_session_id=session_id)
            .all()
        )
        return {
            "notable_author_count": len({annotation.notable_author_id for annotation in annotations}),
            "important_citation_count": sum(1 for annotation in annotations if annotation.is_important),
            "matched_count": sum(1 for annotation in annotations if annotation.match_status == "matched"),
            "ambiguous_count": sum(1 for annotation in annotations if annotation.match_status == "ambiguous"),
            "unmatched_count": sum(1 for annotation in annotations if annotation.match_status == "unmatched"),
            "total_rows": len(annotations),
            "important_queue_items_count": len(
                {
                    annotation.queue_item_id
                    for annotation in annotations
                    if annotation.is_important and annotation.queue_item_id is not None
                }
            ),
        }

    def _refresh_display_name_if_needed(self, session: ScholarAnalysisSession) -> None:
        if not session.dblp_id:
            return
        current = (session.display_name or "").strip()
        if current and current not in {"待解析", session.dblp_id}:
            return
        provider = self.author_provider
        if not hasattr(provider, "resolve_author_name_by_pid"):
            return
        try:
            resolved = provider.resolve_author_name_by_pid(session.dblp_id)
        except Exception:
            return
        if resolved and resolved != current:
            session.display_name = resolved
            self.repository.db.commit()


def get_scholar_analysis_service(
    db: Session = Depends(get_db),
) -> ScholarAnalysisService:
    return ScholarAnalysisService(ScholarSessionRepository(db))
