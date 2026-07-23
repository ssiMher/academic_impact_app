"""Routes for scholar highlight cards and exports."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.highlight_card_service import (
    HighlightCardService,
    PptxExportError,
    get_highlight_card_service,
)
from app.services.scholar_report_service import (
    ScholarReportNotFoundError,
    ScholarReportService,
    get_scholar_report_service,
)


router = APIRouter(prefix="/scholar-sessions", tags=["highlight-cards"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/{session_id}/cards", response_class=HTMLResponse)
def cards_page(
    request: Request,
    session_id: int,
    card_type: Optional[str] = None,
    view: str = "all",
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    return templates.TemplateResponse(
        request,
        "scholar_sessions/cards.html",
        {
            "session_id": session_id,
            "card_type": card_type or "",
            "view": view,
            "cards": service.list_cards(session_id, card_type=card_type, view=view),
            "workspace_rows": service.list_report_workspace_cards(session_id, card_type=card_type, view=view),
            "workspace_stats": service.report_workspace_stats(session_id),
        },
    )


@router.get("/{session_id}/report-workspace", response_class=HTMLResponse)
def report_workspace_page(
    request: Request,
    session_id: int,
    card_type: Optional[str] = None,
    view: str = "all",
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    formal_report_view = (
        service.build_formal_report_view(session_id)
        if view == "all" and not card_type and service.has_template_direct_results(session_id)
        else None
    )
    return templates.TemplateResponse(
        request,
        "scholar_sessions/cards.html",
        {
            "session_id": session_id,
            "card_type": card_type or "",
            "view": view,
            "cards": service.list_cards(session_id, card_type=card_type, view=view),
            "workspace_rows": service.list_report_workspace_cards(session_id, card_type=card_type, view=view),
            "workspace_stats": service.report_workspace_stats(session_id),
            "report_workspace": True,
            "formal_report_markdown": formal_report_view["markdown"] if formal_report_view else "",
            "formal_report_view": formal_report_view,
        },
    )


@router.post("/{session_id}/cards/generate")
def generate_cards(
    session_id: int,
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    service.generate_cards_from_evidence(session_id)
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/cards", status_code=303)


@router.post("/{session_id}/evidence/{evidence_id}/generate-card")
def generate_card_from_evidence(
    session_id: int,
    evidence_id: int,
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    try:
        service.generate_card_from_evidence(session_id, evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}/report-workspace",
        status_code=303,
    )


@router.post("/{session_id}/cards/{card_id}/edit")
def edit_card(
    session_id: int,
    card_id: int,
    title: str = Form(...),
    subtitle: str = Form(""),
    narrative_zh: str = Form(""),
    body_markdown: str = Form(...),
    user_note: str = Form(""),
    include_in_report: bool = Form(False),
    notable_author_name: str = Form(""),
    notable_author_affiliation: str = Form(""),
    notable_author_role: str = Form(""),
    fellow_status: str = Form("unknown"),
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    try:
        service.update_card(
            card_id,
            title=title,
            subtitle=subtitle or None,
            narrative_zh=narrative_zh or None,
            body_markdown=body_markdown,
            user_note=user_note,
            include_in_report=include_in_report,
            notable_author_name=notable_author_name or None,
            notable_author_affiliation=notable_author_affiliation or None,
            notable_author_role=notable_author_role or None,
            fellow_status=fellow_status or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/report-workspace", status_code=303)


@router.get("/{session_id}/exports/report.md")
def download_scholar_report_markdown(
    session_id: int,
    service: ScholarReportService = Depends(get_scholar_report_service),
):
    try:
        path = service.write_report_markdown(session_id)
    except ScholarReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename="report.md")


@router.get("/{session_id}/exports/structured.json")
def download_scholar_structured_json(
    session_id: int,
    service: ScholarReportService = Depends(get_scholar_report_service),
):
    try:
        path = service.write_structured_json(session_id)
    except ScholarReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type="application/json", filename="structured.json")


@router.get("/{session_id}/exports/highlight_cards.csv")
def download_highlight_cards_csv(
    session_id: int,
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    path = service.write_cards_csv(session_id)
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename="highlight_cards.csv")


@router.get("/{session_id}/exports/highlight_cards.md")
def download_highlight_cards_markdown(
    session_id: int,
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    path = service.write_cards_markdown(session_id)
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename="highlight_cards.md",
    )


@router.get("/{session_id}/exports/report.pptx")
def download_scholar_report_pptx(
    session_id: int,
    request: Request,
    service: HighlightCardService = Depends(get_highlight_card_service),
):
    try:
        path = service.export_pptx(session_id)
    except PptxExportError as exc:
        return templates.TemplateResponse(
            request,
            "scholar_sessions/pptx_export_error.html",
            {
                "session_id": session_id,
                "error_message": str(exc),
            },
            status_code=500,
        )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="report.pptx",
    )
