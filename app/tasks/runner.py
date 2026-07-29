"""Inline local task runner."""

from typing import Optional

from app.models import AnalysisTask
from app.repositories.task_repo import TaskRepository
from app.tasks.task_manager import TaskManager


class TaskRunner:
    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        task_manager: TaskManager,
    ) -> None:
        self.task_repository = task_repository
        self.task_manager = task_manager

    def claim_next_task(self) -> Optional[AnalysisTask]:
        return self.task_repository.claim_next_task()

    def run_once(self) -> Optional[AnalysisTask]:
        task = self.claim_next_task()
        if task is None:
            return None

        try:
            self.task_manager.run(self.task_repository.db, task)
        except Exception as exc:
            self.task_repository.db.rollback()
            return self.task_repository.mark_failed(task, str(exc))

        self.task_repository.db.refresh(task)
        if task.status != "running":
            return task
        return self.task_repository.mark_succeeded(
            task,
            task.stage_message or "Task completed.",
        )
