"""Routes for scholar deep analysis queue."""

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.pdf.security import PdfValidationError
from app.models.constants import SCHOLAR_ANALYSIS_SESSION_KIND
from app.services.pdf_service import PdfService, get_pdf_service
from app.services.pdf_discovery_service import PdfDiscoveryService
from app.services.scholar_queue_service import (
    PdfAssetNotFoundError,
    QueueItemManualPdfExistsError,
    ScholarQueueService,
    ScholarQueueItemNotFoundError,
    get_scholar_queue_service,
)
from app.services.task_service import DuplicateActiveTaskError
from app.services.task_service import TaskService, get_task_service
from app.services.scholar_fulltext_service import (
    ScholarFulltextService,
    get_scholar_fulltext_service,
)


router = APIRouter(prefix="/scholar-sessions", tags=["scholar-queue"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.post("/{session_id}/build-queue")
def enqueue_build_scholar_queue(
    session_id: int,
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    try:
        service.enqueue_build_queue(session_id)
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue", status_code=303)


@router.get("/{session_id}/queue", response_class=HTMLResponse)
def scholar_queue_page(
    request: Request,
    session_id: int,
    view: str = "all",
    analyze_task_id: Optional[int] = None,
    discover_task_id: Optional[int] = None,
    service: ScholarQueueService = Depends(get_scholar_queue_service),
    task_service: TaskService = Depends(get_task_service),
):
    items = service.list_queue_items(session_id, filters={"view": view})
    summary = service.get_queue_summary(session_id)
    selected_ready_item_ids = service.selected_ready_item_ids(session_id)
    analyze_task = _resolve_analyze_task(
        task_service=task_service,
        session_id=session_id,
        analyze_task_id=analyze_task_id,
    )
    discover_task = _resolve_pdf_download_task(
        task_service=task_service,
        session_id=session_id,
        discover_task_id=discover_task_id,
    )
    return templates.TemplateResponse(
        request,
        "scholar_sessions/queue.html",
        {
            "session_id": session_id,
            "items": items,
            "view": view,
            "summary": summary,
            "selected_ready_item_ids": selected_ready_item_ids,
            "analyze_task": analyze_task,
            "analyze_task_created": analyze_task_id is not None and analyze_task is not None,
            "discover_task": discover_task,
            "discover_task_created": (
                discover_task_id is not None and discover_task is not None
            ),
        },
    )


@router.post("/{session_id}/queue/select")
def select_queue_items(
    session_id: int,
    item_ids: List[int] = Form([]),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    service.select_queue_items(session_id, item_ids)
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue?view=selected", status_code=303)


@router.post("/{session_id}/queue/bulk-select")
def bulk_select_queue_items(
    session_id: int,
    mode: str = Form("current_view"),
    view: str = Form("all"),
    item_ids: List[int] = Form([]),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    if mode == "current_view":
        item_ids = service.item_ids_for_view(session_id, view)
    elif mode == "ready_items":
        item_ids = service.item_ids_for_ready(session_id)
    elif mode == "important_items":
        item_ids = service.item_ids_for_important(session_id)
    service.select_queue_items(session_id, item_ids)
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue?view={view}", status_code=303)


@router.post("/{session_id}/queue/bulk-clear")
def bulk_clear_queue_selection(
    session_id: int,
    mode: str = Form("current_view"),
    view: str = Form("all"),
    item_ids: List[int] = Form([]),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    if mode == "current_view":
        item_ids = service.item_ids_for_view(session_id, view)
    service.clear_queue_selection(session_id, item_ids)
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue?view={view}", status_code=303)


@router.post("/{session_id}/queue/skip")
def skip_queue_items(
    session_id: int,
    item_ids: List[int] = Form([]),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    service.skip_queue_items(session_id, item_ids)
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue?view=skipped", status_code=303)


@router.post("/{session_id}/queue/bulk-analyze")
def bulk_analyze_queue_items(
    session_id: int,
    analysis_scope: str = Form("fulltext_anchor_direct"),
    service: ScholarFulltextService = Depends(get_scholar_fulltext_service),
    queue_service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    task = service.enqueue_analyze_queue(
        session_id=session_id,
        queue_item_ids=queue_service.selected_ready_item_ids(session_id),
        analysis_scope=analysis_scope,
    )
    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}/queue?view=selected&analyze_task_id={task.id}",
        status_code=303,
    )


@router.post("/{session_id}/queue/discover-pdfs")
def enqueue_discover_pdfs_for_queue(
    session_id: int,
    task_service: TaskService = Depends(get_task_service),
):
    try:
        task = task_service.enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="discover_pdfs_for_queue",
        )
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}/queue?discover_task_id={task.id}",
        status_code=303,
    )


@router.post("/{session_id}/queue/{item_id}/download-open-pdf")
def download_open_pdf_for_queue_item(
    session_id: int,
    item_id: int,
    pdf_service: PdfService = Depends(get_pdf_service),
    queue_service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    try:
        queue_service.get_queue_item_for_session(session_id=session_id, item_id=item_id)
    except ScholarQueueItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    discovery = PdfDiscoveryService(pdf_service.repository.db)
    result = discovery.discover_and_download_for_queue_item(
        item_id=item_id,
        pdf_service=pdf_service,
    )
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("reason", "download failed"))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue", status_code=303)


@router.post("/{session_id}/queue/{item_id}/download-ieee-pdf")
def enqueue_ieee_pdf_download(
    session_id: int,
    item_id: int,
    queue_service: ScholarQueueService = Depends(get_scholar_queue_service),
    task_service: TaskService = Depends(get_task_service),
):
    try:
        queue_service.get_queue_item_for_session(session_id=session_id, item_id=item_id)
        task = task_service.enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="download_ieee_pdf",
            payload={"queue_item_id": item_id},
        )
    except ScholarQueueItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}/queue?ieee_download_task_id={task.id}",
        status_code=303,
    )


