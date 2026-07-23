"""Task handler for matching a session against the local PDF library index."""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AnalysisTask
from app.pdf.library import parse_library_dirs
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_library_service import PdfLibraryService


def handle_match_session_pdfs(db: Session, task: AnalysisTask) -> None:
    if task.session_kind not in {"paper_analysis", "scholar_analysis"}:
        raise ValueError("match_session_pdfs supports paper_analysis or scholar_analysis")

    service = PdfLibraryService(
        repository=PdfRepository(db),
        library_dirs=parse_library_dirs(settings.pdf_library_dirs),
        index_path=settings.pdf_index_path,
        max_scan_files=settings.pdf_max_scan_files,
        match_threshold=settings.pdf_match_threshold,
    )

    total = len(service.repository.list_citing_papers_for_session(task.session_id))
    if task.session_kind == "scholar_analysis":
        total = len(service.repository.list_scholar_publications_for_session(task.session_id))
    task.progress_total = total
    task.progress_current = 0
    task.stage = "matching_local_pdfs"
    task.stage_message = "Matching session publications against local PDF library."
    db.flush()

    matched_count = service.match_session_pdfs(task.session_kind, task.session_id)
    task.progress_current = total
    task.stage_message = f"Matched {matched_count} local PDFs."
    db.commit()
