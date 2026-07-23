"""Repository for analysis templates and template matches."""

from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnalysisTemplate, TemplateMatch


class TemplateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_builtin_templates(self) -> List[AnalysisTemplate]:
        statement = (
            select(AnalysisTemplate)
            .where(
                AnalysisTemplate.is_builtin.is_(True),
                AnalysisTemplate.is_active.is_(True),
            )
            .order_by(AnalysisTemplate.id.asc())
        )
        return list(self.db.scalars(statement))

    def get_template(self, template_id: int) -> Optional[AnalysisTemplate]:
        return self.db.get(AnalysisTemplate, template_id)

    def find_session_template(
        self,
        *,
        session_id: int,
        name: str,
        template_type: str,
    ) -> Optional[AnalysisTemplate]:
        statement = select(AnalysisTemplate).where(
            AnalysisTemplate.session_id == session_id,
            AnalysisTemplate.name == name,
            AnalysisTemplate.template_type == template_type,
        )
        return self.db.scalars(statement).first()

    def get_active_templates(self, session_id: int) -> List[AnalysisTemplate]:
        statement = (
            select(AnalysisTemplate)
            .where(
                AnalysisTemplate.session_id == session_id,
                AnalysisTemplate.is_active.is_(True),
            )
            .order_by(AnalysisTemplate.id.asc())
        )
        return list(self.db.scalars(statement))

    def create_template(self, **values) -> AnalysisTemplate:
        template = AnalysisTemplate(**values)
        self.db.add(template)
        self.db.flush()
        return template

    def delete_queue_matches(self, queue_item_id: int) -> None:
        self.db.execute(delete(TemplateMatch).where(TemplateMatch.queue_item_id == queue_item_id))

    def delete_evidence_matches(self, evidence_id: int) -> None:
        self.db.execute(delete(TemplateMatch).where(TemplateMatch.strong_evidence_id == evidence_id))

    def create_match(self, **values) -> TemplateMatch:
        match = TemplateMatch(**values)
        self.db.add(match)
        self.db.flush()
        return match

    def list_matches_for_evidence(self, evidence_id: int) -> List[TemplateMatch]:
        statement = (
            select(TemplateMatch)
            .where(TemplateMatch.strong_evidence_id == evidence_id)
            .order_by(TemplateMatch.match_score.desc(), TemplateMatch.id.asc())
        )
        return list(self.db.scalars(statement))

    def list_matches_for_queue_item(self, queue_item_id: int) -> List[TemplateMatch]:
        statement = (
            select(TemplateMatch)
            .where(TemplateMatch.queue_item_id == queue_item_id)
            .order_by(TemplateMatch.match_score.desc(), TemplateMatch.id.asc())
        )
        return list(self.db.scalars(statement))