@router.post("/{session_id}/queue/bulk-update")
def bulk_update_queue_items(
    session_id: int,
    action: str = Form(...),
    item_ids: List[int] = Form([]),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    if action == "skip":
        service.skip_queue_items(session_id, item_ids)
        redirect_view = "skipped"
    elif action == "mark_important":
        for item_id in item_ids:
            service.update_queue_item_review(item_id, "important", "")
        redirect_view = "important"
    else:
        raise HTTPException(status_code=400, detail="Unsupported bulk action")
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue?view={redirect_view}", status_code=303)


@router.post("/{session_id}/queue/{item_id}/review")
def review_queue_item(
    session_id: int,
    item_id: int,
    review_status: str = Form(...),
    user_note: str = Form(""),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    try:
        service.update_queue_item_review(item_id, review_status, user_note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue", status_code=303)


@router.post("/{session_id}/queue/{item_id}/upload-pdf")
async def upload_pdf_for_queue_item(
    session_id: int,
    item_id: int,
    file: UploadFile = File(...),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
    pdf_service: PdfService = Depends(get_pdf_service),
):
    content = await file.read()
    try:
        service.upload_pdf_for_queue_item(
            session_id=session_id,
            item_id=item_id,
            filename=file.filename or "",
            content=content,
            mime_type=file.content_type or "application/pdf",
            pdf_service=pdf_service,
        )
    except ScholarQueueItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except QueueItemManualPdfExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PdfValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue", status_code=303)


@router.post("/{session_id}/queue/{item_id}/attach-existing-pdf")
def attach_existing_pdf_to_queue_item(
    session_id: int,
    item_id: int,
    pdf_asset_id: int = Form(...),
    service: ScholarQueueService = Depends(get_scholar_queue_service),
):
    try:
        service.attach_existing_pdf_to_queue_item(
            session_id=session_id,
            item_id=item_id,
            pdf_asset_id=pdf_asset_id,
        )
    except ScholarQueueItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PdfAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except QueueItemManualPdfExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/queue", status_code=303)


def _resolve_analyze_task(
    *,
    task_service: TaskService,
    session_id: int,
    analyze_task_id: Optional[int],
):
    if analyze_task_id is not None:
        task = task_service.get_task(analyze_task_id)
        if (
            task is not None
            and task.session_kind == SCHOLAR_ANALYSIS_SESSION_KIND
            and task.session_id == session_id
            and task.task_type == "analyze_scholar_queue"
        ):
            return task

    recent_tasks = task_service.get_recent_for_session(
        session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
        session_id=session_id,
        limit=10,
    )
    analyze_tasks = [
        task for task in recent_tasks if task.task_type == "analyze_scholar_queue"
    ]
    active_task = next(
        (task for task in analyze_tasks if task.status in {"pending", "running"}),
        None,
    )
    return active_task or (analyze_tasks[0] if analyze_tasks else None)


def _resolve_pdf_download_task(
    *,
    task_service: TaskService,
    session_id: int,
    discover_task_id: Optional[int],
):
    task = None
    if discover_task_id is not None:
        candidate = task_service.get_task(discover_task_id)
        if (
            candidate is not None
            and candidate.session_kind == SCHOLAR_ANALYSIS_SESSION_KIND
            and candidate.session_id == session_id
            and candidate.task_type in {
                "discover_pdfs_for_queue",
                "download_open_access_pdfs",
            }
        ):
            task = candidate
    if task is None:
        recent = task_service.get_recent_for_session(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            limit=20,
        )
        tasks = [
            value
            for value in recent
            if value.task_type
            in {"discover_pdfs_for_queue", "download_open_access_pdfs"}
        ]
        task = next(
            (value for value in tasks if value.status in {"pending", "running"}),
            tasks[0] if tasks else None,
        )
    if task is not None:
        try:
            payload = json.loads(task.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        task.result_summary = (
            payload.get("result_summary")
            if isinstance(payload, dict)
            and isinstance(payload.get("result_summary"), dict)
            else None
        )
    return task
