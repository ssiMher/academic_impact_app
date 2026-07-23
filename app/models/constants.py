"""Shared domain constants used across models, services, and tasks."""

from typing import Optional


SCHOLAR_ANALYSIS_SESSION_KIND = "scholar_analysis"

PDF_STATUS_MANUAL = "manual_pdf"
PDF_STATUS_REUSED = "reused_pdf"
PDF_STATUS_LOCAL_LIBRARY = "local_library_pdf"
PDF_STATUS_NEED = "need_pdf"

READY_PDF_STATUSES = {
    PDF_STATUS_MANUAL,
    PDF_STATUS_REUSED,
    PDF_STATUS_LOCAL_LIBRARY,
}


def is_pdf_ready_status(status: Optional[str]) -> bool:
    return status in READY_PDF_STATUSES
