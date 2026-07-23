"""Parse normalized LLM JSON into citation analysis schemas."""

import json
import re
from typing import Any, Dict, List

from pydantic import ValidationError

from app.legacy.adapters.llm_json_parser_adapter import extract_json_payload
from app.schemas.llm import CitationAnalysisResult, TemplateDirectAnalysisResult


class LlmParseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        raw_output_preview: str,
        parse_error: str = "",
        schema_error: str = "",
    ) -> None:
        super().__init__(message)
        self.raw_output_preview = raw_output_preview
        self.parse_error = parse_error
        self.schema_error = schema_error

    def diagnostic_payload(self) -> Dict[str, str]:
        return {
            "error": "provider_schema_error",
            "raw_output_preview": self.raw_output_preview,
            "parse_error": self.parse_error,
            "schema_error": self.schema_error,
        }


def parse_llm_response(raw_response: str) -> CitationAnalysisResult:
    payload = parse_llm_json_payload(raw_response)
    return CitationAnalysisResult.model_validate(payload)


def parse_llm_response_with_diagnostics(raw_response: str) -> CitationAnalysisResult:
    try:
        return parse_llm_response(raw_response)
    except ValidationError as exc:
        raise LlmParseError(
            "LLM output does not match CitationAnalysisResponse schema.",
            raw_output_preview=_preview(raw_response),
            schema_error=str(exc),
        ) from exc
    except Exception as exc:
        raise LlmParseError(
            "LLM output could not be parsed as citation analysis JSON.",
            raw_output_preview=_preview(raw_response),
            parse_error=str(exc),
        ) from exc


def parse_template_direct_response_with_diagnostics(raw_response: str) -> TemplateDirectAnalysisResult:
    try:
        payload = parse_llm_json_payload(raw_response)
        return TemplateDirectAnalysisResult.model_validate(payload)
    except ValidationError as exc:
        raise LlmParseError(
            "LLM output does not match TemplateDirectAnalysisResult schema.",
            raw_output_preview=_preview(raw_response),
            schema_error=str(exc),
        ) from exc
    except Exception as exc:
        raise LlmParseError(
            "LLM output could not be parsed as template-direct report JSON.",
            raw_output_preview=_preview(raw_response),
            parse_error=str(exc),
        ) from exc


def parse_llm_json_payload(raw_response: str) -> Dict[str, Any]:
    cleaned = strip_think_tags(raw_response or "").strip()
    if _looks_like_no_evidence_text(cleaned):
        return {"findings": []}
    if cleaned.startswith(("{", "[")):
        payload = json.loads(cleaned)
        return normalize_llm_json_payload(payload)
    payload = extract_json_payload(cleaned)
    return normalize_llm_json_payload(payload)


def normalize_llm_json_payload(payload: Any) -> Dict[str, Any]:
    """Normalize provider field aliases without inventing missing evidence labels."""
    if isinstance(payload, dict) and "findings" not in payload and "evidence" in payload:
        payload = dict(payload)
        payload["findings"] = payload.pop("evidence")
    if isinstance(payload, list):
        payload = {"findings": payload}
    if not isinstance(payload, dict):
        return payload
    findings = payload.get("findings")
    if isinstance(findings, list):
        payload = dict(payload)
        payload["findings"] = [
            _normalize_finding_aliases(finding) if isinstance(finding, dict) else finding
            for finding in findings
        ]
    return payload


def strip_think_tags(raw_response: str) -> str:
    return re.sub(r"<think>.*?</think>", "", raw_response or "", flags=re.DOTALL | re.IGNORECASE)


def _normalize_finding_aliases(finding: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(finding)
    _copy_first_alias(normalized, "evidence_type", ["aspect", "type", "category"])
    _copy_first_alias(normalized, "reasoning", ["reason", "evidence_reason"])
    _copy_first_alias(normalized, "citation_text", ["quote", "evidence_quote", "text"])
    _copy_first_alias(normalized, "keywords", ["highlight_keywords"])
    return normalized


def _copy_first_alias(payload: Dict[str, Any], canonical: str, aliases: List[str]) -> None:
    if payload.get(canonical) not in (None, ""):
        return
    for alias in aliases:
        if payload.get(alias) not in (None, ""):
            payload[canonical] = payload[alias]
            return


def _looks_like_no_evidence_text(value: str) -> bool:
    normalized = " ".join(value.lower().split())
    return normalized in {
        "no evidence found",
        "no strong evidence found",
        "no citation evidence found",
        "no relevant evidence found",
    }


def _preview(value: str, limit: int = 4000) -> str:
    return (value or "")[:limit]
