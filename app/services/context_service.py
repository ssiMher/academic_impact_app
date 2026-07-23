"""Helpers for deriving report-friendly long-context previews from extracted text."""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import unicodedata
from typing import Iterable, Optional


@dataclass
class CardContext:
    citation_text: str = ""
    citation_sentence: str = ""
    paragraph_context: str = ""
    anchor_context: str = ""
    display_context: str = ""
    body_context_before: str = ""
    body_context_after: str = ""
    body_context_full: str = ""
    section_heading: str = ""
    target_reference_marker: str = ""
    context_start: Optional[int] = None
    context_end: Optional[int] = None
    highlight_terms: list[str] = None
    highlighted_sentence_html: str = ""
    highlighted_paragraph_html: str = ""
    highlighted_context_html: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["highlight_terms"] = self.highlight_terms or []
        return data


def build_context_preview(
    *,
    extracted_text_path: Optional[str],
    citation_text: str,
    diagnostics: Optional[object] = None,
    target_reference_marker: Optional[str] = None,
    highlight_terms: Optional[Iterable[str]] = None,
    before_chars: int = 900,
    after_chars: int = 900,
    max_total_chars: int = 1800,
) -> dict:
    if not extracted_text_path:
        return _empty_context()
    path = Path(extracted_text_path)
    if not path.exists() or not path.is_file():
        return _empty_context()
    full_text = path.read_text(encoding="utf-8")
    if not full_text.strip():
        return _empty_context()

    diagnostics_payload = _load_json(diagnostics)
    target_reference_marker = (
        target_reference_marker
        or str(diagnostics_payload.get("target_reference_marker") or "").strip()
        or None
    )
    technical_terms = _collect_highlight_terms(
        citation_text=citation_text,
        supplied_terms=highlight_terms,
        diagnostics_payload=diagnostics_payload,
    )

    body_text, body_limit = _body_text_before_references(full_text)
    if not body_text.strip():
        body_text = full_text
        body_limit = len(full_text)

    span = (
        _locate_from_target_contexts(
            body_text,
            diagnostics_payload=diagnostics_payload,
            target_reference_marker=target_reference_marker,
        )
        or _locate_normalized(body_text, citation_text)
        or _locate_by_marker_window(
            body_text,
            citation_text=citation_text,
            target_reference_marker=target_reference_marker,
            technical_terms=technical_terms,
        )
    )
    if span is None:
        return _empty_context()

    start, end = span
    if start >= body_limit:
        return _empty_context()

    paragraph = _paragraph_for_index(body_text, start, end)
    sentence = _sentence_for_index(body_text, start, end)
    trimmed_citation = citation_text.strip()
    if trimmed_citation and trimmed_citation.endswith((".", "!", "?")):
        sentence = trimmed_citation
    section_heading = _diagnostic_section_heading(diagnostics_payload) or _nearest_section_heading(body_text, start)

    paragraph_bounds = _paragraph_bounds(body_text, start, end)
    if paragraph_bounds is not None:
        paragraph_start, paragraph_end = paragraph_bounds
    else:
        paragraph_start, paragraph_end = start, end

    window_start = max(0, start - before_chars)
    window_end = min(len(body_text), end + after_chars)

    display_start = paragraph_start
    display_end = paragraph_end
    if display_end - display_start < max_total_chars // 3:
        display_start = min(display_start, window_start)
        display_end = max(display_end, window_end)
    if display_end - display_start > max_total_chars:
        display_start, display_end = _trim_window_around_span(
            display_start,
            display_end,
            start,
            end,
            max_total_chars=max_total_chars,
            text_len=len(body_text),
        )

    display_context = body_text[display_start:display_end].strip()
    anchor_context = _best_anchor_context(
        body_text=body_text,
        diagnostics_payload=diagnostics_payload,
        start=start,
        end=end,
        max_total_chars=max_total_chars,
    )
    if not anchor_context:
        anchor_context = display_context

    highlight_target = sentence or citation_text
    highlighted_context_html = _highlight_html(
        display_context,
        sentence=highlight_target,
        citation_text=citation_text,
        target_reference_marker=target_reference_marker,
        highlight_terms=technical_terms,
    )
    context = CardContext(
        citation_text=citation_text,
        body_context_before=body_text[display_start:start],
        body_context_after=body_text[end:display_end],
        body_context_full=display_context,
        citation_sentence=sentence,
        paragraph_context=paragraph,
        anchor_context=anchor_context,
        display_context=display_context,
        context_start=display_start,
        context_end=display_end,
        section_heading=section_heading,
        target_reference_marker=target_reference_marker or "",
        highlight_terms=technical_terms,
        highlighted_sentence_html=_highlight_html(
            sentence,
            sentence=sentence,
            citation_text=citation_text,
            target_reference_marker=target_reference_marker,
            highlight_terms=technical_terms,
        ),
        highlighted_paragraph_html=_highlight_html(
            paragraph,
            sentence=sentence,
            citation_text=citation_text,
            target_reference_marker=target_reference_marker,
            highlight_terms=technical_terms,
        ),
        highlighted_context_html=highlighted_context_html,
    )
    return context.to_dict()


