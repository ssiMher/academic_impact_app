"""Build citation anchors from target paper information."""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CitationAnchor:
    title: str
    normalized_title: str
    keywords: List[str]


@dataclass(frozen=True)
class ReferenceAnchor:
    reference_marker: str
    reference_marker_text: str
    reference_entry_text: str
    reference_entry_start: int
    reference_entry_end: int
    match_method: str
    match_score: float


@dataclass(frozen=True)
class TargetReferenceContext:
    marker_text: str
    context_text: str
    start: int
    end: int
    section_heading: str
    context_type: str
    contains_formula: bool


@dataclass(frozen=True)
class BibliographicIdentityMatch:
    status: str
    method: str
    score: float
    reason_code: str


def reference_entries_by_marker(fulltext: str) -> Dict[str, str]:
    """Return raw References entries keyed by numeric citation marker."""
    return {
        marker: entry_text.strip()
        for marker, entry_text, _start, _end in _reference_entries(fulltext)
    }


def normalize_bibliographic_identity(value: str) -> str:
    """Normalize a reference entry without relying on PDF whitespace quality."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u00ad", "").replace("–", "-").replace("—", "-")
    text = re.sub(r"^\s*(?:\[\s*\d+\s*\]|\d+\s*\.)\s*", "", text)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(
        r"(?<![A-Za-z])(?:[A-Za-z][ \t]+){2,}[A-Za-z](?![A-Za-z])",
        lambda match: re.sub(r"[ \t]+", "", match.group(0)),
        text,
    )
    text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def match_bibliographic_identity(
    reference_entry: str,
    *,
    target_title: str,
    target_doi: Optional[str] = None,
    target_reference_entry: str = "",
    target_authors: Optional[List[str]] = None,
    target_year: Optional[int] = None,
    resolver_marker_matched: bool = False,
) -> BibliographicIdentityMatch:
    """Compare a raw References entry with the resolved target publication."""
    entry = normalize_bibliographic_identity(reference_entry)
    if not entry:
        return BibliographicIdentityMatch(
            "unresolved", "", 0.0, "reference_entry_unresolved"
        )

    target_entry = normalize_bibliographic_identity(target_reference_entry)
    title = normalize_bibliographic_identity(target_title)
    entry_compact = entry.replace(" ", "")
    target_entry_compact = target_entry.replace(" ", "")
    title_compact = title.replace(" ", "")

    expected_doi = _normalized_doi(target_doi) or _extract_doi(
        target_reference_entry
    )
    entry_doi = _extract_doi(reference_entry)
    if expected_doi and entry_doi and expected_doi == entry_doi:
        return BibliographicIdentityMatch(
            "matched", "exact_doi_match", 1.0, "exact_doi_match"
        )

    if len(title_compact) >= 8 and title_compact in entry_compact:
        return BibliographicIdentityMatch(
            "matched", "normalized_title_match", 0.98, "normalized_title_match"
        )

    title_tokens = set(_identity_tokens(title))
    entry_tokens = set(_identity_tokens(entry))
    title_overlap = (
        len(title_tokens & entry_tokens) / len(title_tokens)
        if title_tokens
        else 0.0
    )
    author_match = _identity_author_match(entry, target_authors or [])
    year_match = bool(target_year and str(target_year) in entry_tokens)
    if title_overlap >= 0.65 and (author_match or year_match):
        return BibliographicIdentityMatch(
            "matched",
            "title_author_year_match",
            round(0.75 + min(title_overlap, 0.2), 4),
            "title_author_year_match",
        )

    entry_similarity = (
        SequenceMatcher(None, entry_compact, target_entry_compact).ratio()
        if target_entry_compact
        else 0.0
    )
    if resolver_marker_matched:
        if target_entry_compact and entry_similarity < 0.35:
            return BibliographicIdentityMatch(
                "mismatch",
                "marker_resolver_match",
                round(entry_similarity, 4),
                "reference_marker_mapping_conflict",
            )
        return BibliographicIdentityMatch(
            "matched",
            "marker_resolver_match",
            max(0.9, round(entry_similarity, 4)),
            "marker_resolver_match",
        )

    return BibliographicIdentityMatch(
        "mismatch",
        "mismatch",
        round(max(title_overlap, entry_similarity), 4),
        "reference_entry_target_mismatch",
    )


def normalize_text(value: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    ascii_text = ascii_text.replace("-\n", "").replace("\n", " ")
    ascii_text = re.sub(
        r"(?<![A-Za-z])(?:[A-Za-z][ \t]+){2,}[A-Za-z](?![A-Za-z])",
        lambda match: re.sub(r"[ \t]+", "", match.group(0)),
        ascii_text,
    )
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", ascii_text.lower()).split())


def build_target_citation_anchor(target_title: str) -> CitationAnchor:
    normalized_title = normalize_text(target_title)
    keywords = [
        token
        for token in normalized_title.split()
        if len(token) >= 4 and token not in {"paper", "study", "analysis"}
    ]
    return CitationAnchor(
        title=target_title,
        normalized_title=normalized_title,
        keywords=keywords,
    )


def find_target_reference_anchor(
    fulltext: str,
    cited_title: str,
    cited_doi: Optional[str] = None,
    cited_authors: Optional[List[str]] = None,
) -> Optional[ReferenceAnchor]:
    entries = _reference_entries(fulltext)
    if not entries:
        return None

    normalized_title = normalize_text(cited_title)
    normalized_doi = normalize_text(cited_doi or "")
    author_terms = [
        normalize_text(author).split()[-1]
        for author in (cited_authors or [])
        if normalize_text(author)
    ]

    best_anchor = None
    best_score = 0.0
    for marker, entry_text, start, end in entries:
        normalized_entry = normalize_text(entry_text)
        compact_entry = normalized_entry.replace(" ", "")
        compact_title = normalized_title.replace(" ", "")
        score = 0.0
        method = ""
        if normalized_doi and normalized_doi in normalized_entry:
            score = 1.0
            method = "doi_exact"
        elif normalized_title and normalized_title in normalized_entry:
            score = 0.98
            method = "title_exact"
        elif len(compact_title) >= 8 and compact_title in compact_entry:
            score = 0.96
            method = "title_exact"
        else:
            title_overlap = _token_overlap(normalized_entry, normalized_title)
            author_overlap = _author_overlap(normalized_entry, author_terms)
            if title_overlap >= 0.75:
                score = max(score, round(0.8 + min(title_overlap, 0.18), 4))
                method = "title_overlap"
            if not method and title_overlap >= 0.55 and author_overlap > 0:
                score = round(0.65 + min(author_overlap * 0.1, 0.1), 4)
                method = "title_author_overlap"
        if score > best_score:
            best_score = score
            best_anchor = ReferenceAnchor(
                reference_marker=marker,
                reference_marker_text=f"[{marker}]",
                reference_entry_text=entry_text.strip(),
                reference_entry_start=start,
                reference_entry_end=end,
                match_method=method or "unknown",
                match_score=score,
            )
    return best_anchor if best_anchor and best_anchor.match_score >= 0.65 else None


def citation_text_has_target_anchor(citation_text: str, reference_marker: Optional[str]) -> bool:
    if not citation_text or not reference_marker:
        return False
    try:
        target = int(reference_marker)
    except ValueError:
        return False
    for range_match in re.finditer(r"\[(\d+)\]\s*[-–—]\s*\[(\d+)\]", citation_text):
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start <= target <= end or end <= target <= start:
            return True
    for content in re.findall(r"\[([^\]]+)\]", citation_text):
        normalized = content.replace("–", "-").replace("—", "-")
        tokens = [token.strip() for token in normalized.split(",") if token.strip()]
        for token in tokens:
            if "-" in token:
                start_text, end_text = [part.strip() for part in token.split("-", 1)]
                if start_text.isdigit() and end_text.isdigit():
                    start = int(start_text)
                    end = int(end_text)
                    if start <= target <= end or end <= target <= start:
                        return True
            elif token.isdigit() and int(token) == target:
                return True
    return False


def extract_target_reference_contexts(
    fulltext: str,
    reference_marker: str,
    window_chars: int = 1200,
    max_contexts: int = 10,
) -> List[TargetReferenceContext]:
    if not fulltext or not reference_marker:
        return []
    body_end = _references_body_end(fulltext)
    body_text = fulltext[:body_end] if body_end is not None else fulltext
    contexts: List[TargetReferenceContext] = []
    seen = set()
    pattern = re.compile(
        r"\[[^\]]+\](?:\s*,\s*\[[^\]]+\])*(?:\s*[-–—]\s*\[[^\]]+\])?"
    )
    for match in pattern.finditer(body_text):
        marker_text = match.group(0)
        if not citation_text_has_target_anchor(marker_text, reference_marker):
            continue
        start, end = _window_bounds(len(body_text), match.start(), match.end(), window_chars)
        context_text = body_text[start:end].strip()
        if not context_text:
            continue
        context_key = (start, end, normalize_text(context_text[:200]))
        if context_key in seen:
            continue
        seen.add(context_key)
        context_type = _context_type_for_marker(marker_text)
        contains_formula = _contains_formula_language(context_text)
        if contains_formula:
            context_type = "formula_nearby"
        contexts.append(
            TargetReferenceContext(
                marker_text=f"[{reference_marker}]",
                context_text=context_text,
                start=start,
                end=end,
                section_heading=_nearest_section_heading(body_text, match.start()),
                context_type=context_type,
                contains_formula=contains_formula,
            )
        )
        if len(contexts) >= max_contexts:
            break
    return contexts


def extract_alias_contexts(
    fulltext: str,
    aliases: List[str],
    window_chars: int = 1000,
    max_contexts: int = 8,
) -> List[TargetReferenceContext]:
    body_end = _references_body_end(fulltext)
    body_text = fulltext[:body_end] if body_end is not None else fulltext
    contexts: List[TargetReferenceContext] = []
    seen = set()
    for alias in aliases:
        alias = (alias or "").strip()
        if not alias:
            continue
        pattern = re.compile(re.escape(alias), re.IGNORECASE)
        for match in pattern.finditer(body_text):
            start, end = _window_bounds(len(body_text), match.start(), match.end(), window_chars)
            context_text = body_text[start:end].strip()
            if not context_text:
                continue
            context_key = (start, end, normalize_text(context_text[:200]))
            if context_key in seen:
                continue
            seen.add(context_key)
            contexts.append(
                TargetReferenceContext(
                    marker_text=alias,
                    context_text=context_text,
                    start=start,
                    end=end,
                    section_heading=_nearest_section_heading(body_text, match.start()),
                    context_type="alias_context",
                    contains_formula=_contains_formula_language(context_text),
                )
            )
            if len(contexts) >= max_contexts:
                return contexts
    return contexts


def _references_section_start(fulltext: str) -> Optional[int]:
    match = re.search(
        r"(?im)^[ \t]*(?:references|bibliography|"
        r"r[ \t]*e[ \t]*f[ \t]*e[ \t]*r[ \t]*e[ \t]*n[ \t]*c[ \t]*e[ \t]*s)"
        r"[ \t]*$",
        fulltext or "",
    )
    return match.start() if match else None


def _extract_reference_entries(references_text: str, offset: int):
    matches = list(
        re.finditer(
            r"(?m)(?:^|\f)[ \t]*\[[ \t]*(\d(?:[ \t]*\d)*)[ \t]*\][ \t]*",
            references_text,
        )
    )
    entries = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(references_text)
        marker = re.sub(r"\s+", "", match.group(1))
        entry_text = references_text[start:end]
        entries.append((marker, entry_text, offset + start, offset + end))
    return entries


def _reference_entries(fulltext: str):
    references_start = _references_section_start(fulltext)
    if references_start is not None:
        return _extract_reference_entries(
            fulltext[references_start:],
            references_start,
        )

    # Some PDF extractors omit or mangle the References heading. In that case,
    # inspect only the document tail and require several bibliography-shaped
    # numbered entries before accepting the inferred section.
    text = fulltext or ""
    candidates = _extract_reference_entries(text, 0)
    plausible = [
        entry
        for entry in candidates
        if _looks_like_bibliographic_entry(entry[1])
    ]
    if len(plausible) < 3:
        return []

    runs = []
    current = []
    previous_marker = None
    for entry in plausible:
        marker = int(entry[0])
        if previous_marker is None or 0 < marker - previous_marker <= 3:
            current.append(entry)
        else:
            if current:
                runs.append(current)
            current = [entry]
        previous_marker = marker
    if current:
        runs.append(current)
    eligible_runs = [run for run in runs if len(run) >= 3]
    return eligible_runs[-1] if eligible_runs else []


def _references_body_end(fulltext: str) -> Optional[int]:
    references_start = _references_section_start(fulltext)
    if references_start is not None:
        return references_start
    entries = _reference_entries(fulltext)
    return min((entry[2] for entry in entries), default=None)


def _looks_like_bibliographic_entry(entry_text: str) -> bool:
    text = " ".join((entry_text or "")[:2500].split())
    if not text or len(text) > 1800:
        return False
    cues = 0
    if re.search(r"\b(?:19|20)\d{2}\b", text):
        cues += 1
    if re.search(
        r"\b(?:doi|vol\.?|no\.?|pp?\.?|proc\.?|proceedings|journal|"
        r"transactions?|conference|symposium|workshop|IEEE|ACM)\b",
        text,
        flags=re.I,
    ):
        cues += 1
    if re.search(r"[“\"].{8,}[”\"]", text):
        cues += 1
    if re.search(r"^\s*\[\s*\d+\s*\]\s+[A-Z][.\w-]*(?:\s+[A-Z][.\w-]*)*,", text):
        cues += 1
    return cues >= 2


def _token_overlap(entry_text: str, title_text: str) -> float:
    title_terms = {term for term in title_text.split() if len(term) >= 4}
    if not title_terms:
        return 0.0
    entry_terms = set(entry_text.split())
    return len(title_terms & entry_terms) / len(title_terms)


def _author_overlap(entry_text: str, author_terms: List[str]) -> int:
    if not author_terms:
        return 0
    entry_terms = set(entry_text.split())
    return sum(1 for author in author_terms if author and author in entry_terms)


def _normalized_doi(value: Optional[str]) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized.startswith("https://doi.org/"):
        normalized = normalized[len("https://doi.org/") :]
    return normalized.rstrip(".,;)")


def _extract_doi(value: str) -> str:
    match = re.search(r"\b10\.\d{4,9}/[^\s<>\"]+", value or "", flags=re.I)
    return _normalized_doi(match.group(0)) if match else ""


def _identity_tokens(value: str) -> List[str]:
    ignored = {"a", "an", "and", "by", "in", "of", "on", "the", "to", "via"}
    return [
        token
        for token in (value or "").split()
        if len(token) >= 2 and token not in ignored
    ]


def _identity_author_match(entry: str, target_authors: List[str]) -> bool:
    entry_compact = entry.replace(" ", "")
    entry_tokens = set(entry.split())
    for author in target_authors:
        normalized = normalize_bibliographic_identity(author)
        if not normalized:
            continue
        compact = normalized.replace(" ", "")
        surname = normalized.split()[-1]
        if compact in entry_compact or surname in entry_tokens:
            return True
    return False


def _window_bounds(text_length: int, start: int, end: int, window_chars: int):
    half_window = max(400, window_chars // 2)
    context_start = max(0, start - half_window)
    context_end = min(text_length, end + half_window)
    return context_start, context_end


def _nearest_section_heading(text: str, position: int) -> str:
    lines = text[:position].splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 120:
            continue
        if re.match(r"^(\d+(\.\d+)*)\s+", stripped):
            return stripped
        if stripped.isupper() or re.match(r"^[A-Z][A-Za-z0-9 ,:/-]{2,}$", stripped):
            return stripped
    return ""


def _contains_formula_language(text: str) -> bool:
    normalized = normalize_text(text)
    formula_terms = {
        "eq",
        "equation",
        "formula",
        "model",
        "convolution",
        "spectral",
        "frequency",
        "sampling",
        "vector",
        "theorem",
        "proof",
    }
    return any(term in normalized.split() or term in normalized for term in formula_terms)


def _context_type_for_marker(marker_text: str) -> str:
    normalized = marker_text.replace(" ", "")
    if re.search(r"\[\d+\]\s*[-–—]\s*\[\d+\]", normalized):
        return "range_marker"
    if "," in normalized:
        return "grouped_marker"
    return "exact_marker"
