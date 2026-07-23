"""Keyword selection and safe HTML rendering for evidence highlighting."""

import html
import re
from typing import Iterable, List


def build_highlight_keywords(*, citation_text: str, keywords: Iterable[str]) -> List[str]:
    lowered_text = citation_text.lower()
    seen = set()
    highlights = []
    for keyword in keywords:
        normalized = " ".join(keyword.strip().split())
        if not normalized:
            continue
        lowered_keyword = normalized.lower()
        if lowered_keyword in lowered_text and lowered_keyword not in seen:
            seen.add(lowered_keyword)
            highlights.append(normalized)
    return highlights


def build_highlighted_text_html(*, citation_text: str, keywords: Iterable[str]) -> str:
    highlighted = html.escape(citation_text or "")
    for keyword in sorted(build_highlight_keywords(citation_text=citation_text, keywords=keywords), key=len, reverse=True):
        pattern = re.compile(re.escape(html.escape(keyword)), flags=re.IGNORECASE)
        highlighted = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", highlighted)
    return highlighted