def _body_text_before_references(text: str) -> tuple[str, int]:
    pattern = re.compile(
        r"(?im)^(references|bibliography)\s*$"
    )
    match = pattern.search(text)
    if not match:
        return text, len(text)
    return text[:match.start()], match.start()


def _collect_highlight_terms(
    *,
    citation_text: str,
    supplied_terms: Optional[Iterable[str]],
    diagnostics_payload: dict,
) -> list[str]:
    terms = []
    for term in supplied_terms or []:
        if term:
            terms.append(str(term))
    preview_text = " ".join(
        str(item.get("context_text_preview") or "")
        for item in diagnostics_payload.get("target_contexts_preview", [])[:3]
        if isinstance(item, dict)
    )
    terms.extend(_diagnostic_keyword_terms(diagnostics_payload))
    terms.extend(_extract_candidate_phrases(f"{citation_text} {preview_text}", max_terms=8))
    combined = f"{citation_text} {preview_text}".lower()
    deduped = []
    seen = set()
    for term in terms:
        normalized = term.strip().lower()
        if not normalized or normalized in seen:
            continue
        if normalized in combined or normalized in {str(diagnostics_payload.get("target_reference_marker") or "").lower()}:
            deduped.append(term.strip())
            seen.add(normalized)
    return deduped


def _diagnostic_keyword_terms(payload: dict) -> list[str]:
    terms: list[str] = []

    def visit(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"highlight_keywords", "keywords", "matched_terms", "positive_keywords"}:
                    if isinstance(nested, list):
                        terms.extend(str(item) for item in nested if str(item).strip())
                    elif nested:
                        terms.append(str(nested))
                else:
                    visit(nested)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return terms


