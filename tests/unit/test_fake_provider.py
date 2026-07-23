import pytest

from app.providers.errors import ProviderErrorCode, ProviderException
from app.providers.fake import FakeCitationProvider


def test_fake_provider_health_check_returns_ok():
    provider = FakeCitationProvider()

    health = provider.health_check()

    assert health.ok is True
    assert health.provider_name == "fake"
    assert health.message == "Fake provider is ready."


def test_fake_citation_provider_returns_fixed_citing_papers():
    provider = FakeCitationProvider()

    results = provider.discover_citations("A target paper")

    assert len(results) == 5
    assert [edge.citing_paper.title for edge in results] == [
        "Evidence-Aware Academic Impact Assessment",
        "Citation Contexts for Research Evaluation",
        "Human Review Loops in Scholarly Analytics",
        "Template-Based Evidence Classification",
        "PDF Grounding for Citation Analysis",
    ]
    assert all(edge.citing_paper.source_url.startswith("fake://citations/") for edge in results)
    assert all(edge.citing_paper.authors for edge in results)
    assert results[0].citing_paper.citation_contexts == [
        "This work builds on the target paper to evaluate evidence quality."
    ]
    assert results[-1].citing_paper.citation_contexts == []


@pytest.mark.parametrize(
    ("code", "is_retryable"),
    [
        (ProviderErrorCode.RATE_LIMITED, True),
        (ProviderErrorCode.TIMEOUT, True),
        (ProviderErrorCode.AUTHENTICATION_FAILED, False),
        (ProviderErrorCode.NOT_FOUND, False),
    ],
)
def test_provider_error_can_be_classified(code, is_retryable):
    error = ProviderException(
        code=code,
        message="Provider failed",
        provider_name="fake",
    ).to_error()

    assert error.code == code
    assert error.provider_name == "fake"
    assert error.message == "Provider failed"
    assert error.is_retryable is is_retryable
