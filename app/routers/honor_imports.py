"""Routes for importing notable citation author CSV files."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.session import get_db
from app.services.honor_csv_service import (
    HonorCsvImportError,
    HonorCsvImportService,
)


router = APIRouter(prefix="/scholar-sessions", tags=["honor-imports"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/{session_id}/import-honor-csv", response_class=HTMLResponse)
def import_honor_csv_page(request: Request, session_id: int, db=Depends(get_db)):
    service = HonorCsvImportService(db)
    annotations = service.current_annotations(session_id)
    return templates.TemplateResponse(
        request,
        "scholar_sessions/import_honor_csv.html",
        {
            "session_id": session_id,
            "annotations": annotations,
            "summary": None,
            "error_message": "",
        },
    )


@router.post("/{session_id}/import-honor-csv", response_class=HTMLResponse)
async def import_honor_csv_submit(
    request: Request,
    session_id: int,
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    service = HonorCsvImportService(db)
    try:
        summary = service.import_csv(session_id=session_id, content=await file.read())
        annotations = service.current_annotations(session_id)
        return templates.TemplateResponse(
            request,
            "scholar_sessions/import_honor_csv.html",
            {
                "session_id": session_id,
                "annotations": annotations,
                "summary": summary,
                "error_message": "",
            },
        )
    except HonorCsvImportError as exc:
        return templates.TemplateResponse(
            request,
            "scholar_sessions/import_honor_csv.html",
            {
                "session_id": session_id,
                "annotations": service.current_annotations(session_id),
                "summary": None,
                "error_message": str(exc),
            },
            status_code=400,
        )


@router.post("/{session_id}/import-honor-csv/rematch", response_class=HTMLResponse)
def rematch_honor_csv_submit(
    request: Request,
    session_id: int,
    db=Depends(get_db),
):
    service = HonorCsvImportService(db)
    try:
        summary = service.rematch_existing_annotations(session_id)
        annotations = service.current_annotations(session_id)
        return templates.TemplateResponse(
            request,
            "scholar_sessions/import_honor_csv.html",
            {
                "session_id": session_id,
                "annotations": annotations,
                "summary": summary,
                "error_message": "",
            },
        )
    except HonorCsvImportError as exc:
        return templates.TemplateResponse(
            request,
            "scholar_sessions/import_honor_csv.html",
            {
                "session_id": session_id,
                "annotations": service.current_annotations(session_id),
                "summary": None,
                "error_message": str(exc),
            },
            status_code=400,
        )
