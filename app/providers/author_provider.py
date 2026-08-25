"""Author provider selection."""

from functools import lru_cache
import os

from app.core.config import settings
from app.providers.base import AuthorProvider
from app.providers.fake import FakeAuthorProvider
from app.providers.implementations.dblp import DblpAuthorProvider


def get_author_provider() -> AuthorProvider:
    provider_name = os.getenv("ACADEMIC_IMPACT_AUTHOR_PROVIDER", settings.author_provider)
    timeout_seconds = float(
        os.getenv(
            "ACADEMIC_IMPACT_PROVIDER_TIMEOUT_SECONDS",
            str(settings.provider_timeout_seconds),
        )
    )
    return _get_author_provider(provider_name, timeout_seconds)


@lru_cache(maxsize=8)
def _get_author_provider(
    provider_name: str,
    timeout_seconds: float,
) -> AuthorProvider:
    if provider_name == "fake":
        return FakeAuthorProvider()
    if provider_name == "dblp":
        return DblpAuthorProvider(timeout_seconds=timeout_seconds)
    raise ValueError(f"Unsupported author provider: {provider_name}")
