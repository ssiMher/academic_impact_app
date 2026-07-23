import json
import socket
from urllib.error import HTTPError

import pytest
from app.providers.author_provider import get_author_provider
from app.providers.citation_provider import get_citation_provider
from app.providers.errors import ProviderErrorCode, ProviderException
from app.providers.implementations.dblp import DblpAuthorProvider
from app.providers.implementations.openalex import OpenAlexProvider
from app.providers.implementations.openai_compatible_llm import OpenAICompatibleLlmProvider
from app.providers.metadata_provider import get_metadata_provider
from app.schemas.llm import LlmCitationAnalysisRequest
from app.schemas.provider import ProviderPublication


class FakeResponse:
    def __init__(self, payload=None, raw_text=None):
        self.payload = payload
        self.raw_text = raw_text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if self.raw_text is not None:
            return self.raw_text.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


def test_dblp_provider_normalizes_pid():
    provider = DblpAuthorProvider(timeout_seconds=3.0)

    assert provider.normalize_author_ref("https://dblp.org/pid/11/1165.html") == "11/1165"
    assert provider.normalize_author_ref("pid/11/1165") == "11/1165"


def test_dblp_provider_maps_publications_to_schema(monkeypatch):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <dblpperson>
      <person name="Grace Hopper" pid="11/1165"/>
      <r>
        <article key="journals/test/Hopper24">
          <author>Grace Hopper</author>
          <author>Avery Stone</author>
          <title>Evidence-Aware Impact.</title>
          <year>2024</year>
          <journal>Journal of Tests</journal>
          <ee>https://doi.org/10.1234/example</ee>
        </article>
      </r>
    </dblpperson>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(raw_text=xml_payload),
    )

    identity = DblpAuthorProvider(timeout_seconds=3.0).resolve_author("pid/11/1165")

    assert identity.display_name == "Grace Hopper"
    assert identity.dblp_id == "11/1165"
    assert identity.publications[0].title == "Evidence-Aware Impact"
    assert identity.publications[0].venue == "Journal of Tests"
    assert identity.publications[0].doi == "10.1234/example"
    assert identity.publications[0].authors == ["Grace Hopper", "Avery Stone"]


def test_dblp_author_provider_parses_primary_name(monkeypatch):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <dblpperson>
      <person name="Jingyi Ning" pid="275/7641"/>
    </dblpperson>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(raw_text=xml_payload),
    )

    identity = DblpAuthorProvider(timeout_seconds=3.0).resolve_author("275/7641")

    assert identity.display_name == "Jingyi Ning"
    assert identity.dblp_id == "275/7641"


def test_dblp_pid_not_used_as_display_name_when_name_missing(monkeypatch):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <dblpperson>
      <person pid="275/7641"/>
    </dblpperson>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(raw_text=xml_payload),
    )

    identity = DblpAuthorProvider(timeout_seconds=3.0).resolve_author("275/7641")

    assert identity.display_name == "待解析"
    assert identity.display_name != "275/7641"


def test_dblp_pid_resolves_display_name_from_profile(monkeypatch):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <dblpperson>
      <person name="Jingyi Ning" pid="275/7641"/>
    </dblpperson>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(raw_text=xml_payload),
    )

    name = DblpAuthorProvider(timeout_seconds=3.0).resolve_author_name_by_pid("275/7641")

    assert name == "Jingyi Ning"


def test_dblp_pid_resolves_display_name_from_publication_fallback(monkeypatch):
    xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <dblpperson>
      <person pid="275/7641"/>
      <r>
        <article>
          <author pid="275/7641">Jingyi Ning</author>
          <title>Paper.</title>
          <year>2024</year>
        </article>
      </r>
    </dblpperson>
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(raw_text=xml_payload),
    )

    name = DblpAuthorProvider(timeout_seconds=3.0).resolve_author_name_by_pid("275/7641")

    assert name == "Jingyi Ning"


