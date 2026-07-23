"""Routes for scholar analysis MVP sessions."""

from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.scholar_analysis_service import (
    ScholarAnalysisService,
    get_scholar_analysis_service,
)
from app.services.task_service import DuplicateActiveTaskError


router = APIRouter(prefix="/scholar-sessions", tags=["scholar-sessions"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/new", response_class=HTMLResponse)
def new_scholar_session(request: Request):
    return templates.TemplateResponse(
        request,
        "scholar_sessions/new.html",
        {},
    )


@router.post("")
def create_scholar_session(
    author_ref: str = Form(...),
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    session = service.create_scholar_session(author_ref)
    return RedirectResponse(
        url=f"/scholar-sessions/{session.id}",
        status_code=303,
    )


@router.get("/{session_id}", response_class=HTMLResponse)
def scholar_session_detail(
    request: Request,
    session_id: int,
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    detail = service.get_scholar_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Scholar analysis session not found")

    return templates.TemplateResponse(
        request,
        "scholar_sessions/detail.html",
        detail,
    )


@router.post("/{session_id}/expand-citations")
def enqueue_expand_scholar_citations(
    session_id: int,
    publication_ids: List[int] = Form([]),
    limit_per_publication: int = Form(0),
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    try:
        service.enqueue_expand_scholar_citations(
            session_id=session_id,
            publication_ids=publication_ids,
            limit_per_publication=limit_per_publication,
        )
    except DuplicateActiveTaskError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)

    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}",
        status_code=303,
    )


@router.post("/{session_id}/expand-and-build-queue")
def enqueue_expand_and_build_scholar_queue(
    session_id: int,
    publication_ids: List[int] = Form([]),
    limit_per_publication: int = Form(0),
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    try:
        service.enqueue_expand_and_build_scholar_queue(
            session_id=session_id,
            publication_ids=publication_ids,
            limit_per_publication=limit_per_publication,
        )
    except DuplicateActiveTaskError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)

    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}",
        status_code=303,
    )
