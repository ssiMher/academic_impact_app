"""Strict parsing and validation for arXiv identifiers."""

import re
from typing import Optional
from urllib.parse import unquote, urlparse


_NEW_STYLE_RE = re.compile(r"^(\d{2})(0[1-9]|1[0-2])\.(\d{4,5})(v\d+)?$", re.I)
_OLD_STYLE_RE = re.compile(
    r"^[a-z][a-z0-9-]*(?:\.[a-z]{2})?/\d{7}(?:v\d+)?$",
    re.I,
)
_ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.([^\s?#]+)", re.I)
_ARXIV_PREFIX_RE = re.compile(r"\barxiv\s*:\s*([^\s,;?#]+)", re.I)
_BARE_NEW_RE = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5}(?:v\d+)?)(?![\d.])", re.I)
_BARE_OLD_RE = re.compile(
    r"(?<![a-z0-9.-])([a-z][a-z0-9-]*(?:\.[a-z]{2})?/\d{7}(?:v\d+)?)(?![a-z0-9])",
    re.I,
)
_ORDINARY_DOI_RE = re.compile(r"\b10\.\d{4,9}/", re.I)


def normalize_arxiv_identifier(value: str) -> Optional[str]:
    """Return a canonical identifier only when the complete value is valid."""
    candidate = unquote((value or "").strip())
    if not candidate:
        return None
    candidate = re.sub(r"^arxiv\s*:\s*", "", candidate, flags=re.I)
    candidate = re.sub(r"^10\.48550/arxiv\.", "", candidate, flags=re.I)
    candidate = re.sub(r"\.pdf$", "", candidate, flags=re.I)
    candidate = candidate.strip().strip("/.,;()[]{}")
    if _NEW_STYLE_RE.fullmatch(candidate) or _OLD_STYLE_RE.fullmatch(candidate):
        return candidate
    return None


def is_valid_arxiv_identifier(value: str) -> bool:
    return normalize_arxiv_identifier(value) is not None


def extract_arxiv_identifier(value: str, *, allow_bare: bool = False) -> Optional[str]:
    """Extract an identifier only from an explicit arXiv source or allowed bare text."""
    text = unquote((value or "").strip())
    if not text:
        return None

    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        path = parsed.path.lstrip("/")
        for prefix in ("abs/", "pdf/"):
            if path.lower().startswith(prefix):
                path = path[len(prefix) :]
                break
        return normalize_arxiv_identifier(path)

    for pattern in (_ARXIV_DOI_RE, _ARXIV_PREFIX_RE):
        match = pattern.search(text)
        if match:
            return normalize_arxiv_identifier(match.group(1))

    if not allow_bare or _ORDINARY_DOI_RE.search(text):
        return None
    for pattern in (_BARE_NEW_RE, _BARE_OLD_RE):
        for match in pattern.finditer(text):
            identifier = normalize_arxiv_identifier(match.group(1))
            if identifier:
                return identifier
    return None
