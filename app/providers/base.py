"""Provider interfaces for external integrations."""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.schemas.llm import CitationAnalysisResponse, LlmCitationAnalysisRequest
from app.schemas.provider import (
    ProviderAuthorIdentity,
    ProviderCitationEdge,
    ProviderHealth,
    ProviderPublication,
)


class Provider(ABC):
    provider_name: str

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        raise NotImplementedError


class AuthorProvider(Provider):
    @abstractmethod
    def resolve_author(self, author_ref: str) -> ProviderAuthorIdentity:
        raise NotImplementedError


class CitationProvider(Provider):
    @abstractmethod
    def discover_citations(self, target_title: str) -> List[ProviderCitationEdge]:
        raise NotImplementedError


class MetadataProvider(Provider):
    @abstractmethod
    def resolve_publication(self, query: str) -> Optional[ProviderPublication]:
        raise NotImplementedError


class PdfProvider(Provider):
    @abstractmethod
    def locate_pdf(self, publication: ProviderPublication) -> Optional[str]:
        raise NotImplementedError


class LlmProvider(Provider):
    @abstractmethod
    def analyze_text(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def analyze_citation(
        self,
        request: LlmCitationAnalysisRequest,
    ) -> CitationAnalysisResponse:
        raise NotImplementedError
