"""Repository for local analysis tasks."""

from datetime import datetime
import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisTask


ACTIVE_TASK_STATUSES = {
    "pending",
    "running",
    "waiting_for_login",
    "challenge_blocked",
    "pause_requested",
    "paused",
}


class TaskRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        session_kind: str,
        session_id: int,
        task_type: str,
        stage: str = "queued",
        payload: Optional[dict] = None,
    ) -> AnalysisTask:
        task = AnalysisTask(
            session_kind=session_kind,
            session_id=session_id,
            task_type=task_type,
            payload_json=json.dumps(payload or {}) if payload else None,
            status="pending",
            stage=stage,
            progress_current=0,
            progress_total=0,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get_by_id(self, task_id: int) -> Optional[AnalysisTask]:
        return self.db.get(AnalysisTask, task_id)

    def get_recent_for_session(
        self,
        *,
        session_kind: str,
        session_id: int,
        limit: int = 5,
    ) -> List[AnalysisTask]:
        statement = (
            select(AnalysisTask)
            .where(
                AnalysisTask.session_kind == session_kind,
                AnalysisTask.session_id == session_id,
            )
            .order_by(AnalysisTask.created_at.desc(), AnalysisTask.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(statement))

    def has_active_task(
        self,
        *,
        session_kind: str,
        session_id: int,
        task_type: str,
    ) -> bool:
        statement = select(AnalysisTask.id).where(
            AnalysisTask.session_kind == session_kind,
            AnalysisTask.session_id == session_id,
            AnalysisTask.task_type == task_type,
            AnalysisTask.status.in_(ACTIVE_TASK_STATUSES),
        )
        return self.db.execute(statement).first() is not None

    def claim_next_task(self) -> Optional[AnalysisTask]:
        statement = (
            select(AnalysisTask)
            .where(AnalysisTask.status == "pending")
            .order_by(AnalysisTask.created_at.asc(), AnalysisTask.id.asc())
            .limit(1)
        )
        task = self.db.scalars(statement).first()
        if task is None:
            return None

        task.status = "running"
        task.stage = "running"
        existing_stage_message = task.stage_message or ""
        if "analysis_scope=" in existing_stage_message:
            task.stage_message = f"Task is running. {existing_stage_message}"
        else:
            task.stage_message = "Task is running."
        task.started_at = datetime.utcnow()
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_succeeded(self, task: AnalysisTask, stage_message: str = "Task completed.") -> AnalysisTask:
        task.status = "succeeded"
        task.stage = "finished"
        task.stage_message = stage_message
        task.error_message = None
        task.finished_at = datetime.utcnow()
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def mark_failed(self, task: AnalysisTask, error_message: str) -> AnalysisTask:
        task.status = "failed"
        task.stage = "failed"
        task.stage_message = "Task failed."
        task.error_message = error_message
        task.finished_at = datetime.utcnow()
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def resume(self, task: AnalysisTask) -> AnalysisTask:
        task.status = "pending"
        task.stage = "queued_for_resume"
        task.error_message = None
        task.finished_at = None
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def pause(self, task: AnalysisTask) -> AnalysisTask:
        task.status = "paused"
        task.stage = "paused"
        task.stage_message = "任务已暂停；未完成条目和进度已保留。"
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def request_pause(self, task: AnalysisTask) -> AnalysisTask:
        task.status = "pause_requested"
        task.stage = "pause_requested"
        task.stage_message = "正在安全暂停；当前论文完成后将停止后续访问。"
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task
