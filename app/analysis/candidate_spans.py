"""Locate candidate citation spans in extracted full text."""

import re
from dataclasses import dataclass
from typing import List

from app.analysis.citation_anchor import CitationAnchor, normalize_text


@dataclass(frozen=True)
class CandidateSpan:
    text: str
    start: int
    end: int


def split_sentences_with_offsets(text: str):
    for match in re.finditer(r"[^.!?。！？]+[.!?。！？]?", text):
        sentence = match.group(0).strip()
        if sentence:
            yield sentence, match.start(), match.end()


def find_candidate_spans(text: str, anchor: CitationAnchor, max_spans: int = 5) -> List[CandidateSpan]:
    spans: List[CandidateSpan] = []
    for sentence, start, end in split_sentences_with_offsets(text):
        normalized_sentence = normalize_text(sentence)
        title_match = anchor.normalized_title and anchor.normalized_title in normalized_sentence
        keyword_hits = sum(1 for keyword in anchor.keywords if keyword in normalized_sentence)
        if title_match or keyword_hits >= 2:
            spans.append(CandidateSpan(text=sentence, start=start, end=end))
        if len(spans) >= max_spans:
            break
    return spans
