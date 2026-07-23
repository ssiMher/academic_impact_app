"""Routes for citing paper PDF uploads."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.pdf.security import PdfValidationError
from app.services.pdf_service import (
    CitingPaperNotFoundError,
    PdfService,
    get_pdf_service,
)
from app.services.task_service import (
    DuplicateActiveTaskError,
    TaskService,
    get_task_service,
)


router = APIRouter(tags=["uploads"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


@router.get("/citing-papers/{citing_paper_id}", response_class=HTMLResponse)
def citing_paper_detail(
    request: Request,
    citing_paper_id: int,
    service: PdfService = Depends(get_pdf_service),
):
    citing_paper = service.get_citing_paper(citing_paper_id)
    if citing_paper is None:
        raise HTTPException(status_code=404, detail="Citing paper not found")

    pdf_asset = service.get_pdf_asset_for_citing_paper(citing_paper)
    strong_evidence = service.get_strong_evidence_for_citing_paper(citing_paper_id)
    analysis_readiness = service.get_analysis_readiness(citing_paper)
    return templates.TemplateResponse(
        request,
        "citing_papers/detail.html",
        {
            "citing_paper": citing_paper,
            "pdf_asset": pdf_asset,
            "strong_evidence": strong_evidence,
            "analysis_readiness": analysis_readiness,
        },
    )


@router.post("/citing-papers/{citing_paper_id}/pdf")
async def upload_citing_paper_pdf(
    citing_paper_id: int,
    file: UploadFile = File(...),
    service: PdfService = Depends(get_pdf_service),
):
    content = await file.read()
    try:
        service.upload_pdf_for_citing_paper(
            citing_paper_id=citing_paper_id,
            filename=file.filename or "",
            content=content,
            mime_type=file.content_type or "application/pdf",
        )
    except CitingPaperNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PdfValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return RedirectResponse(
        url=f"/citing-papers/{citing_paper_id}",
        status_code=303,
    )


@router.post("/citing-papers/{citing_paper_id}/analyze")
def enqueue_citing_paper_analysis(
    citing_paper_id: int,
    pdf_service: PdfService = Depends(get_pdf_service),
    task_service: TaskService = Depends(get_task_service),
):
    citing_paper = pdf_service.get_citing_paper(citing_paper_id)
    if citing_paper is None:
        raise HTTPException(status_code=404, detail="Citing paper not found")

    readiness = pdf_service.get_analysis_readiness(citing_paper)
    if readiness != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=readiness,
        )

    try:
        task_service.enqueue(
            session_kind="citing_paper",
            session_id=citing_paper_id,
            task_type="analyze_citation",
        )
    except DuplicateActiveTaskError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return RedirectResponse(
        url=f"/citing-papers/{citing_paper_id}",
        status_code=303,
    )
