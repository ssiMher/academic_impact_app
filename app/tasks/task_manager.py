"""Task handler registry."""

from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.models import AnalysisTask
from app.tasks.handlers.analyze_citation import handle_analyze_citation
from app.tasks.handlers.analyze_scholar_queue import handle_analyze_scholar_queue
from app.tasks.handlers.build_scholar_queue import handle_build_scholar_queue
from app.tasks.handlers.discover_paper import handle_discover_paper
from app.tasks.handlers.discover_pdfs_for_queue import handle_discover_pdfs_for_queue
from app.tasks.handlers.download_ieee_pdf import handle_download_ieee_pdf
from app.tasks.handlers.expand_and_build_scholar_queue import (
    handle_expand_and_build_scholar_queue,
)
from app.tasks.handlers.expand_scholar_citations import handle_expand_scholar_citations
from app.tasks.handlers.match_session_pdfs import handle_match_session_pdfs
from app.tasks.handlers.rebuild_pdf_index import handle_rebuild_pdf_index
from app.tasks.handlers.rejudge_template_direct_evidences import (
    handle_rejudge_template_direct_evidences,
)
from app.tasks.handlers.scan_pdf_inbox import handle_scan_pdf_inbox


TaskHandler = Callable[[Session, AnalysisTask], None]


class TaskManager:
    def __init__(self, handlers: Optional[Dict[str, TaskHandler]] = None) -> None:
        self.handlers = handlers or {
            "discover_paper": handle_discover_paper,
            "analyze_citation": handle_analyze_citation,
            "expand_scholar_citations": handle_expand_scholar_citations,
            "expand_and_build_scholar_queue": handle_expand_and_build_scholar_queue,
            "rebuild_pdf_index": handle_rebuild_pdf_index,
            "match_session_pdfs": handle_match_session_pdfs,
            "build_scholar_queue": handle_build_scholar_queue,
            "analyze_scholar_queue": handle_analyze_scholar_queue,
            "rejudge_template_direct_evidences": (
                handle_rejudge_template_direct_evidences
            ),
            "discover_pdfs_for_queue": handle_discover_pdfs_for_queue,
            "download_open_access_pdfs": handle_discover_pdfs_for_queue,
            "download_ieee_pdf": handle_download_ieee_pdf,
            "scan_pdf_inbox": handle_scan_pdf_inbox,
        }

    def run(self, db: Session, task: AnalysisTask) -> None:
        handler = self.handlers.get(task.task_type)
        if handler is None:
            raise ValueError(f"No handler registered for task type: {task.task_type}")
        handler(db, task)
