"""Service layer for local task management."""

import json
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AnalysisTask
from app.repositories.task_repo import TaskRepository


class DuplicateActiveTaskError(Exception):
    pass


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def enqueue(
        self,
        *,
        session_kind: str,
        session_id: int,
        task_type: str,
        payload: Optional[dict] = None,
    ) -> AnalysisTask:
        if self.repository.has_active_task(
            session_kind=session_kind,
            session_id=session_id,
            task_type=task_type,
        ):
            raise DuplicateActiveTaskError(
                f"Active {task_type} task already exists for {session_kind}:{session_id}"
            )

        return self.repository.create(
            session_kind=session_kind,
            session_id=session_id,
            task_type=task_type,
            payload=payload,
        )

    def get_task(self, task_id: int) -> Optional[AnalysisTask]:
        return self.repository.get_by_id(task_id)

    def get_recent_for_session(
        self,
        *,
        session_kind: str,
        session_id: int,
        limit: int = 5,
    ) -> List[AnalysisTask]:
        return self.repository.get_recent_for_session(
            session_kind=session_kind,
            session_id=session_id,
            limit=limit,
        )

    def resume(self, task_id: int) -> AnalysisTask:
        task = self.repository.get_by_id(task_id)
        if task is None:
            raise ValueError("Task not found")
        payload = {}
        try:
            payload = json.loads(task.payload_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["resume_requested"] = True
        task.payload_json = json.dumps(payload, ensure_ascii=False)
        return self.repository.resume(task)

    def pause(self, task_id: int) -> AnalysisTask:
        task = self.repository.get_by_id(task_id)
        if task is None:
            raise ValueError("Task not found")
        if task.status == "running":
            return self.repository.request_pause(task)
        return self.repository.pause(task)


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(TaskRepository(db))
