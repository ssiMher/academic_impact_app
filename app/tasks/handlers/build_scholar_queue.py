"""Task handler for building scholar deep analysis queue items."""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AnalysisTask
from app.pdf.library import parse_library_dirs
from app.repositories.pdf_repo import PdfRepository
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.services.pdf_library_service import PdfLibraryService
from app.services.scholar_queue_service import ScholarQueueService


def handle_build_scholar_queue(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != "scholar_analysis":
        raise ValueError("build_scholar_queue only supports scholar_analysis sessions")

    service = ScholarQueueService(
        repository=ScholarQueueRepository(db),
        pdf_library_service=PdfLibraryService(
            repository=PdfRepository(db),
            library_dirs=parse_library_dirs(settings.pdf_library_dirs),
            index_path=settings.pdf_index_path,
            max_scan_files=settings.pdf_max_scan_files,
            match_threshold=settings.pdf_match_threshold,
        ),
    )
    task.stage = "building_scholar_queue"
    task.stage_message = "Building scholar deep analysis queue."
    task.progress_total = len(service.repository.list_citation_edges(task.session_id))
    task.progress_current = 0
    db.flush()
    service.build_queue(task.session_id)
    task.progress_current = task.progress_total
    db.commit()
