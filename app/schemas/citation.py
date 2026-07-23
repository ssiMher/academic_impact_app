"""Citation workflow schemas."""

from typing import List

from pydantic import BaseModel

from app.schemas.provider import ProviderCitationEdge


class CitationDiscoveryResult(BaseModel):
    citations: List[ProviderCitationEdge]
