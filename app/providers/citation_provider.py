"""Citation provider selection."""

import os

from app.core.config import settings
from app.providers.base import CitationProvider
from app.providers.fake import FakeCitationProvider
from app.providers.implementations.openalex import OpenAlexProvider


def get_citation_provider() -> CitationProvider:
    provider_name = os.getenv("ACADEMIC_IMPACT_CITATION_PROVIDER", settings.citation_provider)
    if provider_name == "fake":
        return FakeCitationProvider()
    if provider_name == "openalex":
        return OpenAlexProvider(
            timeout_seconds=float(
                os.getenv(
                    "ACADEMIC_IMPACT_PROVIDER_TIMEOUT_SECONDS",
                    str(settings.provider_timeout_seconds),
                )
            )
        )
    raise ValueError(f"Unsupported citation provider: {provider_name}")