def _extract_candidate_phrases(text: str, *, max_terms: int = 8) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "")
    if not cleaned:
        return []
    phrases: list[str] = []

    for match in re.finditer(r"\b(?:Eq\.?|Equation)\s*\(?\d+[A-Za-z]?\)?", cleaned, flags=re.IGNORECASE):
        phrases.append(match.group(0).strip())

    # Generic technical noun phrase heuristic. It intentionally uses structural
    # cues instead of domain-specific vocabulary.
    pattern = re.compile(
        r"\b(?:[^\W_][\w'’.-]{2,}\s+){1,5}"
        r"(?:model|models|method|methods|process|processes|operation|operations|"
        r"mechanism|mechanisms|equation|equations|framework|frameworks|"
        r"pipeline|pipelines|estimation|detection|tracking|classification|"
        r"vector|vectors|signal|signals|peak|peaks|difference|differences|"
        r"pattern|patterns|feature|features|representation|representations|"
        r"change|changes|sensor|sensors)\b",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(cleaned):
        phrase = match.group(0).strip(" ,.;:()[]")
        if 5 <= len(phrase) <= 90:
            phrases.append(phrase)

    deduped: list[str] = []
    seen = set()
    for phrase in phrases:
        normalized = phrase.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(phrase)
        if len(deduped) >= max_terms:
            break
    return deduped


def _locate_from_target_contexts(
    body_text: str,
    *,
    diagnostics_payload: dict,
    target_reference_marker: Optional[str],
) -> Optional[tuple[int, int]]:
    previews = diagnostics_payload.get("target_contexts_preview", [])
    for preview in previews:
        if not isinstance(preview, dict):
            continue
        snippet = str(preview.get("context_text_preview") or "").replace("...", " ").strip()
        if len(snippet) < 40:
            continue
        span = _locate_normalized(body_text, snippet)
        if span is not None:
            return span
    if target_reference_marker:
        return _locate_by_marker_window(
            body_text,
            citation_text="",
            target_reference_marker=target_reference_marker,
            technical_terms=[],
        )
    return None


def _locate_by_marker_window(
    body_text: str,
    *,
    citation_text: str,
    target_reference_marker: Optional[str],
    technical_terms: Iterable[str],
) -> Optional[tuple[int, int]]:
    if not target_reference_marker:
        return None
    marker = target_reference_marker.strip()
    matches = [match.start() for match in re.finditer(re.escape(marker), body_text)]
    if not matches:
        return None
    best_start = matches[0]
    best_score = -1
    lowered_quote = citation_text.lower()
    for start in matches:
        end = start + len(marker)
        window = body_text[max(0, start - 800): min(len(body_text), end + 800)]
        score = 0
        if lowered_quote:
            shared_words = {
                word for word in re.findall(r"[A-Za-z][A-Za-z0-9.-]{3,}", lowered_quote)
                if word in window.lower()
            }
            score += len(shared_words) * 3
        score += sum(5 for term in technical_terms if term.lower() in window.lower())
        if score > best_score:
            best_score = score
            best_start = start
    return best_start, best_start + len(marker)


def _locate_normalized(text: str, needle: str) -> Optional[tuple[int, int]]:
    if not needle:
        return None
    normalized_text, index_map = _normalize_with_map(text)
    normalized_needle, _ = _normalize_with_map(needle)
    normalized_needle = normalized_needle.strip()
    if not normalized_needle:
        return None
    found = normalized_text.find(normalized_needle)
    if found < 0:
        return None
    start = index_map[found]
    end = index_map[min(len(index_map) - 1, found + len(normalized_needle) - 1)] + 1
    return start, end


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    prev_space = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "-" and i + 1 < len(text) and text[i + 1] == "\n":
            i += 2
            continue
        normalized = unicodedata.normalize("NFKD", char)
        plain_chars = []
        for piece in normalized:
            if unicodedata.combining(piece):
                continue
            plain = _replace_char(piece)
            if plain:
                plain_chars.extend(list(plain))
        if not plain_chars:
            i += 1
            continue
        for piece in plain_chars:
            if piece.isspace():
                if not prev_space:
                    chars.append(" ")
                    index_map.append(i)
                    prev_space = True
            else:
                chars.append(piece.lower())
                index_map.append(i)
                prev_space = False
        i += 1
    return "".join(chars), index_map


def _replace_char(char: str) -> str:
    replacements = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "´": "'",
        "`": "'",
        "\u00a0": " ",
    }
    if char in replacements:
        return replacements[char]
    if char.isspace():
        return " "
    return char


def _nearest_section_heading(text: str, position: int) -> str:
    lines = text[:position].splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 90:
            continue
        if re.match(r"^(\d+(\.\d+)*|[IVX]+-[A-Z0-9]+)\)?[\s:.-]+", stripped):
            return stripped
        if stripped.isupper():
            return stripped
        if stripped.endswith("."):
            continue
        if len(stripped.split()) <= 8 and re.match(r"^[A-Z][A-Za-z0-9 ,:/()'’-]{2,}$", stripped):
            return stripped
    return ""


def _diagnostic_section_heading(diagnostics_payload: dict) -> str:
    previews = diagnostics_payload.get("target_contexts_preview", [])
    for preview in previews:
        if not isinstance(preview, dict):
            continue
        heading = str(preview.get("section_heading") or "").strip()
        if heading:
            return heading
    return ""


