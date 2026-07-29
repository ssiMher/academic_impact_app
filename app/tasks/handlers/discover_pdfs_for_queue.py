"""Discover PDFs, then pause/resume the IEEE stage around user authentication."""

from __future__ import annotations

from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.models import AnalysisTask, DeepAnalysisQueueItem, Publication
from app.pdf.publisher import classify_publisher_from_doi_or_url
from app.services.ieee_session_service import IeeeSessionService
from app.services.queue_pdf_download_service import (
    PdfDownloadResult,
    QueuePdfDownloadService,
)


COUNT_KEYS = (
    "downloaded",
    "open_access_downloaded",
    "ieee_downloaded",
    "requires_login",
    "no_pdf_found",
    "failed",
    "skipped",
    "skipped_existing_pdf",
    "skipped_ineligible",
    "challenge_blocked_count",
    "resumed_count",
)


def handle_discover_pdfs_for_queue(db: Session, task: AnalysisTask) -> None:
    items = (
        db.query(DeepAnalysisQueueItem)
        .filter_by(scholar_session_id=task.session_id)
        .order_by(DeepAnalysisQueueItem.id.asc())
        .all()
    )
    by_id = {item.id: item for item in items}
    service = QueuePdfDownloadService(db)
    session_service = IeeeSessionService()
    payload = _payload(task)
    counts = _counts(payload.get("progress_summary"))
    failures = list(payload.get("working_failures") or [])
    pending_ieee_ids = [
        int(value)
        for value in payload.get("pending_ieee_item_ids") or []
        if int(value) in by_id
    ]
    total = len(items)
    task.progress_total = total
    task.stage = "discovering_open_pdfs"

    if not payload.get("discovery_completed"):
        pending_ieee_ids = []
        counts = _counts()
        failures = []
        task.progress_current = 0
        task.stage_message = "正在准备开放 PDF 发现"
        _save_progress(db, task, counts, failures, pending_ieee_ids)
        for index, item in enumerate(items, start=1):
            title = _title(item)
            task.stage_message = f"正在处理 {index}/{total}：{title}（检查开放 PDF）"
            _save_progress(db, task, counts, failures, pending_ieee_ids)
            if item.queue_status not in {"selected", "pending"}:
                counts["skipped"] += 1
                counts["skipped_ineligible"] += 1
                task.progress_current += 1
                _save_progress(db, task, counts, failures, pending_ieee_ids)
                continue
            try:
                open_only = getattr(service, "discover_open_pdf_for_queue_item", None)
                legacy_service = open_only is None
                if open_only is not None:
                    result = open_only(item.id)
                else:
                    result = service.download_pdf_for_queue_item(
                        item.id,
                        allow_restricted_browser=True,
                    )
            except Exception as exc:
                db.rollback()
                task = db.get(AnalysisTask, task.id)
                counts["failed"] += 1
                failures.append(
                    _failure_values(item.id, title, f"{type(exc).__name__}: {exc}")
                )
                task.progress_current += 1
                _save_progress(db, task, counts, failures, pending_ieee_ids)
                continue
            if result.status == "downloaded":
                counts["downloaded"] += 1
                if result.source == "ieee_browser_helper":
                    counts["ieee_downloaded"] += 1
                else:
                    counts["open_access_downloaded"] += 1
                task.progress_current += 1
            elif result.status == "skipped_existing_pdf":
                counts["skipped"] += 1
                counts["skipped_existing_pdf"] += 1
                task.progress_current += 1
            elif not legacy_service and _is_ieee_item(db, item):
                pending_ieee_ids.append(item.id)
            elif result.status == "no_pdf_found":
                counts["no_pdf_found"] += 1
                failures.append(_failure(item, result.reason or "no_pdf_found"))
                task.progress_current += 1
            else:
                counts["failed"] += 1
                failures.append(_failure(item, result.reason or result.status))
                task.progress_current += 1
            task.stage_message = f"已处理 {index}/{total}：{title}；结果={result.status}"
            _save_progress(db, task, counts, failures, pending_ieee_ids)
        payload = _payload(task)
        payload["discovery_completed"] = True
        task.payload_json = json.dumps(payload, ensure_ascii=False)
        db.commit()

    # Do not revisit queue items that acquired a PDF while this task was paused.
    pending_ieee_ids = [
        item_id
        for item_id in pending_ieee_ids
        if by_id[item_id].pdf_asset_id is None
    ]
    if not pending_ieee_ids:
        _finish_task(db, task, counts, failures, total, session_service.status())
        return

    task.stage = "checking_ieee_session"
    task.stage_message = f"正在检查 IEEE 会话；待处理 {len(pending_ieee_ids)} 篇"
    _save_progress(db, task, counts, failures, pending_ieee_ids)
    session_status = session_service.status()
    if session_status.profile_exists and not session_status.login_window_open:
        session_status = session_service.status(probe=True)
    if session_status.status == "challenge_blocked":
        counts["challenge_blocked_count"] += 1
        _hold_task(
            db,
            task,
            status="challenge_blocked",
            message="IEEE 页面受到挑战限制，已停止后续访问。请人工处理或稍后重试。",
            counts=counts,
            failures=failures,
            pending_ieee_ids=pending_ieee_ids,
            session_status=session_status,
        )
        return
    if session_status.status != "authenticated":
        if not session_status.login_window_open:
            try:
                session_status = session_service.open_login_window()
            except Exception as exc:
                session_status = session_service.status()
                failures.append(
                    _failure_values(0, "IEEE session", f"{type(exc).__name__}: {exc}")
                )
        counts["requires_login"] = len(pending_ieee_ids)
        _hold_task(
            db,
            task,
            status="waiting_for_login",
            message=(
                "请在刚打开的 IEEE 专用浏览器中完成登录，"
                "登录后点击“检测登录状态”，再继续 IEEE 下载。"
            ),
            counts=counts,
            failures=failures,
            pending_ieee_ids=pending_ieee_ids,
            session_status=session_status,
        )
        return

    counts["requires_login"] = 0
    counts["resumed_count"] += 1 if payload.get("resume_requested") else 0
    if payload.get("resume_requested"):
        clear_pause = getattr(session_service, "clear_pause_request", None)
        if clear_pause is not None:
            clear_pause(task.id)
    task.stage = "downloading_ieee_pdfs"
    task.stage_message = f"IEEE 会话已认证，正在下载 {len(pending_ieee_ids)} 篇论文"
    _save_progress(db, task, counts, failures, pending_ieee_ids)
    try:
        results = service.download_ieee_batch(
            pending_ieee_ids,
            stop_file=session_service.pause_path(task.id),
        )
    except Exception as exc:
        results = [
            PdfDownloadResult(
                item_id,
                "failed",
                source="ieee_browser_helper",
                reason=f"{type(exc).__name__}: {exc}",
            )
            for item_id in pending_ieee_ids
        ]

    processed_ids = set()
    hold_status = None
    for result in results:
        item = by_id.get(result.queue_item_id)
        if item is None:
            continue
        title = _title(item)
        if result.status in {"requires_login", "challenge_blocked", "paused"}:
            hold_status = result.status
            if result.status == "challenge_blocked":
                session_service.record_challenge(result.reason or "IEEE challenge blocked")
                counts["challenge_blocked_count"] += 1
            break
        processed_ids.add(item.id)
        if result.status == "downloaded":
            counts["downloaded"] += 1
            counts["ieee_downloaded"] += 1
            session_service.record_download_success()
        elif result.status == "skipped_existing_pdf":
            counts["skipped"] += 1
            counts["skipped_existing_pdf"] += 1
        else:
            counts["failed"] += 1
            failures.append(_failure(item, result.reason or result.status))
        task.progress_current += 1
        task.stage_message = (
            f"已处理 IEEE {task.progress_current}/{total}：{title}；"
            f"结果={result.status}"
        )
        remaining = [value for value in pending_ieee_ids if value not in processed_ids]
        _save_progress(db, task, counts, failures, remaining)

    remaining = [value for value in pending_ieee_ids if value not in processed_ids]
    if hold_status or remaining:
        status = {
            "challenge_blocked": "challenge_blocked",
            "paused": "paused",
        }.get(hold_status, "waiting_for_login")
        if status == "waiting_for_login":
            counts["requires_login"] = len(remaining)
        _hold_task(
            db,
            task,
            status=status,
            message=(
                "IEEE 会话中途失效，已保存断点，请重新登录后继续。"
                if status == "waiting_for_login"
                else (
                    "任务已暂停，剩余 IEEE 条目已保留。"
                    if status == "paused"
                    else "IEEE 挑战已阻止后续下载，剩余条目已保留。"
                )
            ),
            counts=counts,
            failures=failures,
            pending_ieee_ids=remaining,
            session_status=session_service.status(),
        )
        return
    _finish_task(db, task, counts, failures, total, session_service.status())


