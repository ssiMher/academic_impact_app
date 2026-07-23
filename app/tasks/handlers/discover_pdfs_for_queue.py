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
    task.stage = "discovering_pdfs"
    db.flush()
    for index, item in enumerate(items, start=1):
        if item.queue_status not in {"selected", "pending"}:
            counts["skipped"] += 1
            counts["skipped_ineligible"] += 1
            task.progress_current = index
            continue
        try:
            result = service.download_pdf_for_queue_item(
                item.id,
                allow_restricted_browser=True,
            )
        except Exception as exc:
            result = None
            counts["failed"] += 1
            failures.append(_failure(item, f"{type(exc).__name__}: {exc}"))
            task.progress_current = index
            db.rollback()
            task = db.merge(task)
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
        db.commit()
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
    payload["result_summary"] = summary
    task.payload_json = json.dumps(payload, ensure_ascii=False)
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
    return {
        "queue_item_id": item.id,
        "citing_paper_title": (item.citing_paper_title or "")[:240],
        "reason": reason[:500],
    }
