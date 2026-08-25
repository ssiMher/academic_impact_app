"""Routes for scholar full-text evidence analysis."""

from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.scholar_fulltext_service import (
    ScholarFulltextService,
    get_scholar_fulltext_service,
)
from app.services.highlight_card_service import HighlightCardService
from app.services.task_service import DuplicateActiveTaskError


router = APIRouter(prefix="/scholar-sessions", tags=["scholar-evidence"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.post("/{session_id}/queue/analyze")
def enqueue_analyze_scholar_queue(
    session_id: int,
    item_ids: List[int] = Form([]),
    analysis_scope: str = Form("fulltext_template_direct"),
    service: ScholarFulltextService = Depends(get_scholar_fulltext_service),
):
    try:
        task = service.enqueue_analyze_queue(
            session_id=session_id,
            queue_item_ids=item_ids,
            analysis_scope=analysis_scope,
        )
    except DuplicateActiveTaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(
        url=(
            f"/scholar-sessions/{session_id}/queue"
            f"?view=selected&analyze_task_id={task.id}"
        ),
        status_code=303,
    )


@router.get("/{session_id}/evidence", response_class=HTMLResponse)
def scholar_evidence_page(
    request: Request,
    session_id: int,
    view: str = "all",
    mode: str = "formal",
    service: ScholarFulltextService = Depends(get_scholar_fulltext_service),
):
    mode = "debug" if mode == "debug" else "formal"
    evidence_items = service.list_scholar_evidence(
        session_id,
        filters={
            "view": view,
            "latest_only": mode != "debug",
        },
    )
    formal_evidence_view = HighlightCardService(service.db).build_formal_evidence_view(
        evidence_items
    )
    summary = service.evidence_service.quality_summary(session_id)
    analysis_diagnostics = service.list_analysis_diagnostics(session_id)
    latest_successful_analysis = next(
        (
            diagnostic
            for diagnostic in analysis_diagnostics
            if diagnostic.get("status") == "succeeded"
        ),
        None,
    )
    pdf_summary = service.queue_pdf_summary(session_id)
    direct_candidate_layers = service.latest_direct_candidate_layers(session_id)
    return templates.TemplateResponse(
        request,
        "scholar_sessions/evidence.html",
        {
            "session_id": session_id,
            "view": view,
            "mode": mode,
            "evidence_items": evidence_items,
            "formal_evidence_view": formal_evidence_view,
            "summary": summary,
            "analysis_diagnostics": analysis_diagnostics,
            "latest_successful_analysis": latest_successful_analysis,
            "pdf_summary": pdf_summary,
            "direct_candidate_layers": direct_candidate_layers,
        },
    )


@router.get("/{session_id}/analysis-debug", response_class=HTMLResponse)
def scholar_analysis_debug_page(
    request: Request,
    session_id: int,
    service: ScholarFulltextService = Depends(get_scholar_fulltext_service),
):
    return templates.TemplateResponse(
        request,
        "scholar_sessions/analysis_debug.html",
        {
            "session_id": session_id,
            "debug_rows": service.list_analysis_debug_rows(session_id, limit=10),
        },
    )


@router.get(
    "/{session_id}/analysis-debug/{result_id}/{kind}",
    response_class=PlainTextResponse,
)
def scholar_analysis_debug_artifact(
    session_id: int,
    result_id: int,
    kind: str,
    service: ScholarFulltextService = Depends(get_scholar_fulltext_service),
):
    try:
        artifact = service.read_debug_artifact(
            session_id=session_id,
            result_id=result_id,
            kind=kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PlainTextResponse(
        artifact["content"],
        media_type=str(artifact["media_type"]),
        headers={
            "Content-Disposition": f'inline; filename="{artifact["basename"]}"'
        },
    )


@router.post("/{session_id}/evidence/{evidence_id}/review")
def review_scholar_evidence(
    session_id: int,
    evidence_id: int,
    review_status: str = Form(...),
    user_note: str = Form(""),
    corrected_label: str = Form(""),
    service: ScholarFulltextService = Depends(get_scholar_fulltext_service),
):
    try:
        service.update_evidence_review(
            evidence_id,
            review_status,
            user_note,
            corrected_label or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}/evidence?mode=debug#evidence-{evidence_id}",
        status_code=303,
    )
