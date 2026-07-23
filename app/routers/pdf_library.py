"""Routes for local PDF library status and task enqueueing."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.pdf_library_service import (
    PdfLibraryService,
    get_pdf_library_service,
)
from app.services.task_service import DuplicateActiveTaskError


router = APIRouter(tags=["pdf-library"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/pdf-library", response_class=HTMLResponse)
def pdf_library_page(
    request: Request,
    service: PdfLibraryService = Depends(get_pdf_library_service),
):
    return templates.TemplateResponse(
        request,
        "pdf_library/index.html",
        service.get_index_status(),
    )


@router.get("/pdf-library.json")
def pdf_library_json(
    service: PdfLibraryService = Depends(get_pdf_library_service),
):
    status = service.get_index_status()
    status.pop("index", None)
    return status


@router.post("/pdf-library/rebuild")
def enqueue_pdf_library_rebuild(
    service: PdfLibraryService = Depends(get_pdf_library_service),
):
    if not service.library_dirs:
        raise HTTPException(status_code=400, detail="local library disabled")
    try:
        service.enqueue_pdf_library_rebuild()
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(url="/pdf-library", status_code=303)


@router.post("/paper-sessions/{session_id}/match-local-pdfs")
def enqueue_paper_session_pdf_match(
    session_id: int,
    service: PdfLibraryService = Depends(get_pdf_library_service),
):
    try:
        service.enqueue_match_session_pdfs("paper_analysis", session_id)
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(url=f"/paper-sessions/{session_id}", status_code=303)


@router.post("/scholar-sessions/{session_id}/match-local-pdfs")
def enqueue_scholar_session_pdf_match(
    session_id: int,
    service: PdfLibraryService = Depends(get_pdf_library_service),
):
    try:
        service.enqueue_match_session_pdfs("scholar_analysis", session_id)
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}", status_code=303)
