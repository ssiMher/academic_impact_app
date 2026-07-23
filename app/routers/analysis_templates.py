"""Routes for scholar analysis templates."""

from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.template_service import TemplateService, get_template_service


router = APIRouter(prefix="/scholar-sessions", tags=["analysis-templates"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _parse_keywords(raw_keywords: str) -> List[str]:
    return [
        keyword.strip()
        for keyword in raw_keywords.replace("\n", ",").split(",")
        if keyword.strip()
    ]


@router.get("/{session_id}/templates", response_class=HTMLResponse)
def templates_page(
    request: Request,
    session_id: int,
    service: TemplateService = Depends(get_template_service),
):
    return templates.TemplateResponse(
        request,
        "scholar_sessions/templates.html",
        {
            "session_id": session_id,
            "builtin_templates": service.list_builtin_templates(),
            "active_templates": service.get_active_templates(session_id),
        },
    )


@router.post("/{session_id}/templates/enable")
def enable_template(
    session_id: int,
    template_id: int = Form(...),
    service: TemplateService = Depends(get_template_service),
):
    try:
        service.enable_template(session_id=session_id, template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/templates", status_code=303)


@router.post("/{session_id}/templates/disable")
def disable_template(
    session_id: int,
    template_id: int = Form(...),
    service: TemplateService = Depends(get_template_service),
):
    try:
        service.disable_template(session_id=session_id, template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/templates", status_code=303)


@router.post("/{session_id}/templates/custom")
def create_custom_template(
    session_id: int,
    template_name: str = Form(""),
    natural_language_goal: str = Form(...),
    template_type: str = Form("custom"),
    positive_keywords: str = Form(""),
    negative_keywords: str = Form(""),
    required_patterns: str = Form(""),
    allowed_evidence_types: str = Form(""),
    strict_rules: str = Form(""),
    instruction_text: str = Form(""),
    min_citation_chars: int = Form(0),
    min_citation_words: int = Form(0),
    require_target_marker: bool = Form(False),
    allow_grouped_citation: bool = Form(False),
    auto_include_in_report: bool = Form(False),
    service: TemplateService = Depends(get_template_service),
):
    service.create_custom_template(
        session_id=session_id,
        template_name=template_name or None,
        natural_language_goal=natural_language_goal,
        template_type=template_type,
        positive_keywords=_parse_keywords(positive_keywords),
        negative_keywords=_parse_keywords(negative_keywords),
        required_patterns=_parse_keywords(required_patterns),
        allowed_evidence_types=_parse_keywords(allowed_evidence_types),
        strict_rules=_parse_keywords(strict_rules),
        instruction_text=instruction_text,
        min_citation_chars=min_citation_chars,
        min_citation_words=min_citation_words,
        require_target_marker=require_target_marker,
        allow_grouped_citation=allow_grouped_citation,
        auto_include_in_report=auto_include_in_report,
    )
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/templates", status_code=303)


@router.post("/{session_id}/templates/reapply")
def reapply_templates(
    session_id: int,
    service: TemplateService = Depends(get_template_service),
):
    service.reapply_templates_to_session(session_id)
    return RedirectResponse(url=f"/scholar-sessions/{session_id}/templates", status_code=303)


@router.get("/{session_id}/templates/{template_id}", response_class=HTMLResponse)
def template_detail_page(
    request: Request,
    session_id: int,
    template_id: int,
    service: TemplateService = Depends(get_template_service),
):
    try:
        template = service.get_template(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return templates.TemplateResponse(
        request,
        "scholar_sessions/template_detail.html",
        {
            "session_id": session_id,
            "template": template,
        },
    )
