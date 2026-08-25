"""Routes for scholar analysis MVP sessions."""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.scholar_analysis_service import (
    ScholarAnalysisService,
    get_scholar_analysis_service,
)
from app.services.task_service import DuplicateActiveTaskError
from app.providers.errors import ProviderException
from app.providers.implementations.dblp import (
    DblpAuthorNotFoundError,
    InvalidDblpPidError,
    is_dblp_pid,
)


router = APIRouter(prefix="/scholar-sessions", tags=["scholar-sessions"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/new", response_class=HTMLResponse)
def new_scholar_session(request: Request):
    return _render_new_session(request)


@router.post("/author-search", response_class=HTMLResponse)
def search_scholar_authors(
    request: Request,
    author_query: str = Form(...),
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    query = (author_query or "").strip()
    if not query:
        return _render_new_session(
            request,
            author_query=query,
            error_message="请输入学者英文全名或 DBLP PID。",
        )
    if not service.uses_dblp_author_provider:
        return _create_or_render_error(
            request,
            service,
            author_ref=query,
        )
    if service.uses_dblp_author_provider and is_dblp_pid(query):
        return _create_or_render_error(
            request,
            service,
            author_ref=query,
        )
    try:
        candidates = service.search_authors(query, limit=10)
    except ProviderException:
        logger.warning("DBLP author search failed", exc_info=True)
        return _render_new_session(
            request,
            author_query=query,
            error_message="DBLP 当前暂时不可用，请稍后重试。",
        )
    if not candidates:
        return _render_new_session(
            request,
            author_query=query,
            error_message="未找到匹配作者，请尝试英文全名或直接输入 DBLP PID。",
        )
    return _render_new_session(
        request,
        author_query=query,
        candidates=candidates,
        info_message=(
            "找到多个同名作者，请选择正确的 DBLP 记录。"
            if len(candidates) > 1
            else "请确认作者信息后创建会话。"
        ),
    )


@router.post("")
def create_scholar_session(
    request: Request,
    author_ref: Optional[str] = Form(None),
    dblp_pid: Optional[str] = Form(None),
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    selected_pid = (dblp_pid or "").strip()
    raw_author_ref = (author_ref or "").strip()
    if selected_pid:
        return _create_or_render_error(
            request,
            service,
            dblp_pid=selected_pid,
            author_query=raw_author_ref,
        )
    if service.uses_dblp_author_provider and not is_dblp_pid(raw_author_ref):
        return search_scholar_authors(
            request=request,
            author_query=raw_author_ref,
            service=service,
        )
    return _create_or_render_error(
        request,
        service,
        author_ref=raw_author_ref,
    )


def _create_or_render_error(
    request: Request,
    service: ScholarAnalysisService,
    *,
    author_ref: str = "",
    dblp_pid: Optional[str] = None,
    author_query: str = "",
):
    try:
        session = service.create_scholar_session(
            author_ref,
            dblp_pid=dblp_pid,
        )
    except InvalidDblpPidError:
        return _render_new_session(
            request,
            author_query=author_query or author_ref or dblp_pid or "",
            error_message="DBLP PID 格式无效，请重新搜索并选择作者。",
        )
    except DblpAuthorNotFoundError:
        return _render_new_session(
            request,
            author_query=author_query or author_ref or dblp_pid or "",
            error_message="未找到该 DBLP 作者记录，请重新搜索。",
        )
    except ProviderException:
        logger.warning("DBLP author resolution failed", exc_info=True)
        return _render_new_session(
            request,
            author_query=author_query or author_ref or dblp_pid or "",
            error_message="DBLP 当前暂时不可用，请稍后重试。",
        )
    return RedirectResponse(
        url=f"/scholar-sessions/{session.id}",
        status_code=303,
    )


def _render_new_session(
    request: Request,
    *,
    author_query: str = "",
    candidates=None,
    error_message: str = "",
    info_message: str = "",
):
    return templates.TemplateResponse(
        request,
        "scholar_sessions/new.html",
        {
            "author_query": author_query,
            "candidates": candidates or [],
            "error_message": error_message,
            "info_message": info_message,
        },
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


@router.post("/{session_id}/refresh-dblp-publications")
def refresh_dblp_publications(
    session_id: int,
    service: ScholarAnalysisService = Depends(get_scholar_analysis_service),
):
    try:
        session = service.refresh_dblp_publications(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProviderException:
        logger.warning("DBLP publication sync failed", exc_info=True)
        return RedirectResponse(
            url=(
                f"/scholar-sessions/{session_id}"
                "?dblp_sync=unavailable"
            ),
            status_code=303,
        )
    sync_status = "success" if session.publication_count else "no_results"
    return RedirectResponse(
        url=f"/scholar-sessions/{session_id}?dblp_sync={sync_status}",
        status_code=303,
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
