"""Task handler for rebuilding the configured local PDF library index."""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AnalysisTask
from app.pdf.library import parse_library_dirs
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_library_service import PdfLibraryService


def handle_rebuild_pdf_index(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != "pdf_library":
        raise ValueError("rebuild_pdf_index only supports pdf_library tasks")

    service = PdfLibraryService(
        repository=PdfRepository(db),
        library_dirs=parse_library_dirs(settings.pdf_library_dirs),
        index_path=settings.pdf_index_path,
        max_scan_files=settings.pdf_max_scan_files,
        match_threshold=settings.pdf_match_threshold,
    )
    index = service.rebuild_index(task=task)
    if index.status != "succeeded":
        raise ValueError(index.error_message or "PDF library index rebuild failed")
