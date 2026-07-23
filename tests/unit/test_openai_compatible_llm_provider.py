import json
import socket
from urllib.error import HTTPError

import pytest

from app.providers.errors import ProviderErrorCode, ProviderException
from app.providers.implementations.openai_compatible_llm import OpenAICompatibleLlmProvider
from app.providers.llm_provider import get_llm_provider
from app.schemas.llm import LlmCitationAnalysisRequest


def request_payload():
    return LlmCitationAnalysisRequest(
        target_title="Evidence-aware citation analysis",
        candidate_spans=[
            "Evidence-aware citation analysis is a method foundation for this system."
        ],
    )


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def chat_completion_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def valid_content():
    return json.dumps(
        {
            "findings": [
                {
                    "evidence_type": "method_foundation",
                    "stance": "positive",
                    "mention_type": "strong",
                    "citation_text": "Evidence-aware citation analysis is a method foundation.",
                    "reasoning": "Specific method dependency.",
                    "keywords": ["method foundation"],
                }
            ]
        }
    )


def provider():
    return OpenAICompatibleLlmProvider(
        base_url="https://llm.example.test/v1",
        api_key="test-key",
        model="fake-model",
        timeout_seconds=3.0,
        disable_thinking=True,
    )


def test_openai_compatible_success_json(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(chat_completion_payload(valid_content()))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = provider().analyze_citation(request_payload())

    assert result.findings[0].evidence_type == "method_foundation"
    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "fake-model"
    assert captured["body"]["thinking"] == {"type": "disabled"}


def test_openai_compatible_success_fenced_json(monkeypatch):
    fenced = "```json\n" + valid_content() + "\n```"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(chat_completion_payload(fenced)),
    )

    result = provider().analyze_citation(request_payload())

    assert result.findings[0].citation_text.startswith("Evidence-aware")


def test_openai_compatible_invalid_json_maps_schema_error(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(chat_completion_payload("{not-json")),
    )

    with pytest.raises(ProviderException) as exc:
        provider().analyze_citation(request_payload())

    assert exc.value.code == ProviderErrorCode.PROVIDER_SCHEMA_ERROR


def test_openai_compatible_timeout_maps_timeout(monkeypatch):
    def fake_timeout(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_timeout)

    with pytest.raises(ProviderException) as exc:
        provider().analyze_citation(request_payload())

    assert exc.value.code == ProviderErrorCode.TIMEOUT


def test_openai_compatible_401_maps_auth_error(monkeypatch):
    def fake_401(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_401)

    with pytest.raises(ProviderException) as exc:
        provider().analyze_citation(request_payload())

    assert exc.value.code == ProviderErrorCode.AUTH_ERROR


def test_openai_compatible_429_maps_rate_limit(monkeypatch):
    def fake_429(request, timeout):
        raise HTTPError(request.full_url, 429, "Rate Limited", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_429)

    with pytest.raises(ProviderException) as exc:
        provider().analyze_citation(request_payload())

    assert exc.value.code == ProviderErrorCode.RATE_LIMIT


def test_fake_provider_is_default(monkeypatch):
    monkeypatch.delenv("ACADEMIC_IMPACT_LLM_PROVIDER", raising=False)

    selected = get_llm_provider()

    assert selected.provider_name == "fake-llm"


def test_health_json_redacts_api_key(monkeypatch):
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_API_KEY", "placeholder-value-to-redact")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_MODEL", "fake-model")

    from app.main import health_json

    payload = health_json()

    assert payload["llm_provider"]["provider"] == "openai_compatible"
    assert payload["llm_provider"]["api_key_configured"] is True
    assert "placeholder-value-to-redact" not in str(payload)
