"""Routes for importing external citation lists."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ExternalCitationImportBatch
from app.services.external_citation_import_service import ExternalCitationImportService


router = APIRouter(tags=["external-citations"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/{session_kind_path}/{session_id}/external-citations/import", response_class=HTMLResponse)
def external_citation_import_page(
    request: Request,
    session_kind_path: str,
    session_id: int,
    batch_id: int = 0,
    db: Session = Depends(get_db),
):
    session_kind = _session_kind(session_kind_path)
    service = ExternalCitationImportService(db)
    batch = db.get(ExternalCitationImportBatch, batch_id) if batch_id else None
    rows = service.rows_for_batch(batch.id) if batch else []
    return templates.TemplateResponse(
        request,
        "external_citations/import.html",
        {
            "session_kind_path": session_kind_path,
            "session_kind": session_kind,
            "session_id": session_id,
            "batch": batch,
            "rows": rows,
        },
    )


@router.post("/{session_kind_path}/{session_id}/external-citations/import", response_class=HTMLResponse)
async def import_external_citations(
    request: Request,
    session_kind_path: str,
    session_id: int,
    source_name: str = Form("google_scholar_import"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    session_kind = _session_kind(session_kind_path)
    content = await file.read()
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="当前 MVP 仅支持 CSV。BibTeX / RIS 将在后续阶段支持。")
    batch = ExternalCitationImportService(db).import_csv(
        session_kind=session_kind,
        session_id=session_id,
        content=content,
        filename=file.filename or "external-citations.csv",
        source_name=source_name,
    )
    rows = ExternalCitationImportService(db).rows_for_batch(batch.id)
    return templates.TemplateResponse(
        request,
        "external_citations/import.html",
        {
            "session_kind_path": session_kind_path,
            "session_kind": session_kind,
            "session_id": session_id,
            "batch": batch,
            "rows": rows,
        },
    )


def _session_kind(path_value: str) -> str:
    if path_value == "scholar-sessions":
        return "scholar_analysis"
    if path_value == "paper-sessions":
        return "paper_analysis"
    raise HTTPException(status_code=404, detail="Unsupported session kind")
