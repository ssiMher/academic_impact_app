"""Adapter for robust legacy LLM JSON extraction."""

import json
import re
from typing import Any, Iterable, Optional

from app.schemas.llm import CitationAnalysisResponse


def strip_thinking_blocks(text: str) -> str:
    cleaned = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    cleaned = re.sub(r"(?is)<think>.*$", "", cleaned)
    return cleaned.strip()


def parse_legacy_llm_json(raw_response: str) -> CitationAnalysisResponse:
    payload = extract_json_payload(raw_response)
    return CitationAnalysisResponse.model_validate(payload)


def extract_json_payload(raw_response: str) -> Any:
    text = (raw_response or "").strip()
    if not text:
        raise ValueError("LLM response is empty.")

    direct = _try_json(text)
    if direct is not None:
        return direct

    cleaned = strip_thinking_blocks(text)
    fenced_blocks = re.findall(r"(?is)```(?:json)?\s*(.*?)```", cleaned)
    parsed = _choose_json_candidate(_parse_candidates(fenced_blocks))
    if parsed is not None:
        return parsed

    parsed = _choose_json_candidate(_parse_embedded_json_values(cleaned))
    if parsed is not None:
        return parsed

    raise ValueError("No valid JSON object found in LLM response.")


def _try_json(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_candidates(candidates: Iterable[str]) -> list:
    values = []
    for candidate in candidates:
        parsed = _try_json((candidate or "").strip())
        if parsed is not None:
            values.append(parsed)
    return values


def _parse_embedded_json_values(text: str) -> list:
    decoder = json.JSONDecoder()
    values = []
    for match in re.finditer(r"[\{\[]", text):
        try:
            value, _end = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        values.append(value)
    return values


def _choose_json_candidate(values: list) -> Optional[Any]:
    if not values:
        return None
    for value in reversed(values):
        if isinstance(value, dict) and isinstance(value.get("findings"), list):
            return value
    for value in reversed(values):
        if isinstance(value, dict):
            return value
    return values[-1]
