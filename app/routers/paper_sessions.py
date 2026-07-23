"""Routes for ordinary paper analysis sessions."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.schemas.paper_session import PaperSessionCreate
from app.services.paper_analysis_service import (
    PaperAnalysisService,
    get_paper_analysis_service,
)
from app.services.task_service import DuplicateActiveTaskError


router = APIRouter(prefix="/paper-sessions", tags=["paper-sessions"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/new", response_class=HTMLResponse)
def new_paper_session(request: Request):
    return templates.TemplateResponse(
        request,
        "paper_sessions/new.html",
        {"query_kind": "title"},
    )


@router.post("")
def create_paper_session(
    query_text: str = Form(...),
    query_kind: str = Form("title"),
    service: PaperAnalysisService = Depends(get_paper_analysis_service),
):
    session = service.create_session(
        PaperSessionCreate(query_text=query_text, query_kind=query_kind)
    )
    return RedirectResponse(
        url=f"/paper-sessions/{session.id}",
        status_code=303,
    )


@router.get("/{session_id}", response_class=HTMLResponse)
def paper_session_detail(
    request: Request,
    session_id: int,
    service: PaperAnalysisService = Depends(get_paper_analysis_service),
):
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Paper analysis session not found")

    recent_tasks = service.get_recent_tasks(session_id=session_id)
    citing_papers = service.list_citing_papers(session_id=session_id)
    return templates.TemplateResponse(
        request,
        "paper_sessions/detail.html",
        {
            "session": session,
            "recent_tasks": recent_tasks,
            "citing_papers": citing_papers,
        },
    )


@router.post("/{session_id}/discover")
def enqueue_discover_paper(
    session_id: int,
    service: PaperAnalysisService = Depends(get_paper_analysis_service),
):
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Paper analysis session not found")

    try:
        service.enqueue_discover_task(session_id=session_id)
    except DuplicateActiveTaskError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return RedirectResponse(
        url=f"/paper-sessions/{session_id}",
        status_code=303,
    )