def _empty_context():
    return CardContext(highlight_terms=[]).to_dict()


def _sentence_for_index(text: str, start: int, end: int) -> str:
    left = max(
        text.rfind(". ", 0, start),
        text.rfind("! ", 0, start),
        text.rfind("? ", 0, start),
        text.rfind("; ", 0, start),
        text.rfind("\n", 0, start),
    )
    right_candidates = [
        idx
        for idx in [
            text.find(". ", end),
            text.find("! ", end),
            text.find("? ", end),
            text.find("; ", end),
            text.find("\n", end),
        ]
        if idx >= 0
    ]
    right = min(right_candidates) if right_candidates else len(text)
    left = 0 if left < 0 else left + 1
    right = len(text) if right < 0 else min(len(text), right + 1)
    return text[left:right].strip()


def _paragraph_bounds(text: str, start: int, end: int) -> Optional[tuple[int, int]]:
    left = text.rfind("\n\n", 0, start)
    right = text.find("\n\n", end)
    left = 0 if left < 0 else left + 2
    right = len(text) if right < 0 else right
    if right <= left:
        return None
    return left, right


def _paragraph_for_index(text: str, start: int, end: int) -> str:
    bounds = _paragraph_bounds(text, start, end)
    if bounds is None:
        return text[start:end].strip()
    left, right = bounds
    return text[left:right].strip()


def _trim_window_around_span(
    start: int,
    end: int,
    focus_start: int,
    focus_end: int,
    *,
    max_total_chars: int,
    text_len: int,
) -> tuple[int, int]:
    if end - start <= max_total_chars:
        return start, end
    padding_left = min((max_total_chars - (focus_end - focus_start)) // 2, focus_start - start)
    padding_right = max_total_chars - (focus_end - focus_start) - padding_left
    new_start = max(0, focus_start - padding_left)
    new_end = min(text_len, focus_end + padding_right)
    if new_end - new_start > max_total_chars:
        new_end = min(text_len, new_start + max_total_chars)
    return new_start, new_end


def _best_anchor_context(
    *,
    body_text: str,
    diagnostics_payload: dict,
    start: int,
    end: int,
    max_total_chars: int,
) -> str:
    previews = diagnostics_payload.get("target_contexts_preview", [])
    for preview in previews:
        if isinstance(preview, dict):
            text = str(preview.get("context_text_preview") or "").strip()
            if text:
                return text[:max_total_chars]
    window_start = max(0, start - 500)
    window_end = min(len(body_text), end + 500)
    return body_text[window_start:window_end].strip()


def _highlight_html(
    text: str,
    *,
    sentence: str,
    citation_text: str,
    target_reference_marker: Optional[str],
    highlight_terms: Iterable[str],
) -> str:
    if not text:
        return ""
    if sentence and text.strip() == sentence.strip():
        return f"<mark>{html.escape(text)}</mark>"
    escaped = html.escape(text)
    if sentence:
        escaped_sentence = html.escape(sentence)
        escaped = escaped.replace(
            escaped_sentence,
            f'<span class="context-sentence">{escaped_sentence}</span>',
            1,
        )
    for token in _highlight_tokens(citation_text, target_reference_marker, highlight_terms):
        escaped = _replace_first_case_insensitive_mark(escaped, token)
    return escaped


def _highlight_tokens(
    citation_text: str,
    target_reference_marker: Optional[str],
    highlight_terms: Iterable[str],
) -> list[str]:
    tokens = []
    if target_reference_marker:
        tokens.append(target_reference_marker)
    for term in highlight_terms:
        if term:
            tokens.append(term)
    deduped = []
    seen = set()
    for token in tokens:
        normalized = token.strip().lower()
        if not normalized or normalized in seen:
            continue
        deduped.append(token.strip())
        seen.add(normalized)
    return deduped


def _replace_first_case_insensitive_mark(text: str, token: str) -> str:
    escaped_token = html.escape(token)
    pattern = re.compile(re.escape(escaped_token), flags=re.IGNORECASE)
    return pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", text, count=1)


def _load_json(value: Optional[object]) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
