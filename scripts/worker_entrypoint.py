"""Shared worker entrypoints for command-line scripts."""

import time
from typing import Callable, Optional

from app.db.base import init_db
from app.db.session import SessionLocal
from app.models import AnalysisTask
from app.repositories.task_repo import TaskRepository
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager


def build_runner(db) -> TaskRunner:
    return TaskRunner(
        task_repository=TaskRepository(db),
        task_manager=TaskManager(),
    )


def format_task_result(task: Optional[AnalysisTask]) -> str:
    if task is None:
        return "No pending task."
    return f"Task #{task.id} {task.task_type} -> {task.status}"


def run_worker_once(
    session_factory=SessionLocal,
    printer: Callable[[str], None] = print,
    ensure_schema: bool = True,
):
    if ensure_schema:
        init_db()
    db = session_factory()
    try:
        task = build_runner(db).run_once()
        printer(format_task_result(task))
        return task
    finally:
        db.close()


def run_worker_forever(
    *,
    session_factory=SessionLocal,
    printer: Callable[[str], None] = print,
    sleep_seconds: float = 1.0,
) -> None:
    init_db()
    try:
        while True:
            task = run_worker_once(
                session_factory=session_factory,
                printer=printer,
                ensure_schema=False,
            )
            if task is None:
                time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        printer("Worker stopped.")
