"""Scan the manual-download PDF inbox."""

from sqlalchemy.orm import Session

from app.models import AnalysisTask
from app.services.pdf_inbox_service import get_pdf_inbox_service


def handle_scan_pdf_inbox(db: Session, task: AnalysisTask) -> None:
    service = get_pdf_inbox_service(db)
    task.stage = "scanning_pdf_inbox"
    task.progress_total = 1
    task.progress_current = 0
    db.flush()
    summary = service.scan_inbox()
    task.progress_current = 1
    task.stage_message = (
        f"scanned={summary.scanned_count}; "
        f"created_assets={summary.created_asset_count}; "
        f"auto_bound={summary.auto_bound_count}; "
        f"manual_confirmation={summary.manual_confirmation_count}; "
        f"duplicates={summary.duplicate_count}; "
        f"failed={summary.failed_count}"
    )
    db.commit()
