"""Shared importance checks for scholar queue items and derived views."""

import json
from typing import Iterable


IMPORTANT_REVIEW_STATUSES = {"important"}
BLOCKING_REVIEW_STATUSES = {"rejected", "false_positive"}


def is_queue_item_important(item, annotations: Iterable = ()) -> bool:
    review_status = getattr(item, "user_review_status", "") or ""
    if review_status in BLOCKING_REVIEW_STATUSES:
        return False
    if review_status in IMPORTANT_REVIEW_STATUSES:
        return True
    if getattr(item, "is_important", False):
        return True
    if any(
        getattr(annotation, "is_important", False)
        for annotation in (annotations or [])
    ):
        return True
    reasons = _load_json_list(getattr(item, "priority_reasons_json", ""))
    return any(
        str(reason.get("reason") or "").startswith("notable_author:")
        for reason in reasons
        if isinstance(reason, dict)
    )


def _load_json_list(value: str):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
