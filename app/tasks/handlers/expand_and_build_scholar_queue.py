"""Combined task handler for scholar citation expansion followed by queue build."""

from sqlalchemy.orm import Session

from app.models import AnalysisTask
from app.models.constants import SCHOLAR_ANALYSIS_SESSION_KIND
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.repositories.scholar_session_repo import ScholarSessionRepository
from app.tasks.handlers.build_scholar_queue import handle_build_scholar_queue
from app.tasks.handlers.expand_scholar_citations import handle_expand_scholar_citations


def handle_expand_and_build_scholar_queue(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != SCHOLAR_ANALYSIS_SESSION_KIND:
        raise ValueError(
            "expand_and_build_scholar_queue only supports scholar_analysis sessions"
        )

    scholar_repo = ScholarSessionRepository(db)
    queue_repo = ScholarQueueRepository(db)
    session = scholar_repo.get_by_id(task.session_id)
    if session is None:
        raise ValueError(f"ScholarAnalysisSession {task.session_id} was not found")

    task.stage = "expand_and_build_scholar_queue"
    task.stage_message = "阶段 1：扩展引用"
    db.flush()

    handle_expand_scholar_citations(db, task)
    expansion_stage_message = task.stage_message or ""

    citation_edges = queue_repo.list_citation_edges(task.session_id)
    citation_edge_count = len(citation_edges)
    provider_name = citation_edges[0].provider_name if citation_edges else "unknown"

    if citation_edge_count == 0:
        task.progress_total = 1
        task.progress_current = 1
        task.stage = "expand_finished_no_edges"
        task.stage_message = (
            "阶段 1：扩展引用完成；"
            "阶段 2：未开始；"
            "已扩展引用数=0；"
            "已生成队列条目数=0；"
            f"provider={provider_name}；"
            f"{expansion_stage_message}；"
            "自动复用PDF=否；"
            "没有扩展到引用，无法构建队列"
        )
        db.commit()
        return

    task.stage = "building_scholar_queue"
    task.stage_message = (
        "阶段 1：扩展引用完成；"
        "阶段 2：构建队列中"
    )
    db.flush()

    handle_build_scholar_queue(db, task)

    queue_count = len(queue_repo.list_queue_items(task.session_id))
    auto_reuse_count = sum(
        1
        for item in queue_repo.list_queue_items(task.session_id)
        if item.pdf_readiness_status in {"reused_pdf", "local_library_pdf"}
    )
    task.stage = "expand_and_build_finished"
    task.stage_message = (
        "阶段 1：扩展引用完成；"
        "阶段 2：构建队列完成；"
        f"已扩展引用数={citation_edge_count}；"
        f"已生成队列条目数={queue_count}；"
        f"provider={provider_name}；"
        f"{expansion_stage_message}；"
        f"自动复用PDF={'是' if auto_reuse_count > 0 else '否'}"
        f"（{auto_reuse_count}）"
    )
    db.commit()