def _hold_task(
    db,
    task,
    *,
    status,
    message,
    counts,
    failures,
    pending_ieee_ids,
    session_status,
) -> None:
    task.status = status
    task.stage = status
    task.stage_message = message
    if status == "paused":
        payload = _payload(task)
        payload["pause_acknowledged"] = True
        task.payload_json = json.dumps(payload, ensure_ascii=False)
    _save_progress(
        db,
        task,
        counts,
        failures,
        pending_ieee_ids,
        session_status=session_status,
    )


def _finish_task(db, task, counts, failures, total, session_status) -> None:
    summary = {
        "total_items": total,
        **counts,
        "found_open_access": counts["open_access_downloaded"],
        "manual_upload_required": counts["no_pdf_found"] + counts["failed"],
        "failure_count": len(failures),
        "failures": failures,
        "pending_ieee_count": 0,
        "authenticated_ieee_count": counts["ieee_downloaded"],
        "ieee_session_status": session_status.status,
        "actual_download_success_count": counts["downloaded"],
        "permanent_no_pdf_count": counts["no_pdf_found"],
        "temporary_failure_count": counts["failed"],
    }
    payload = _payload(task)
    payload["pending_ieee_item_ids"] = []
    payload["progress_summary"] = dict(counts)
    payload["result_summary"] = summary
    payload["working_failures"] = failures
    task.payload_json = json.dumps(payload, ensure_ascii=False)
    task.progress_current = total
    task.progress_total = total
    task.finished_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    if counts["downloaded"] == 0 and counts["failed"] > 0:
        task.status = "failed"
        task.stage = "failed"
        task.error_message = "所有可下载项目均失败；请查看逐篇失败原因。"
    elif counts["downloaded"] > 0 and counts["failed"] > 0:
        task.status = "partial_success"
        task.stage = "partial_success"
    elif counts["no_pdf_found"]:
        task.status = "completed_with_warnings"
        task.stage = "completed_with_warnings"
    else:
        task.status = "running"  # TaskRunner converts a clean run to succeeded.
        task.stage = "finishing"
    task.stage_message = (
        f"total_items={total}; downloaded={counts['downloaded']}; "
        f"open_access_downloaded={counts['open_access_downloaded']}; "
        f"ieee_downloaded={counts['ieee_downloaded']}; "
        f"requires_login={counts['requires_login']}; "
        f"no_pdf_found={counts['no_pdf_found']}; failed={counts['failed']}; "
        f"skipped={counts['skipped']}; failure_count={len(failures)}"
    )
    db.commit()


