"""Task status API routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.services.task_service import TaskService, get_task_service


router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}")
def get_task_status(
    task_id: int,
    service: TaskService = Depends(get_task_service),
):
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "id": task.id,
        "session_kind": task.session_kind,
        "session_id": task.session_id,
        "task_type": task.task_type,
        "status": task.status,
        "stage": task.stage,
        "stage_message": task.stage_message,
        "progress_current": task.progress_current,
        "progress_total": task.progress_total,
        "error_message": task.error_message,
    }
