"""Task handler for scholar queue full-text analysis."""

import json

from sqlalchemy.orm import Session

from app.models import AnalysisTask
from app.models.constants import SCHOLAR_ANALYSIS_SESSION_KIND
from app.services.scholar_fulltext_service import ScholarFulltextService


def handle_analyze_scholar_queue(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != SCHOLAR_ANALYSIS_SESSION_KIND:
        raise ValueError("analyze_scholar_queue only supports scholar_analysis sessions")

    service = ScholarFulltextService(db)
    analysis_scope = _analysis_scope_from_task(task)
    queue_item_ids = _queue_item_ids_from_task(task)
    task.stage = "analyzing_scholar_queue"
    task.stage_message = f"Analyzing selected scholar queue items. analysis_scope={analysis_scope}"
    db.flush()

    summary = service.analyze_queue_items(
        session_id=task.session_id,
        queue_item_ids=queue_item_ids,
        analysis_scope=analysis_scope,
        task_id=task.id,
    )
    task.progress_total = int(summary["total"])
    task.progress_current = int(summary["succeeded"]) + int(summary["skipped"]) + int(summary["failed"])
    summary_message = _format_summary(summary)
    if (
        int(summary["ready_items"]) > 0
        and int(summary["analyzed_count"]) == 0
        and int(summary["failed_item_count"]) > 0
    ):
        raise ValueError(summary_message)
    if summary["warnings"]:
        task.stage_message = "Scholar queue analysis completed with warnings. " + summary_message
    else:
        task.stage_message = "Scholar queue analysis completed. " + summary_message
    db.commit()


def _format_summary(summary) -> str:
    parts = [
        f"total_queue_items={summary['total_queue_items']}",
        f"selected_items={summary['selected_items']}",
        f"ready_items={summary['ready_items']}",
        f"skipped_need_pdf_count={summary['skipped_need_pdf_count']}",
        f"skipped_not_selected_count={summary['skipped_not_selected_count']}",
        f"analyzed_count={summary['analyzed_count']}",
        f"fulltext_result_count={summary['fulltext_result_count']}",
        f"strong_evidence_count={summary['strong_evidence_count']}",
        f"failed_item_count={summary['failed_item_count']}",
        f"analysis_scope={summary.get('analysis_scope')}",
        f"fulltext_chars={summary.get('fulltext_chars')}",
        f"llm_findings_count={summary.get('llm_findings_count')}",
    ]
    warnings = summary.get("warnings") or []
    if warnings:
        parts.append(
            "warnings="
            + "; ".join(str(warning) for warning in warnings)
        )
    return "; ".join(parts)


def _analysis_scope_from_task(task: AnalysisTask) -> str:
    payload = _payload_from_task(task)
    if "analysis_scope" in payload:
        value = str(payload.get("analysis_scope") or "").strip()
        if value in {
            "candidate_spans",
            "fulltext_direct",
            "fulltext_anchor_direct",
            "fulltext_template_direct",
            "scholar_queue",
        }:
            return value
        raise ValueError(f"Unsupported analysis_scope: {value}")
    text = task.stage_message or ""
    marker = "analysis_scope="
    if marker not in text:
        return "candidate_spans"
    value = text.split(marker, 1)[1].split()[0].strip().strip(";")
    if value in {"candidate_spans", "fulltext_direct", "fulltext_anchor_direct", "fulltext_template_direct"}:
        return value
    raise ValueError(f"Unsupported analysis_scope: {value}")


def _queue_item_ids_from_task(task: AnalysisTask):
    payload = _payload_from_task(task)
    queue_item_ids = payload.get("queue_item_ids")
    if isinstance(queue_item_ids, list):
        return [int(value) for value in queue_item_ids if value not in (None, "")]
    queue_item_id = payload.get("queue_item_id")
    if queue_item_id not in (None, ""):
        return [int(queue_item_id)]
    return None


def _payload_from_task(task: AnalysisTask) -> dict:
    if not task.payload_json:
        return {}
    try:
        payload = json.loads(task.payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid analyze_scholar_queue payload_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid analyze_scholar_queue payload_json")
    return payload
