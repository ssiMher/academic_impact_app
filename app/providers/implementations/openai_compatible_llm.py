"""OpenAI-compatible chat/completions LLM provider."""

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.analysis.llm_parser import (
    LlmParseError,
    parse_llm_response_with_diagnostics,
    parse_template_direct_response_with_diagnostics,
)
from app.providers.base import LlmProvider
from app.providers.errors import ProviderErrorCode, ProviderException
from app.schemas.llm import CitationAnalysisResponse, LlmCitationAnalysisRequest
from app.schemas.provider import ProviderHealth


@dataclass(frozen=True)
class ProviderRequestLog:
    provider_name: str
    operation_name: str
    status: str
    duration_ms: Optional[float]
    error_kind: Optional[str]
    request_payload_redacted_json: Dict[str, Any]
    response_snapshot_path: Optional[str] = None


class OpenAICompatibleLlmProvider(LlmProvider):
    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        disable_thinking: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.disable_thinking = disable_thinking
        self.last_request_log = None
        self.last_raw_response_text = ""
        self.last_normalized_response = {}

    def health_check(self) -> ProviderHealth:
        if not self.base_url:
            return ProviderHealth(
                provider_name=self.provider_name,
                ok=False,
                message="LLM base URL is not configured.",
            )
        if not self.api_key:
            return ProviderHealth(
                provider_name=self.provider_name,
                ok=False,
                message="LLM API key is not configured.",
            )
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="OpenAI-compatible LLM provider is configured.",
        )

    def analyze_text(self, prompt: str) -> str:
        request = LlmCitationAnalysisRequest(
            target_title="",
            candidate_spans=[prompt],
        )
        return self.analyze_citation(request).model_dump_json()

    def analyze_citation(
        self,
        request: LlmCitationAnalysisRequest,
    ) -> CitationAnalysisResponse:
        body = self._build_request_body(request)
        self.last_request_log = ProviderRequestLog(
            provider_name=self.provider_name,
            operation_name="chat_completions.analyze_citation",
            status="pending",
            duration_ms=None,
            error_kind=None,
            request_payload_redacted_json=self._redacted_request_payload(body),
        )

        http_request = urllib.request.Request(
            self._chat_completions_url(),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        started_at = time.perf_counter()
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            self._mark_request_failed(started_at, ProviderErrorCode.TIMEOUT)
            raise self._exception(ProviderErrorCode.TIMEOUT, "LLM provider timed out.") from exc
        except urllib.error.HTTPError as exc:
            mapped = self._map_http_error(exc)
            self._mark_request_failed(started_at, mapped.code)
            raise mapped from exc
        except urllib.error.URLError as exc:
            self._mark_request_failed(started_at, ProviderErrorCode.TRANSIENT_NETWORK_ERROR)
            raise self._exception(
                ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                "LLM provider network request failed.",
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._mark_request_failed(started_at, ProviderErrorCode.PROVIDER_SCHEMA_ERROR)
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "LLM provider returned invalid response JSON.",
            ) from exc

        content = self._extract_message_content(response_payload)
        self.last_raw_response_text = content
        try:
            if request.analysis_scope == "fulltext_template_direct":
                parsed = parse_template_direct_response_with_diagnostics(content)
            else:
                parsed = parse_llm_response_with_diagnostics(content)
            self.last_normalized_response = parsed.model_dump()
            self._mark_request_succeeded(started_at)
            return parsed
        except LlmParseError as exc:
            self._mark_request_failed(started_at, ProviderErrorCode.PROVIDER_SCHEMA_ERROR)
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "LLM provider returned output that does not match the citation analysis schema.",
                raw_output_preview=exc.raw_output_preview,
                parse_error=exc.parse_error,
                schema_error=exc.schema_error,
            ) from exc

    def _build_request_body(self, request: LlmCitationAnalysisRequest) -> Dict[str, Any]:
        user_content = request.prompt_text or request.model_dump_json()
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only JSON matching the requested schema. "
                        "Do not include prose outside JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "response_format": {"type": "json_object"},
        }
        if self.disable_thinking:
            body["thinking"] = {"type": "disabled"}
        return body

    def _chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _extract_message_content(self, response_payload: Dict[str, Any]) -> str:
        try:
            return response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "LLM provider response is missing choices[0].message.content.",
            ) from exc

    def _map_http_error(self, exc: urllib.error.HTTPError) -> ProviderException:
        if exc.code in {401, 403}:
            return self._exception(ProviderErrorCode.AUTH_ERROR, "LLM provider authentication failed.")
        if exc.code == 429:
            return self._exception(ProviderErrorCode.RATE_LIMIT, "LLM provider rate limit exceeded.")
        if 500 <= exc.code <= 599:
            return self._exception(
                ProviderErrorCode.TRANSIENT_PROVIDER_ERROR,
                "LLM provider returned a transient server error.",
            )
        return self._exception(
            ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
            f"LLM provider returned HTTP {exc.code}.",
        )

    def _exception(
        self,
        code: ProviderErrorCode,
        message: str,
        *,
        raw_output_preview: str = "",
        parse_error: str = "",
        schema_error: str = "",
    ) -> ProviderException:
        return ProviderException(
            code=code,
            message=message,
            provider_name=self.provider_name,
            raw_output_preview=raw_output_preview,
            parse_error=parse_error,
            schema_error=schema_error,
        )

    def _redacted_request_payload(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "url": self._chat_completions_url(),
            "model": self.model,
            "api_key": "[REDACTED]" if self.api_key else "",
            "body": {key: value for key, value in body.items() if key != "messages"},
        }

    def _mark_request_succeeded(self, started_at: float) -> None:
        self._replace_request_log(
            status="succeeded",
            duration_ms=(time.perf_counter() - started_at) * 1000,
            error_kind=None,
        )

    def _mark_request_failed(self, started_at: float, error_kind: ProviderErrorCode) -> None:
        self._replace_request_log(
            status="failed",
            duration_ms=(time.perf_counter() - started_at) * 1000,
            error_kind=error_kind.value,
        )

    def _replace_request_log(
        self,
        *,
        status: str,
        duration_ms: float,
        error_kind: Optional[str],
    ) -> None:
        if self.last_request_log is None:
            return
        self.last_request_log = ProviderRequestLog(
            provider_name=self.last_request_log.provider_name,
            operation_name=self.last_request_log.operation_name,
            status=status,
            duration_ms=duration_ms,
            error_kind=error_kind,
            request_payload_redacted_json=self.last_request_log.request_payload_redacted_json,
            response_snapshot_path=self.last_request_log.response_snapshot_path,
        )


def strip_fenced_json(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped
