"""Provider-facing normalized schemas."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ProviderErrorCode(str, Enum):
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    TRANSIENT_PROVIDER_ERROR = "transient_provider_error"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_SCHEMA_ERROR = "provider_schema_error"
    TRANSIENT_NETWORK_ERROR = "transient_network_error"
    UNKNOWN = "unknown"


class ProviderHealth(BaseModel):
    provider_name: str
    ok: bool
    message: str = ""


class ProviderError(BaseModel):
    provider_name: str
    code: ProviderErrorCode
    message: str
    is_retryable: bool = False


class ProviderPublication(BaseModel):
    title: str
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    openalex_id: Optional[str] = None
    openalex_cited_by_count: Optional[int] = None
    openalex_cited_by_api_url: Optional[str] = None
    open_access_pdf_url: Optional[str] = None
    open_access_landing_url: Optional[str] = None
    open_access_license: Optional[str] = None
    open_access_source: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    citation_contexts: List[str] = Field(default_factory=list)


class ProviderAuthorIdentity(BaseModel):
    display_name: str
    dblp_id: Optional[str] = None
    openalex_id: Optional[str] = None
    scopus_author_id: Optional[str] = None
    publications: List[ProviderPublication] = Field(default_factory=list)


@dataclass
class DblpAuthorCandidate:
    pid: str
    name: str
    aliases: List[str] = field(default_factory=list)
    affiliations: List[str] = field(default_factory=list)
    dblp_url: str = ""
    publication_count: Optional[int] = None
    recent_publications: List[str] = field(default_factory=list)
    recent_venues: List[str] = field(default_factory=list)
    short_description: str = ""


class ProviderCitationEdge(BaseModel):
    target_title: Optional[str] = None
    citing_paper: ProviderPublication
