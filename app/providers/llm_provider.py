"""LLM provider selection."""

import os

from app.core.config import settings
from app.providers.base import LlmProvider
from app.providers.fake import FakeLlmProvider
from app.providers.implementations.openai_compatible_llm import OpenAICompatibleLlmProvider


def get_llm_provider() -> LlmProvider:
    provider_name = os.getenv("ACADEMIC_IMPACT_LLM_PROVIDER", settings.llm_provider)
    if provider_name == "fake":
        return FakeLlmProvider()
    if provider_name == "openai_compatible":
        return OpenAICompatibleLlmProvider(
            base_url=os.getenv("ACADEMIC_IMPACT_LLM_BASE_URL", settings.llm_base_url),
            api_key=os.getenv("ACADEMIC_IMPACT_LLM_API_KEY", settings.llm_api_key),
            model=os.getenv("ACADEMIC_IMPACT_LLM_MODEL", settings.llm_model),
            timeout_seconds=float(
                os.getenv(
                    "ACADEMIC_IMPACT_LLM_TIMEOUT_SECONDS",
                    str(settings.llm_timeout_seconds),
                )
            ),
            disable_thinking=os.getenv(
                "ACADEMIC_IMPACT_LLM_DISABLE_THINKING",
                str(settings.llm_disable_thinking).lower(),
            ).lower()
            in {"1", "true", "yes", "on"},
        )
    raise ValueError(f"Unsupported LLM provider: {provider_name}")
