"""Download one IEEE paper through the configured browser helper."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import AnalysisTask
from app.services.queue_pdf_download_service import QueuePdfDownloadService


def handle_download_ieee_pdf(db: Session, task: AnalysisTask) -> None:
    payload = _payload(task)
    item_id = int(payload.get("queue_item_id") or 0)
    task.stage = "downloading_ieee_pdf"
    task.progress_total = 1
    task.progress_current = 0
    task.stage_message = "正在通过 IEEE 专用浏览器会话下载 PDF"
    db.commit()

    result = QueuePdfDownloadService(db).download_pdf_for_queue_item(
        item_id,
        allow_restricted_browser=True,
    )
    task.progress_current = 1
    if result.status == "requires_login":
        task.status = "waiting_for_login"
        task.stage = "waiting_for_login"
        task.progress_current = 0
        task.stage_message = "IEEE 下载助手需要重新完成机构登录"
    elif result.status == "challenge_blocked":
        task.status = "challenge_blocked"
        task.stage = "challenge_blocked"
        task.progress_current = 0
        task.stage_message = "IEEE 页面受到挑战限制，已停止自动访问"
    elif result.status == "skipped_existing_pdf":
        task.stage_message = "IEEE PDF skipped: queue item already has a PDF"
    elif result.status == "downloaded":
        task.stage_message = (
            "IEEE PDF downloaded and bound; "
            f"queue_item_id={item_id}; pdf_asset_id={result.pdf_asset_id}"
        )
    else:
        raise RuntimeError(f"IEEE PDF download failed: {result.reason}")
    db.commit()


def _payload(task: AnalysisTask) -> dict:
    try:
        payload = json.loads(task.payload_json or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid download_ieee_pdf payload_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid download_ieee_pdf payload_json")
    return payload
