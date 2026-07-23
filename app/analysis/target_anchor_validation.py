"""Validate that a citation quote is anchored to the target paper."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import unicodedata
from typing import Iterable, Optional

from app.analysis.citation_anchor import citation_text_has_target_anchor


@dataclass(frozen=True)
class TargetAnchorValidation:
    target_reference_marker: str
    citation_text_contains_target_marker: bool
    citation_text_contains_other_marker: bool
    anchor_validation_status: str
    anchor_validation_reason: str

    @property
    def is_valid(self) -> bool:
        return self.anchor_validation_status in {"valid", "valid_grouped"}


def validate_citation_target_anchor(
    *,
    citation_text: str,
    target_reference_marker: Optional[str],
    cited_paper_title: str,
    cited_authors_json: Optional[str] = None,
    reference_entry_text: str = "",
) -> TargetAnchorValidation:
    quote = citation_text or ""
    marker = _clean_marker(target_reference_marker)
    contains_target = citation_text_has_target_anchor(quote, marker) if marker else False
    markers = _extract_reference_markers(quote)
    contains_other = bool(marker and markers and any(value != marker for value in markers))
    contains_alias = _contains_target_alias(
        quote,
        cited_paper_title=cited_paper_title,
        cited_authors_json=cited_authors_json,
        reference_entry_text=reference_entry_text,
    )

    if marker:
        if contains_target:
            status = "valid_grouped" if contains_other else "valid"
            return TargetAnchorValidation(
                target_reference_marker=f"[{marker}]",
                citation_text_contains_target_marker=True,
                citation_text_contains_other_marker=contains_other,
                anchor_validation_status=status,
                anchor_validation_reason="citation_text_contains_target_marker",
            )
        if markers:
            return TargetAnchorValidation(
                target_reference_marker=f"[{marker}]",
                citation_text_contains_target_marker=False,
                citation_text_contains_other_marker=True,
                anchor_validation_status="invalid",
                anchor_validation_reason="cited_other_reference_marker",
            )
        if contains_alias:
            return TargetAnchorValidation(
                target_reference_marker=f"[{marker}]",
                citation_text_contains_target_marker=False,
                citation_text_contains_other_marker=False,
                anchor_validation_status="valid",
                anchor_validation_reason="title_alias_anchor_found",
            )
        return TargetAnchorValidation(
            target_reference_marker=f"[{marker}]",
            citation_text_contains_target_marker=False,
            citation_text_contains_other_marker=False,
            anchor_validation_status="invalid",
            anchor_validation_reason="target_anchor_missing",
        )

    if contains_alias:
        return TargetAnchorValidation(
            target_reference_marker="",
            citation_text_contains_target_marker=False,
            citation_text_contains_other_marker=bool(markers),
            anchor_validation_status="valid",
            anchor_validation_reason="title_alias_anchor_found",
        )
    return TargetAnchorValidation(
        target_reference_marker="",
        citation_text_contains_target_marker=False,
        citation_text_contains_other_marker=bool(markers),
        anchor_validation_status="unknown",
        anchor_validation_reason="no_target_reference_marker_available",
    )


def _clean_marker(marker: Optional[str]) -> str:
    value = str(marker or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    return value


def _extract_reference_markers(text: str) -> set[str]:
    markers: set[str] = set()
    for start, end in re.findall(r"\[(\d+)\]\s*[-–—]\s*\[(\d+)\]", text or ""):
        start_int, end_int = int(start), int(end)
        low, high = sorted((start_int, end_int))
        markers.update(str(value) for value in range(low, high + 1))
    for content in re.findall(r"\[([^\]]+)\]", text or ""):
        normalized = content.replace("–", "-").replace("—", "-")
        for token in re.split(r"\s*,\s*", normalized):
            token = token.strip()
            if "-" in token:
                left, right = [part.strip() for part in token.split("-", 1)]
                if left.isdigit() and right.isdigit():
                    low, high = sorted((int(left), int(right)))
                    markers.update(str(value) for value in range(low, high + 1))
            elif token.isdigit():
                markers.add(token)
    return markers


def _contains_target_alias(
    quote: str,
    *,
    cited_paper_title: str,
    cited_authors_json: Optional[str],
    reference_entry_text: str,
) -> bool:
    normalized_quote = _normalize(quote)
    if not normalized_quote:
        return False
    for alias in _target_aliases(cited_paper_title, cited_authors_json, reference_entry_text):
        if alias and alias in normalized_quote:
            return True
    return False


def _target_aliases(
    cited_paper_title: str,
    cited_authors_json: Optional[str],
    reference_entry_text: str,
) -> list[str]:
    aliases: list[str] = []
    normalized_title = _normalize(cited_paper_title)
    if normalized_title:
        aliases.append(normalized_title)
        if ":" in cited_paper_title:
            aliases.append(_normalize(cited_paper_title.split(":", 1)[0]))
        title_words = [word for word in normalized_title.split() if len(word) >= 5]
        if title_words:
            aliases.append(" ".join(title_words[: min(5, len(title_words))]))
    for author_name in _load_authors(cited_authors_json):
        family = _normalize(author_name).split()
        if family:
            aliases.append(f"{family[-1]} et al")
    first_reference_author = _first_reference_author(reference_entry_text)
    if first_reference_author:
        aliases.append(first_reference_author)
    return _dedupe(alias for alias in aliases if alias and len(alias) >= 4)


def _load_authors(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _first_reference_author(reference_entry_text: str) -> str:
    normalized = _normalize(reference_entry_text)
    match = re.match(r"\d*\s*([a-z][a-z]+)\s+et\s+al", normalized)
    return f"{match.group(1)} et al" if match else ""


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower())
    return " ".join(text.split())


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
