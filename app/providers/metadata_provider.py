"""Metadata provider selection."""

import os

from app.core.config import settings
from app.providers.base import MetadataProvider
from app.providers.fake import FakeMetadataProvider
from app.providers.implementations.openalex import OpenAlexProvider


def get_metadata_provider() -> MetadataProvider:
    provider_name = os.getenv("ACADEMIC_IMPACT_METADATA_PROVIDER", settings.metadata_provider)
    if provider_name == "fake":
        return FakeMetadataProvider()
    if provider_name == "openalex":
        return OpenAlexProvider(
            timeout_seconds=float(
                os.getenv(
                    "ACADEMIC_IMPACT_PROVIDER_TIMEOUT_SECONDS",
                    str(settings.provider_timeout_seconds),
                )
            )
        )
    raise ValueError(f"Unsupported metadata provider: {provider_name}")