def _payload(task: AnalysisTask) -> dict:
    try:
        payload = json.loads(task.payload_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _counts(value=None) -> dict:
    source = value if isinstance(value, dict) else {}
    return {key: int(source.get(key) or 0) for key in COUNT_KEYS}


def _save_progress(
    db,
    task,
    counts,
    failures,
    pending_ieee_ids,
    *,
    session_status=None,
) -> None:
    payload = _payload(task)
    payload["progress_summary"] = dict(counts)
    payload["working_failures"] = failures
    payload["pending_ieee_item_ids"] = list(pending_ieee_ids)
    payload["pending_ieee_count"] = len(pending_ieee_ids)
    if session_status is not None:
        payload["ieee_session_status"] = {
            "status": session_status.status,
            "personal_login": session_status.personal_login,
            "institution_access": session_status.institution_access,
            "institution_name": session_status.institution_name,
            "challenge_detected": session_status.challenge_detected,
            "profile_exists": session_status.profile_exists,
            "profile_locked": session_status.profile_locked,
            "login_window_open": session_status.login_window_open,
            "message": session_status.message,
            "last_successful_download_at": session_status.last_successful_download_at,
        }
    task.payload_json = json.dumps(payload, ensure_ascii=False)
    db.commit()


def _is_ieee_item(db: Session, item: DeepAnalysisQueueItem) -> bool:
    publication = db.get(Publication, item.citing_publication_id)
    publisher = classify_publisher_from_doi_or_url(
        publication.doi if publication else None,
        item.publisher_landing_url or item.pdf_source_url,
    )
    return publisher.source == "ieee_xplore"


def _title(item: DeepAnalysisQueueItem) -> str:
    return (item.citing_paper_title or f"Queue item {item.id}")[:120]


def _failure(item: DeepAnalysisQueueItem, reason: str) -> dict:
    return _failure_values(item.id, item.citing_paper_title or "", reason)


def _failure_values(item_id: int, item_title: str, reason: str) -> dict:
    return {
        "queue_item_id": item_id,
        "citing_paper_title": item_title[:240],
        "reason": reason[:500],
    }
