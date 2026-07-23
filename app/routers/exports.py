"""Routes for paper analysis report exports."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.services.export_service import ExportService, get_export_service
from app.services.report_service import ReportNotFoundError


router = APIRouter(prefix="/paper-sessions", tags=["exports"])


@router.get("/{session_id}/exports/report.md")
def download_report_markdown(
    session_id: int,
    service: ExportService = Depends(get_export_service),
):
    try:
        export_path = service.write_report_markdown(session_id)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return FileResponse(
        export_path,
        media_type="text/markdown; charset=utf-8",
        filename="report.md",
    )


@router.get("/{session_id}/exports/structured.json")
def download_structured_json(
    session_id: int,
    service: ExportService = Depends(get_export_service),
):
    try:
        export_path = service.write_structured_json(session_id)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return FileResponse(
        export_path,
        media_type="application/json",
        filename="structured.json",
    )
