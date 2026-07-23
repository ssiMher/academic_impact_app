"""Discover/download PDFs for eligible scholar queue items."""

import json
from sqlalchemy.orm import Session

from app.models import AnalysisTask, DeepAnalysisQueueItem
from app.services.queue_pdf_download_service import QueuePdfDownloadService


def handle_discover_pdfs_for_queue(db: Session, task: AnalysisTask) -> None:
    items = (
        db.query(DeepAnalysisQueueItem)
        .filter_by(scholar_session_id=task.session_id)
        .order_by(DeepAnalysisQueueItem.id.asc())
        .all()
    )
    service = QueuePdfDownloadService(db)
    total = len(items)
    counts = {
        "downloaded": 0,
        "open_access_downloaded": 0,
        "ieee_downloaded": 0,
        "requires_login": 0,
        "no_pdf_found": 0,
        "failed": 0,
        "skipped": 0,
        "skipped_existing_pdf": 0,
        "skipped_ineligible": 0,
    }
    failures = []
    task.progress_total = total
    task.progress_current = 0
    task.stage = "downloading_pdfs"
    task.stage_message = "正在准备批量 PDF 下载"
    _save_progress(db, task, counts)
    for index, item in enumerate(items, start=1):
        item_id = item.id
        item_title = (item.citing_paper_title or f"Queue item {item.id}")[:120]
        task.progress_current = index - 1
        task.progress_total = total
        task.stage = "downloading_pdfs"
        task.stage_message = f"正在处理 {index}/{total}：{item_title}"
        _save_progress(db, task, counts)

        if item.queue_status not in {"selected", "pending"}:
            counts["skipped"] += 1
            counts["skipped_ineligible"] += 1
            task.progress_current = index
            task.stage_message = (
                f"已处理 {index}/{total}：{item_title}；结果=skipped_ineligible"
            )
            _save_progress(db, task, counts)
            continue
        try:
            result = service.download_pdf_for_queue_item(
                item_id,
                allow_restricted_browser=True,
            )
        except Exception as exc:
            counts["failed"] += 1
            failure_reason = f"{type(exc).__name__}: {exc}"
            failures.append(_failure_values(item_id, item_title, failure_reason))
            db.rollback()
            task = db.get(AnalysisTask, task.id)
            task.progress_current = index
            task.progress_total = total
            task.stage = "downloading_pdfs"
            task.stage_message = (
                f"已处理 {index}/{total}：{item_title}；结果=failed"
            )
            _save_progress(db, task, counts)
            continue
        status = result.status
        if status == "downloaded":
            counts["downloaded"] += 1
            if result.source == "ieee_browser_helper":
                counts["ieee_downloaded"] += 1
            else:
                counts["open_access_downloaded"] += 1
        elif status == "skipped_existing_pdf":
            counts["skipped"] += 1
            counts["skipped_existing_pdf"] += 1
        elif status == "requires_login":
            counts["requires_login"] += 1
            failures.append(_failure(item, result.reason or "requires_login"))
        elif status == "no_pdf_found":
            counts["no_pdf_found"] += 1
            failures.append(_failure(item, result.reason or "no_pdf_found"))
        else:
            counts["failed"] += 1
            failures.append(_failure(item, result.reason or status))
        task.progress_current = index
        task.stage_message = f"已处理 {index}/{total}：{item_title}；结果={status}"
        _save_progress(db, task, counts)
    summary = {
        "total_items": total,
        **counts,
        "found_open_access": counts["open_access_downloaded"],
        "manual_upload_required": (
            counts["requires_login"] + counts["no_pdf_found"] + counts["failed"]
        ),
        "failure_count": len(failures),
        "failures": failures,
    }
    payload = _payload(task)
    payload["progress_summary"] = dict(counts)
    payload["result_summary"] = summary
    task.payload_json = json.dumps(payload, ensure_ascii=False)
    task.progress_current = total
    task.progress_total = total
    task.stage_message = (
        f"total_items={total}; "
        f"downloaded={counts['downloaded']}; "
        f"open_access_downloaded={counts['open_access_downloaded']}; "
        f"found_open_access={counts['open_access_downloaded']}; "
        f"ieee_downloaded={counts['ieee_downloaded']}; "
        f"requires_login={counts['requires_login']}; "
        f"no_pdf_found={counts['no_pdf_found']}; "
        f"failed={counts['failed']}; "
        f"skipped={counts['skipped']}; "
        f"skipped_existing_pdf={counts['skipped_existing_pdf']}; "
        f"failure_count={len(failures)}"
    )
    db.commit()


def _payload(task: AnalysisTask) -> dict:
    try:
        payload = json.loads(task.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _failure(item: DeepAnalysisQueueItem, reason: str) -> dict:
    return _failure_values(item.id, item.citing_paper_title or "", reason)


def _failure_values(item_id: int, item_title: str, reason: str) -> dict:
    return {
        "queue_item_id": item_id,
        "citing_paper_title": item_title[:240],
        "reason": reason[:500],
    }


def _save_progress(
    db: Session,
    task: AnalysisTask,
    counts: dict,
) -> None:
    payload = _payload(task)
    payload["progress_summary"] = dict(counts)
    task.payload_json = json.dumps(payload, ensure_ascii=False)
    db.commit()
