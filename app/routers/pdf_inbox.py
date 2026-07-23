"""Routes for the manual browser-download PDF inbox."""

import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services.pdf_inbox_service import PdfInboxService, get_pdf_inbox_service
from app.services.task_service import DuplicateActiveTaskError


router = APIRouter(tags=["pdf-inbox"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/pdf-inbox", response_class=HTMLResponse)
def pdf_inbox_page(
    request: Request,
    service: PdfInboxService = Depends(get_pdf_inbox_service),
):
    return templates.TemplateResponse(
        request,
        "pdf_inbox/index.html",
        {
            "entries": service.list_entries(),
            "inbox_dir": service.inbox_dir.name,
            "match_threshold": service.match_threshold,
        },
    )


@router.post("/pdf-inbox/rescan")
def enqueue_pdf_inbox_scan(
    service: PdfInboxService = Depends(get_pdf_inbox_service),
):
    try:
        service.enqueue_scan()
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(url="/pdf-inbox", status_code=303)


@router.post("/pdf-inbox/scan-now")
def scan_pdf_inbox_now(
    service: PdfInboxService = Depends(get_pdf_inbox_service),
):
    service.scan_inbox()
    return RedirectResponse(url="/pdf-inbox", status_code=303)


@router.post("/pdf-inbox/{entry_id}/bind")
def bind_pdf_inbox_entry(
    entry_id: int,
    queue_item_id: int = Form(...),
    service: PdfInboxService = Depends(get_pdf_inbox_service),
):
    try:
        service.bind_entry_to_queue_item(entry_id=entry_id, queue_item_id=queue_item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url="/pdf-inbox", status_code=303)


@router.post("/pdf-inbox/{entry_id}/ignore")
def ignore_pdf_inbox_entry(
    entry_id: int,
    service: PdfInboxService = Depends(get_pdf_inbox_service),
):
    try:
        service.ignore_entry(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url="/pdf-inbox", status_code=303)


@router.get("/scholar-sessions/{session_id}/exports/missing_pdfs_download_list.csv")
def download_missing_pdf_list(
    session_id: int,
    service: PdfInboxService = Depends(get_pdf_inbox_service),
):
    rows = service.missing_pdfs_download_rows(session_id)
    buffer = io.StringIO()
    fieldnames = [
        "queue_item_id",
        "citing_paper_title",
        "cited_paper_title",
        "doi",
        "publisher",
        "year",
        "venue",
        "doi_url",
        "publisher_url",
        "google_scholar_query_url",
        "status",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=missing_pdfs_download_list.csv"
        },
    )
