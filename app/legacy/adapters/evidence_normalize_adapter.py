"""Adapter for legacy evidence labels and highlight keyword normalization."""

import re
from dataclasses import dataclass, field
from typing import Iterable, List


@dataclass(frozen=True)
class NormalizedLegacyFinding:
    page: int
    span_index: int
    citation_text: str
    keep: bool
    aspect: str
    stance: str
    confidence: float
    mention_type: str
    function: str = ""
    reason: str = ""
    highlight_keywords: List[str] = field(default_factory=list)


def normalize_legacy_finding(finding: dict) -> NormalizedLegacyFinding:
    page = _coerce_int(finding.get("page")) or 0
    span_index = _coerce_int(finding.get("span_index")) or 0
    keep = _coerce_bool(finding.get("keep"))
    citation_text = str(finding.get("citation_text") or "").strip()
    aspect = _normalize_legacy_aspect(finding.get("aspect"), keep=keep)
    stance = _normalize_legacy_stance(finding.get("stance"))
    confidence = _coerce_float(finding.get("confidence"), default=0.6 if keep else 0.35)
    mention_type = _normalize_mention_type(finding.get("mention_type"), keep=keep)
    if mention_type == "explicit_citation" and _looks_grouped_citation(citation_text):
        mention_type = "grouped_literature_mention"
    return NormalizedLegacyFinding(
        page=page,
        span_index=span_index,
        citation_text=citation_text,
        keep=keep,
        aspect=aspect,
        stance=stance,
        confidence=confidence,
        mention_type=mention_type,
        function=str(finding.get("function") or "").strip(),
        reason=str(finding.get("reason") or "").strip(),
        highlight_keywords=normalize_highlight_keywords(
            citation_text=citation_text,
            keywords=finding.get("keywords") or [],
        ),
    )


def normalize_evidence_label(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    mapping = {
        "background": "theoretical_foundation",
        "method": "method_foundation",
        "baseline": "baseline_or_benchmark",
        "benchmark": "baseline_or_benchmark",
        "comparison": "detailed_comparison",
        "extension": "application_extension",
        "application": "application_extension",
        "adopted": "adopted_or_combined",
        "combined": "adopted_or_combined",
        "seminal": "first_or_seminal_claim",
        "first": "first_or_seminal_claim",
        "important": "important_author_citation",
    }
    return mapping.get(normalized, normalized or "method_foundation")


def normalize_highlight_keywords(*, citation_text: str, keywords: Iterable[str]) -> List[str]:
    text_lower = (citation_text or "").lower()
    seen = set()
    normalized_keywords = []
    for keyword in keywords:
        normalized = " ".join(str(keyword or "").strip().split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen or key not in text_lower:
            continue
        seen.add(key)
        normalized_keywords.append(normalized)
    return normalized_keywords


def _normalize_legacy_aspect(value, *, keep: bool) -> str:
    normalized = str(value or "").strip().lower()
    valid = {"background", "method", "baseline", "comparison", "extension", "application", "other"}
    if normalized not in valid:
        return "other" if keep else "background"
    return normalized


def _normalize_legacy_stance(value) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"positive", "neutral", "negative"}:
        return normalized
    return "neutral"


def _normalize_mention_type(value, *, keep: bool) -> str:
    normalized = str(value or "").strip()
    valid = {"explicit_citation", "grouped_literature_mention", "weak_body_mention"}
    if normalized in valid:
        return normalized
    return "explicit_citation" if keep else "weak_body_mention"


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "是"}:
            return True
        if normalized in {"false", "no", "n", "0", "否"}:
            return False
    return False


def _coerce_float(value, *, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, result))


def _coerce_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _looks_grouped_citation(text: str) -> bool:
    return bool(re.search(r"\[\s*\d+\s*(?:[,，;；]\s*\d+\s*)+\]", text or ""))