def test_openalex_provider_maps_citing_papers_to_schema(monkeypatch):
    captured = {}
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W2",
                "title": "Citing OpenAlex Paper",
                "publication_year": 2025,
                "doi": "https://doi.org/10.5555/citing",
                "primary_location": {"source": {"display_name": "Open Journal"}},
                "authorships": [
                    {"author": {"display_name": "Lin Chen"}},
                    {"author": {"display_name": "Maya Patel"}},
                ],
            }
        ]
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    publication = ProviderPublication(
        title="Target",
        source_url="https://openalex.org/W1",
    )

    edges = OpenAlexProvider(timeout_seconds=3.0).list_citing_papers(publication, limit=1)

    assert "filter=cites%3AW1" in captured["url"]
    assert len(edges) == 1
    assert edges[0].target_title == "Target"
    assert edges[0].citing_paper.title == "Citing OpenAlex Paper"
    assert edges[0].citing_paper.venue == "Open Journal"
    assert edges[0].citing_paper.doi == "10.5555/citing"
    assert edges[0].citing_paper.openalex_id == "W2"
    assert edges[0].citing_paper.authors == ["Lin Chen", "Maya Patel"]
    assert edges[0].citing_paper.source_url == "https://openalex.org/W2"


def test_openalex_citation_provider_paginates_beyond_first_page(monkeypatch):
    requested_urls = []
    first_page = {
        "meta": {"count": 40, "next_cursor": "cursor-2"},
        "results": [
            {
                "id": f"https://openalex.org/W{index}",
                "title": f"Citing OpenAlex Paper {index}",
                "publication_year": 2025,
            }
            for index in range(1, 26)
        ],
    }
    second_page = {
        "meta": {"count": 40, "next_cursor": None},
        "results": [
            {
                "id": f"https://openalex.org/W{index}",
                "title": f"Citing OpenAlex Paper {index}",
                "publication_year": 2025,
            }
            for index in range(26, 41)
        ],
    }
    pages = [first_page, second_page]

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse(pages.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    publication = ProviderPublication(
        title="Target",
        source_url="https://openalex.org/W1",
        openalex_cited_by_count=40,
        openalex_cited_by_api_url="https://api.openalex.org/works?filter=cites:W1",
    )

    provider = OpenAlexProvider(timeout_seconds=3.0)
    edges = provider.list_citing_papers(publication, limit=100)

    assert len(edges) == 40
    assert len(requested_urls) == 2
    assert "per-page=100" in requested_urls[0]
    assert "cursor=%2A" in requested_urls[0]
    assert "cursor=cursor-2" in requested_urls[1]
    assert provider.last_citation_expansion["openalex_cited_by_count"] == 40
    assert provider.last_citation_expansion["fetched_count"] == 40
    assert provider.last_citation_expansion["cursor_pages"] == 2
    assert provider.last_citation_expansion["expansion_complete"] is True


def test_openalex_rate_limit_error(monkeypatch):
    def fake_429(request, timeout):
        raise HTTPError(request.full_url, 429, "Rate Limited", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_429)

    with pytest.raises(ProviderException) as exc:
        OpenAlexProvider(timeout_seconds=3.0).enrich_publication("10.5555/example")

    assert exc.value.code == ProviderErrorCode.RATE_LIMIT


def test_openalex_timeout_error(monkeypatch):
    def fake_timeout(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_timeout)

    with pytest.raises(ProviderException) as exc:
        OpenAlexProvider(timeout_seconds=3.0).enrich_publication("10.5555/example")

    assert exc.value.code == ProviderErrorCode.TIMEOUT


def test_openai_compatible_llm_success(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "findings": [
                                {
                                    "evidence_type": "method_foundation",
                                    "stance": "positive",
                                    "mention_type": "strong",
                                    "citation_text": "The method is used directly.",
                                    "reasoning": "Specific method dependency.",
                                    "keywords": ["method"],
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(payload),
    )

    result = OpenAICompatibleLlmProvider(
        base_url="https://llm.example.test/v1",
        api_key="test-key",
        model="fake-model",
        timeout_seconds=3.0,
        disable_thinking=True,
    ).analyze_citation(
        LlmCitationAnalysisRequest(
            target_title="Target",
            candidate_spans=["The method is used directly."],
        )
    )

    assert result.findings[0].citation_text == "The method is used directly."


def test_openai_compatible_llm_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {"choices": [{"message": {"content": "not json { at all"}}]}
        ),
    )

    with pytest.raises(ProviderException) as exc:
        OpenAICompatibleLlmProvider(
            base_url="https://llm.example.test/v1",
            api_key="test-key",
            model="fake-model",
            timeout_seconds=3.0,
            disable_thinking=True,
        ).analyze_citation(
            LlmCitationAnalysisRequest(target_title="Target", candidate_spans=["Text"])
        )

    assert exc.value.code == ProviderErrorCode.PROVIDER_SCHEMA_ERROR


def test_openai_compatible_llm_embedded_json(monkeypatch):
    content = (
        "Here is the analysis: "
        + json.dumps(
            {
                "findings": [
                    {
                        "evidence_type": "baseline_or_benchmark",
                        "stance": "neutral",
                        "mention_type": "strong",
                        "citation_text": "The target is used as a benchmark.",
                        "reasoning": "Benchmark usage is explicit.",
                        "keywords": ["benchmark"],
                    }
                ]
            }
        )
        + " End."
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: FakeResponse(
            {"choices": [{"message": {"content": content}}]}
        ),
    )

    result = OpenAICompatibleLlmProvider(
        base_url="https://llm.example.test/v1",
        api_key="test-key",
        model="fake-model",
        timeout_seconds=3.0,
        disable_thinking=True,
    ).analyze_citation(
        LlmCitationAnalysisRequest(target_title="Target", candidate_spans=["Text"])
    )

    assert result.findings[0].evidence_type == "baseline_or_benchmark"


def test_openai_compatible_llm_401_auth_error(monkeypatch):
    def fake_401(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_401)

    with pytest.raises(ProviderException) as exc:
        OpenAICompatibleLlmProvider(
            base_url="https://llm.example.test/v1",
            api_key="test-key",
            model="fake-model",
            timeout_seconds=3.0,
            disable_thinking=True,
        ).analyze_citation(
            LlmCitationAnalysisRequest(target_title="Target", candidate_spans=["Text"])
        )

    assert exc.value.code == ProviderErrorCode.AUTH_ERROR


def test_provider_health_redacts_api_key(monkeypatch):
    monkeypatch.setenv("ACADEMIC_IMPACT_AUTHOR_PROVIDER", "fake")
    monkeypatch.setenv("ACADEMIC_IMPACT_CITATION_PROVIDER", "fake")
    monkeypatch.setenv("ACADEMIC_IMPACT_METADATA_PROVIDER", "fake")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_API_KEY", "phase16-secret")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_MODEL", "fake-model")

    from app.main import providers_health

    payload = providers_health()

    assert payload["llm_provider"]["api_key_configured"] is True
    assert "phase16-secret" not in str(payload)


def test_fake_provider_still_default(monkeypatch):
    for key in [
        "ACADEMIC_IMPACT_AUTHOR_PROVIDER",
        "ACADEMIC_IMPACT_CITATION_PROVIDER",
        "ACADEMIC_IMPACT_METADATA_PROVIDER",
        "ACADEMIC_IMPACT_LLM_PROVIDER",
    ]:
        monkeypatch.delenv(key, raising=False)

    assert get_author_provider().provider_name == "fake-author"
    assert get_citation_provider().provider_name == "fake"
    assert get_metadata_provider().provider_name == "fake-metadata"


def test_no_real_network_in_tests():
    provider_test_source = __import__("pathlib").Path(__file__).read_text(encoding="utf-8")
    forbidden_urlopen = "urllib.request." + "urlopen("
    forbidden_requests = "requests." + "get("

    assert forbidden_urlopen not in provider_test_source
    assert forbidden_requests not in provider_test_source
