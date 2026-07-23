"""Local PDF matching helpers."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional


@dataclass(frozen=True)
class PdfLibraryMatch:
    entry_id: int
    pdf_asset_id: Optional[int]
    match_score: float
    match_reason: str
    filename: str


def normalize_title_for_match(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return " ".join(normalized.split())


def title_similarity(left: str, right: str) -> float:
    left_normalized = normalize_title_for_match(left)
    right_normalized = normalize_title_for_match(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()
