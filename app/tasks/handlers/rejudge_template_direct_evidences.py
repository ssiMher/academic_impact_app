"""Rejudge existing template-direct evidences without rereading full text."""

import json

from sqlalchemy.orm import Session

from app.models import AnalysisTask
from app.models.constants import SCHOLAR_ANALYSIS_SESSION_KIND
from app.services.scholar_fulltext_service import ScholarFulltextService


def handle_rejudge_template_direct_evidences(
    db: Session,
    task: AnalysisTask,
) -> None:
    if task.session_kind != SCHOLAR_ANALYSIS_SESSION_KIND:
        raise ValueError(
            "rejudge_template_direct_evidences only supports scholar sessions"
        )
    payload = _payload(task)
    result_ids = payload.get("fulltext_result_ids")
    summary = ScholarFulltextService(db).rejudge_template_direct_evidences(
        session_id=task.session_id,
        fulltext_result_ids=(
            [int(value) for value in result_ids]
            if isinstance(result_ids, list)
            else None
        ),
        task=task,
    )
    task = db.get(AnalysisTask, task.id)
    payload = _payload(task)
    payload["result_summary"] = summary
    task.payload_json = json.dumps(payload, ensure_ascii=False)
    task.progress_current = int(summary["result_count"])
    task.progress_total = int(summary["result_count"])
    task.stage = "finished"
    task.stage_message = (
        "模板重新裁决完成。"
        f"results={summary['result_count']}; "
        f"evidences={summary['evidence_count']}; "
        f"include={summary['include_count']}; "
        f"review={summary['review_count']}; "
        f"exclude={summary['exclude_count']}"
    )
    db.commit()


def _payload(task: AnalysisTask) -> dict:
    if not task.payload_json:
        return {}
    value = json.loads(task.payload_json)
    if not isinstance(value, dict):
        raise ValueError("Invalid rejudge task payload_json")
    return value
