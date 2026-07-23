"""Adapter for legacy-style candidate span location."""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.analysis.citation_anchor import build_target_citation_anchor, normalize_text


@dataclass(frozen=True)
class LegacyFulltextPage:
    page: int
    text: str


@dataclass(frozen=True)
class LegacyCandidateSpan:
    page: int
    span_index: int
    text: str
    score: int
    match_type: str
    keyword_hits: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LegacyCandidateSpanResult:
    ok: bool
    spans: List[LegacyCandidateSpan]
    reference_start_page: Optional[int] = None
    mode: str = "keyword_fallback"
    error: str = ""


def find_legacy_candidate_spans(
    *,
    pages: List[LegacyFulltextPage],
    target_title: str,
    target_doi: Optional[str] = None,
    max_spans: int = 20,
) -> LegacyCandidateSpanResult:
    if not pages:
        return LegacyCandidateSpanResult(ok=False, spans=[], error="No fulltext pages provided.")

    reference_start_page = _find_reference_start_page(pages)
    body_paragraphs = _collect_body_paragraphs(pages, reference_start_page)
    anchor = build_target_citation_anchor(target_title)
    target_doi_n = normalize_text(target_doi or "")

    candidates = []
    for page, span_index, paragraph in body_paragraphs:
        paragraph_n = normalize_text(paragraph)
        keyword_hits = [keyword for keyword in anchor.keywords if keyword in paragraph_n]
        title_match = anchor.normalized_title and anchor.normalized_title in paragraph_n
        doi_match = target_doi_n and target_doi_n in paragraph_n
        score = len(keyword_hits) * 2
        if title_match:
            score += 8
        if doi_match:
            score += 12
        if score <= 0:
            continue
        candidates.append(
            LegacyCandidateSpan(
                page=page,
                span_index=span_index,
                text=paragraph,
                score=score,
                match_type="keyword_fallback",
                keyword_hits=keyword_hits,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.page, item.span_index))
    return LegacyCandidateSpanResult(
        ok=True,
        spans=candidates[:max_spans],
        reference_start_page=reference_start_page,
    )


def _find_reference_start_page(pages: List[LegacyFulltextPage]) -> Optional[int]:
    if not pages:
        return None
    total_pages = max(page.page for page in pages) or len(pages)
    min_heading_page = max(2, int(total_pages * 0.45))
    for page in pages:
        if page.page < min_heading_page:
            continue
        if re.search(r"(?mi)^\s*(references|bibliography)\s*$", page.text or ""):
            return page.page
    return None


def _collect_body_paragraphs(
    pages: List[LegacyFulltextPage],
    reference_start_page: Optional[int],
) -> List[tuple]:
    paragraphs = []
    for page in pages:
        if reference_start_page is not None and page.page >= reference_start_page:
            continue
        for index, paragraph in enumerate(_split_paragraphs(page.text), start=1):
            paragraphs.append((page.page, index, paragraph))
    return paragraphs


def _split_paragraphs(text: str) -> List[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [
        re.sub(r"[ \t]+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", normalized)
    ]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if len(paragraphs) <= 1 and len(normalized) > 120:
        sentences = re.split(r"(?<=[\.\!\?])\s+(?=[A-Z0-9\[])", normalized)
        paragraphs = [sentence.strip() for sentence in sentences if sentence.strip()]
    return paragraphs
