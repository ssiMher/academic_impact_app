"""Provider configuration health service."""

import os

from app.core.config import settings
from app.providers.author_provider import get_author_provider
from app.providers.citation_provider import get_citation_provider
from app.providers.llm_provider import get_llm_provider
from app.providers.metadata_provider import get_metadata_provider


class ProviderHealthService:
    def all_provider_status(self) -> dict:
        return {
            "author_provider": self.author_provider_status(),
            "citation_provider": self.citation_provider_status(),
            "metadata_provider": self.metadata_provider_status(),
            "llm_provider": self.llm_provider_status(),
        }

    def author_provider_status(self) -> dict:
        provider_name = os.getenv("ACADEMIC_IMPACT_AUTHOR_PROVIDER", settings.author_provider)
        return self._basic_status(provider_name, get_author_provider().health_check())

    def citation_provider_status(self) -> dict:
        provider_name = os.getenv("ACADEMIC_IMPACT_CITATION_PROVIDER", settings.citation_provider)
        return self._basic_status(provider_name, get_citation_provider().health_check())

    def metadata_provider_status(self) -> dict:
        provider_name = os.getenv("ACADEMIC_IMPACT_METADATA_PROVIDER", settings.metadata_provider)
        return self._basic_status(provider_name, get_metadata_provider().health_check())

    def llm_provider_status(self) -> dict:
        provider_name = os.getenv("ACADEMIC_IMPACT_LLM_PROVIDER", settings.llm_provider)
        provider = get_llm_provider()
        health = provider.health_check()
        status = self._basic_status(provider_name, health)
        status.update(
            {
                "base_url_configured": bool(
                    os.getenv("ACADEMIC_IMPACT_LLM_BASE_URL", settings.llm_base_url)
                ),
                "api_key_configured": bool(
                    os.getenv("ACADEMIC_IMPACT_LLM_API_KEY", settings.llm_api_key)
                ),
                "model": os.getenv("ACADEMIC_IMPACT_LLM_MODEL", settings.llm_model),
                "timeout_seconds": float(
                    os.getenv(
                        "ACADEMIC_IMPACT_LLM_TIMEOUT_SECONDS",
                        str(settings.llm_timeout_seconds),
                    )
                ),
                "disable_thinking": os.getenv(
                    "ACADEMIC_IMPACT_LLM_DISABLE_THINKING",
                    str(settings.llm_disable_thinking).lower(),
                ).lower()
                in {"1", "true", "yes", "on"},
            }
        )
        return status

    def _basic_status(self, configured_provider: str, health) -> dict:
        return {
            "provider": configured_provider,
            "provider_name": health.provider_name,
            "ok": health.ok,
            "message": health.message,
            "configured": health.ok,
            "recent_error": None if health.ok else health.message,
        }
