"""Adapter for local PDF title, DOI, and arXiv matching."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.pdf.arxiv import extract_arxiv_identifier

@dataclass(frozen=True)
class LocalPdfMatch:
    path: Path
    score: float
    reason: str


def match_local_pdf(
    *,
    search_dir: Path,
    query: str = "",
    title: str = "",
    doi: str = "",
    arxiv_id: str = "",
) -> Optional[LocalPdfMatch]:
    base = Path(search_dir).expanduser()
    if not base.is_dir():
        return None

    candidates = []
    for path in sorted(base.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        score, reason = _score_pdf(path, query=query, title=title, doi=doi, arxiv_id=arxiv_id)
        if score >= 0.75:
            candidates.append(LocalPdfMatch(path=path, score=score, reason=reason))

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.score, -len(str(item.path))), reverse=True)[0]


def _score_pdf(path: Path, *, query: str, title: str, doi: str, arxiv_id: str) -> tuple:
    base_name = path.stem
    score = 0.0
    reason = ""

    normalized_arxiv = normalize_arxiv_id(arxiv_id)
    if normalized_arxiv and normalize_title(base_name) == normalize_title(normalized_arxiv):
        score, reason = 1.0, "arxiv"

    for text in (title, query):
        if not text:
            continue
        if _sanitize_filename(text).lower() == base_name.lower():
            score, reason = max(score, 1.0), "filename"
        similarity = _title_similarity(text, base_name)
        if similarity > score:
            score, reason = similarity, "title"

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        doi_hint = normalized_doi.replace("/", "_")
        if doi_hint in str(path).lower() and 0.95 > score:
            score, reason = 0.95, "doi"

    return score, reason


def normalize_arxiv_id(value: str) -> str:
    normalized = extract_arxiv_identifier(value, allow_bare=True) or ""
    return re.sub(r"v\d+$", "", normalized, flags=re.I)


def normalize_doi(value: str) -> str:
    normalized = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized


def normalize_title(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _title_similarity(query: str, candidate_title: str) -> float:
    query_n = normalize_title(query)
    candidate_n = normalize_title(candidate_title)
    if not query_n or not candidate_n:
        return 0.0
    if query_n == candidate_n:
        return 1.0
    query_words = set(query_n.split())
    candidate_words = set(candidate_n.split())
    if not query_words or not candidate_words:
        return 0.0
    return len(query_words & candidate_words) / max(len(query_words), len(candidate_words))


def _sanitize_filename(value: str) -> str:
    name = value.replace("/", "_").replace("\\", "_")
    name = re.sub(r'[\:\*\?\"\<\>\|]', "_", name)
    return name.strip()[:180] or "paper"
