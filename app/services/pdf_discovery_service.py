"""Discover and download only open-access PDF candidates."""

import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CitationEdge, DeepAnalysisQueueItem, PdfAsset, Publication
from app.models.constants import PDF_STATUS_REUSED
from app.pdf.arxiv import extract_arxiv_identifier, normalize_arxiv_identifier
from app.pdf.match import normalize_title_for_match, title_similarity
from app.pdf.publisher import PublisherInfo, classify_publisher_from_doi_or_url
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_inbox_service import (
    ACCESS_FAILED,
    ACCESS_MANUAL_DOWNLOAD_NEEDED,
    ACCESS_NO_PDF_FOUND,
    ACCESS_OPEN_ACCESS_DOWNLOADED,
    ACCESS_OPEN_ACCESS_AVAILABLE,
    ACCESS_REQUIRES_LOGIN,
)
from app.services.pdf_service import PdfService


logger = logging.getLogger(__name__)


@dataclass
class PdfCandidate:
    title: str
    doi: Optional[str]
    source: str
    url: str
    is_open_access: bool
    license: Optional[str]
    confidence: float
    requires_login: bool
    reason: str
    source_name: Optional[str] = None
    access_status: str = "unknown"
    can_auto_download: bool = False
    url_type: str = "landing_page"
    display_label: Optional[str] = None
    user_action_hint: str = ""


class DownloadFailure(Exception):
    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        self.message = message


class PdfDiscoveryService:
    def __init__(
        self,
        db: Session,
        *,
        timeout_seconds: float = 20.0,
        unpaywall_email: Optional[str] = None,
        unpaywall_timeout_seconds: Optional[float] = None,
    ) -> None:
        self.db = db
        self.timeout_seconds = timeout_seconds
        self.unpaywall_email = (
            settings.unpaywall_email
            if unpaywall_email is None
            else unpaywall_email
        ).strip()
        self.unpaywall_timeout_seconds = (
            settings.unpaywall_timeout_seconds
            if unpaywall_timeout_seconds is None
            else unpaywall_timeout_seconds
        )

    def discover_pdf_candidates_for_queue_item(
        self,
        item_id: int,
        *,
        include_remote_lookup: bool = False,
    ) -> List[PdfCandidate]:
        item = self.db.get(DeepAnalysisQueueItem, item_id)
        if item is None:
            return []
        publication = self.db.get(Publication, item.citing_publication_id)
        edge = self.db.get(CitationEdge, item.citation_edge_id)
        if self.clear_invalid_cached_arxiv_state(item, publication=publication, edge=edge):
            self.db.commit()
        candidates = self._edge_meta_candidates(edge, publication)
        arxiv = self._arxiv_candidate(publication, edge)
        if arxiv is not None:
            candidates.append(arxiv)
        if (
            include_remote_lookup
            and not any(candidate.can_auto_download for candidate in candidates)
        ):
            unpaywall = self._unpaywall_candidate(publication)
            if unpaywall is not None:
                candidates.append(unpaywall)
        if (
            include_remote_lookup
            and not any(candidate.can_auto_download for candidate in candidates)
            and self._should_search_arxiv(publication, edge)
        ):
            arxiv = self._search_arxiv_candidate(publication)
            if arxiv is not None:
                candidates.append(arxiv)
        publisher = self._publisher_info(publication, edge)
        if (
            publisher.landing_url
            and publisher.source != "arxiv"
            and publisher.publisher != "Publisher"
        ):
            candidates.append(
                self._publisher_candidate(item, publication, publisher, edge)
            )
        return self._deduplicate_candidates(candidates)

    def download_if_allowed(
        self,
        candidate: PdfCandidate,
        *,
        pdf_service: PdfService,
    ) -> Union[PdfAsset, DownloadFailure]:
        is_direct_pdf = (
            candidate.url_type == "direct_pdf"
            or self.classify_url_type(candidate.url) == "direct_pdf"
        )
        if not is_direct_pdf or candidate.requires_login or not candidate.is_open_access:
            return DownloadFailure("requires_login", "PDF requires login or manual download.")
        try:
            content, content_type = self._download(candidate.url)
        except DownloadFailure as failure:
            return failure
        if "html" in content_type.lower() or content.lstrip().lower().startswith(b"<!doctype html") or b"<html" in content[:512].lower():
            return DownloadFailure("requires_login", "Downloaded response is HTML, not a PDF.")
        if not content.startswith(b"%PDF"):
            return DownloadFailure("not_pdf", "Downloaded response does not start with %PDF.")
        return pdf_service.store_downloaded_pdf_asset(
            filename=self._filename_for_candidate(candidate),
            content=content,
            source_type=candidate.source,
            source_url=candidate.url,
            license=candidate.license,
        )

    def discover_and_download_for_queue_item(
        self,
        *,
        item_id: int,
        pdf_service: PdfService,
    ) -> dict:
        item = self.db.get(DeepAnalysisQueueItem, item_id)
        if item is None:
            return {"status": "failed", "reason": "queue_item_not_found"}
        if item.pdf_asset_id:
            item.pdf_discovery_status = "downloaded"
            item.pdf_access_status = ACCESS_OPEN_ACCESS_DOWNLOADED
            self.db.commit()
            return {"status": "skipped_existing_pdf"}
        candidates = self.discover_pdf_candidates_for_queue_item(
            item_id,
            include_remote_lookup=True,
        )
        if not candidates:
            item.pdf_discovery_status = "no_pdf_found"
            item.pdf_access_status = ACCESS_NO_PDF_FOUND
            self.db.commit()
            return {"status": "no_pdf_found"}
        candidate = next(
            (value for value in candidates if value.can_auto_download and value.url_type == "direct_pdf"),
            next((value for value in candidates if value.url_type == "landing_page"), candidates[0]),
        )
        item.pdf_source = candidate.source
        item.pdf_source_url = candidate.url
        if candidate.requires_login:
            item.pdf_discovery_status = "requires_login"
            item.pdf_access_status = ACCESS_REQUIRES_LOGIN
            item.publisher_landing_url = candidate.url
            item.publisher_name = candidate.display_label or candidate.source_name or self._publisher_name_for_candidate(candidate)
            item.requires_login_reason = candidate.reason
            self.db.commit()
            return {"status": "requires_login", "candidate": candidate}
        if not candidate.can_auto_download:
            item.pdf_discovery_status = "no_pdf_found"
            item.pdf_access_status = ACCESS_MANUAL_DOWNLOAD_NEEDED
            item.requires_login_reason = candidate.reason
            self.db.commit()
            return {"status": "no_pdf_found", "candidate": candidate}
        item.pdf_discovery_status = "found_open_access_pdf"
        item.pdf_access_status = ACCESS_OPEN_ACCESS_AVAILABLE
        result = self.download_if_allowed(candidate, pdf_service=pdf_service)
        if isinstance(result, DownloadFailure):
            item.pdf_discovery_status = "requires_login" if result.error_kind == "requires_login" else "failed"
            item.pdf_access_status = ACCESS_REQUIRES_LOGIN if result.error_kind == "requires_login" else ACCESS_FAILED
            self.db.commit()
            return {"status": item.pdf_discovery_status, "failure": result}
        item.pdf_asset_id = result.id
        item.pdf_readiness_status = PDF_STATUS_REUSED
        item.pdf_discovery_status = "downloaded"
        item.pdf_access_status = ACCESS_OPEN_ACCESS_DOWNLOADED
        item.pdf_source = result.source_type
        item.pdf_source_url = result.source_url
        self.db.commit()
        return {"status": "downloaded", "asset": result}

    def _publisher_name_for_candidate(self, candidate: PdfCandidate) -> str:
        combined = " ".join([candidate.source or "", candidate.url or "", candidate.doi or ""]).lower()
        if "acm" in combined or "10.1145" in combined:
            return "ACM"
        if "ieee" in combined or "10.1109" in combined:
            return "IEEE"
        if "springer" in combined:
            return "Springer"
        if "elsevier" in combined:
            return "Elsevier"
        return ""

    def _source_name_for_url(self, url: str, fallback: str) -> str:
        value = (url or "").lower()
        if "dl.acm.org" in value or "10.1145" in value:
            return "ACM Digital Library"
        if "ieeexplore.ieee.org" in value or "10.1109" in value:
            return "IEEE Xplore"
        if "arxiv.org" in value:
            return "arXiv"
        if "semanticscholar.org" in value:
            return "Semantic Scholar"
        if "openalex.org" in value:
            return "OpenAlex OA"
        if "doi.org" in value:
            return "DOI"
        return fallback

    def classify_url_type(self, url: str, metadata: Optional[dict] = None) -> str:
        declared = str((metadata or {}).get("url_type") or "").strip().lower()
        if declared in {"direct_pdf", "landing_page", "metadata_page"}:
            return declared
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
        if path.endswith(".pdf") or (host.endswith("arxiv.org") and path.startswith("/pdf/")):
            return "direct_pdf"
        if host.endswith("openalex.org") or host.endswith("semanticscholar.org"):
            return "metadata_page"
        return "landing_page"

    def _candidate_source(
        self,
        url: str,
        requested_source: str,
        *,
        arxiv_id: Optional[str],
    ) -> str:
        value = (url or "").lower()
        if arxiv_id:
            return "arxiv"
        if "openalex.org" in value:
            return "openalex"
        if "semanticscholar.org" in value:
            return "semantic_scholar"
        publisher = classify_publisher_from_doi_or_url(None, url)
        if publisher.publisher != "Publisher":
            return publisher.source
        return "openalex_oa" if requested_source.lower() == "arxiv" else requested_source

    def _publisher_info(
        self,
        publication: Optional[Publication],
        edge: Optional[CitationEdge],
    ) -> PublisherInfo:
        return classify_publisher_from_doi_or_url(
            publication.doi if publication else None,
            self._publisher_url(publication, edge),
        )

    def _publisher_candidate(
        self,
        item: DeepAnalysisQueueItem,
        publication: Optional[Publication],
        publisher: PublisherInfo,
        edge: Optional[CitationEdge],
    ) -> PdfCandidate:
        meta = self._edge_meta(edge)
        is_open_access = bool(meta.get("is_open_access"))
        requires_login = not is_open_access and publisher.source in {
            "acm_dl",
            "ieee_xplore",
            "springer",
            "elsevier",
        }
        return PdfCandidate(
            title=publication.title if publication else item.citing_paper_title,
            doi=publication.doi if publication else None,
            source=publisher.source,
            url=publisher.landing_url,
            is_open_access=is_open_access,
            license=meta.get("license") if is_open_access else None,
            confidence=0.9,
            requires_login=requires_login,
            reason=(
                "publisher_page_requires_login"
                if requires_login
                else (
                    "publisher_open_access_landing_page"
                    if is_open_access
                    else "publisher_landing_page"
                )
            ),
            source_name=publisher.publisher,
            access_status=(
                "requires_login"
                if requires_login
                else "open_access"
                if is_open_access
                else "unknown"
            ),
            can_auto_download=False,
            url_type="landing_page",
            display_label=publisher.publisher,
            user_action_hint=(
                "开放获取页面，但未提供可直接下载的 PDF 地址"
                if is_open_access
                else publisher.access_hint
            ),
        )

    def _deduplicate_candidates(self, candidates: List[PdfCandidate]) -> List[PdfCandidate]:
        by_url = {}
        for candidate in candidates:
            current = by_url.get(candidate.url)
            if current is None or self._candidate_priority(candidate) < self._candidate_priority(current):
                by_url[candidate.url] = candidate
        return sorted(by_url.values(), key=self._candidate_priority)

    def _unpaywall_candidate(
        self,
        publication: Optional[Publication],
    ) -> Optional[PdfCandidate]:
        if publication is None or not publication.doi or not self.unpaywall_email:
            return None
        doi = self._normalize_doi(publication.doi)
        if not doi:
            return None
        params = urllib.parse.urlencode({"email": self.unpaywall_email})
        encoded_doi = urllib.parse.quote(doi, safe="/")
        url = f"https://api.unpaywall.org/v2/{encoded_doi}?{params}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    f"{settings.app_name}/pdf-discovery "
                    f"(mailto:{self.unpaywall_email})"
                ),
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.unpaywall_timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                logger.warning("Unpaywall lookup failed for DOI %s: HTTP %s", doi, exc.code)
            return None
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            urllib.error.URLError,
            socket.timeout,
        ) as exc:
            logger.warning("Unpaywall lookup failed for DOI %s: %s", doi, exc)
            return None
        location = self._best_unpaywall_location(payload)
        if not location:
            return None
        pdf_url = str(location.get("url_for_pdf") or "").strip()
        landing_url = str(
            location.get("url_for_landing_page")
            or location.get("url")
            or ""
        ).strip()
        candidate_url = pdf_url or landing_url
        if not candidate_url:
            return None
        is_direct_pdf = bool(pdf_url)
        return PdfCandidate(
            title=publication.title,
            doi=doi,
            source="unpaywall",
            url=candidate_url,
            is_open_access=True,
            license=location.get("license"),
            confidence=0.9,
            requires_login=False,
            reason=(
                "unpaywall_open_access_pdf"
                if is_direct_pdf
                else "unpaywall_open_access_landing_page"
            ),
            source_name="Unpaywall",
            access_status="open_access",
            can_auto_download=is_direct_pdf,
            url_type="direct_pdf" if is_direct_pdf else "landing_page",
            display_label="Unpaywall 开放版本",
            user_action_hint=(
                "可自动下载开放 PDF"
                if is_direct_pdf
                else "Unpaywall 仅返回开放版本页面"
            ),
        )

    def _should_search_arxiv(
        self,
        publication: Optional[Publication],
        edge: Optional[CitationEdge],
    ) -> bool:
        if publication is None or not publication.title:
            return False
        if not self._publication_authors(publication):
            return False
        meta = self._edge_meta(edge)
        return bool(
            meta.get("is_open_access")
            and (
                meta.get("open_access_landing_url")
                or meta.get("url")
                or meta.get("source_url")
            )
        )

    def _search_arxiv_candidate(
        self,
        publication: Optional[Publication],
    ) -> Optional[PdfCandidate]:
        if publication is None:
            return None
        expected_authors = self._publication_authors(publication)
        if not publication.title or not expected_authors:
            return None
        query_title = normalize_title_for_match(publication.title)
        if not query_title:
            return None
        params = urllib.parse.urlencode(
            {
                "search_query": f'ti:"{query_title}"',
                "start": 0,
                "max_results": 5,
            }
        )
        request = urllib.request.Request(
            f"https://export.arxiv.org/api/query?{params}",
            headers={
                "Accept": "application/atom+xml",
                "User-Agent": (
                    f"{settings.app_name}/pdf-discovery"
                    + (
                        f" (mailto:{self.unpaywall_email})"
                        if self.unpaywall_email
                        else ""
                    )
                ),
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                root = ET.fromstring(response.read())
        except (
            ET.ParseError,
            UnicodeError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            socket.timeout,
        ) as exc:
            logger.warning(
                "arXiv title lookup failed for %s: %s",
                publication.title,
                exc,
            )
            return None

        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        required_author_matches = min(2, len(expected_authors))
        for entry in root.findall("atom:entry", namespace):
            entry_title = entry.findtext("atom:title", default="", namespaces=namespace)
            score = title_similarity(publication.title, entry_title)
            if score < 0.97:
                continue
            entry_authors = {
                normalize_title_for_match(
                    author.findtext("atom:name", default="", namespaces=namespace)
                )
                for author in entry.findall("atom:author", namespace)
            }
            entry_authors.discard("")
            if len(expected_authors & entry_authors) < required_author_matches:
                continue
            identifier = extract_arxiv_identifier(
                entry.findtext("atom:id", default="", namespaces=namespace)
            )
            if not identifier:
                continue
            return PdfCandidate(
                title=publication.title,
                doi=publication.doi,
                source="arxiv",
                url=f"https://arxiv.org/pdf/{identifier}.pdf",
                is_open_access=True,
                license="arXiv",
                confidence=min(score, 0.99),
                requires_login=False,
                reason="arxiv_title_author_match",
                source_name="arXiv",
                access_status="open_access",
                can_auto_download=True,
                url_type="direct_pdf",
                display_label="arXiv",
                user_action_hint="通过标题和作者匹配，可自动下载开放 PDF",
            )
        return None

    @staticmethod
    def _publication_authors(publication: Publication) -> set:
        try:
            values = json.loads(publication.authors_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return set()
        if not isinstance(values, list):
            return set()
        authors = set()
        for value in values:
            if isinstance(value, dict):
                value = value.get("name") or value.get("display_name") or ""
            normalized = normalize_title_for_match(str(value or ""))
            if normalized:
                authors.add(normalized)
        return authors

    def _best_unpaywall_location(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or not payload.get("is_oa"):
            return {}
        locations = [
            payload.get("best_oa_location"),
            *(payload.get("oa_locations") or []),
        ]
        valid_locations = [
            location
            for location in locations
            if isinstance(location, dict)
        ]
        return next(
            (
                location
                for location in valid_locations
                if location.get("url_for_pdf")
            ),
            valid_locations[0] if valid_locations else {},
        )

    def _normalize_doi(self, value: str) -> str:
        doi = (value or "").strip()
        lowered = doi.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if lowered.startswith(prefix):
                return doi[len(prefix):].strip()
        return doi

    def _candidate_priority(self, candidate: PdfCandidate) -> tuple:
        return (
            0 if candidate.can_auto_download and candidate.url_type == "direct_pdf" else 1
            if candidate.url_type == "landing_page" else 2,
            -candidate.confidence,
        )

    def _edge_meta_candidates(self, edge: Optional[CitationEdge], publication: Optional[Publication]) -> List[PdfCandidate]:
        if edge is None or not edge.edge_meta_json:
            return []
        try:
            meta = json.loads(edge.edge_meta_json)
        except json.JSONDecodeError:
            return []
        candidates = []
        for key in (
            "pdf_url",
            "open_access_pdf_url",
            "oa_pdf_url",
            "open_access_landing_url",
        ):
            url = str(meta.get(key) or "").strip()
            if url:
                arxiv_id = extract_arxiv_identifier(url)
                if "arxiv.org" in url.lower() and not arxiv_id:
                    continue
                url_type = self.classify_url_type(url, meta)
                is_open_access = bool(meta.get("is_open_access", True))
                can_auto_download = url_type == "direct_pdf" and is_open_access
                access_status = (
                    "open_access"
                    if is_open_access and url_type != "metadata_page"
                    else (
                        "requires_login"
                        if (
                            url_type == "landing_page"
                            and self._looks_like_restricted_publisher(
                                publication,
                                edge,
                            )
                        )
                        else "unknown"
                    )
                )
                requested_source = str(meta.get("pdf_source") or "openalex_oa")
                source = self._candidate_source(url, requested_source, arxiv_id=arxiv_id)
                publisher = classify_publisher_from_doi_or_url(
                    publication.doi if publication else None,
                    url,
                )
                display_label = self._source_name_for_url(url, source or "OpenAlex")
                if url_type == "landing_page" and publisher.publisher != "Publisher":
                    display_label = publisher.publisher
                candidates.append(
                    PdfCandidate(
                        title=publication.title if publication else "",
                        doi=publication.doi if publication else None,
                        source=source,
                        url=url,
                        is_open_access=is_open_access,
                        license=meta.get("license"),
                        confidence=0.95,
                        requires_login=access_status == "requires_login",
                        reason=(
                            "open_access_pdf_found"
                            if can_auto_download
                            else "metadata_page_not_direct_pdf"
                            if url_type == "metadata_page"
                            else "publisher_page_requires_login"
                            if access_status == "requires_login"
                            else "not_a_direct_pdf_url"
                        ),
                        source_name=display_label,
                        access_status=access_status,
                        can_auto_download=can_auto_download,
                        url_type=url_type,
                        display_label=display_label,
                        user_action_hint=(
                            "可自动下载开放 PDF"
                            if can_auto_download
                            else "该链接仅提供元数据，请使用出版社或 DOI 页面"
                            if url_type == "metadata_page"
                            else publisher.access_hint
                        ),
                    )
                )
        return candidates

    def _arxiv_candidate(
        self,
        publication: Optional[Publication],
        edge: Optional[CitationEdge] = None,
    ) -> Optional[PdfCandidate]:
        if publication is None:
            return None
        arxiv_id = self._publication_arxiv_id(publication, edge)
        if not arxiv_id:
            return None
        return PdfCandidate(
            title=publication.title,
            doi=publication.doi,
            source="arxiv",
            url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            is_open_access=True,
            license="arXiv",
            confidence=0.95,
            requires_login=False,
            reason="arxiv_identifier",
            source_name="arXiv",
            access_status="open_access",
            can_auto_download=True,
            url_type="direct_pdf",
            display_label="arXiv",
            user_action_hint="可自动下载开放 PDF",
        )

    def _extract_arxiv_id(self, value: str) -> Optional[str]:
        return extract_arxiv_identifier(value)

    def _publication_arxiv_id(
        self,
        publication: Optional[Publication],
        edge: Optional[CitationEdge] = None,
    ) -> Optional[str]:
        if publication is not None:
            for value in (
                publication.doi,
                publication.semantic_scholar_id,
                publication.openalex_id,
                publication.dblp_id,
            ):
                identifier = extract_arxiv_identifier(value or "")
                if identifier:
                    return identifier
        meta = self._edge_meta(edge)
        for key in ("arxiv_id", "arxiv_identifier"):
            identifier = normalize_arxiv_identifier(str(meta.get(key) or ""))
            if identifier:
                return identifier
        for key in ("arxiv_url", "url", "source_url", "landing_page_url"):
            identifier = extract_arxiv_identifier(str(meta.get(key) or ""))
            if identifier:
                return identifier
        return None

    def clear_invalid_cached_arxiv_state(
        self,
        item: DeepAnalysisQueueItem,
        *,
        publication: Optional[Publication] = None,
        edge: Optional[CitationEdge] = None,
    ) -> bool:
        """Remove stale arXiv cache values that cannot identify an arXiv record."""
        changed = self._clear_invalid_edge_arxiv_metadata(edge)
        cached_as_arxiv = (item.pdf_source or "").lower() == "arxiv"
        valid_cached_url = extract_arxiv_identifier(item.pdf_source_url or "")
        valid_metadata_id = self._publication_arxiv_id(publication, edge)
        if cached_as_arxiv and not (valid_cached_url or valid_metadata_id):
            item.pdf_source = "publisher_candidate" if publication and publication.doi else None
            item.pdf_source_url = None
            item.pdf_discovery_status = "no_pdf_found"
            item.pdf_access_status = ACCESS_MANUAL_DOWNLOAD_NEEDED
            item.requires_login_reason = "invalid_arxiv_identifier_removed"
            changed = True
        if item.publisher_landing_url and "arxiv.org" in item.publisher_landing_url.lower():
            if not extract_arxiv_identifier(item.publisher_landing_url):
                item.publisher_landing_url = None
                changed = True
        return changed

    def _clear_invalid_edge_arxiv_metadata(self, edge: Optional[CitationEdge]) -> bool:
        meta = self._edge_meta(edge)
        if not meta:
            return False
        changed = False
        for key in ("arxiv_id", "arxiv_identifier"):
            if meta.get(key) and not normalize_arxiv_identifier(str(meta[key])):
                meta.pop(key, None)
                changed = True
        if str(meta.get("pdf_source") or "").lower() == "arxiv":
            pdf_url = str(
                meta.get("pdf_url")
                or meta.get("open_access_pdf_url")
                or meta.get("oa_pdf_url")
                or ""
            )
            explicit_id = next(
                (
                    normalize_arxiv_identifier(str(meta.get(key) or ""))
                    for key in ("arxiv_id", "arxiv_identifier")
                    if meta.get(key)
                ),
                None,
            )
            if not (extract_arxiv_identifier(pdf_url) or explicit_id):
                meta["pdf_source"] = "unknown"
                changed = True
        if changed and edge is not None:
            edge.edge_meta_json = json.dumps(meta, ensure_ascii=False)
        return changed

    def _edge_meta(self, edge: Optional[CitationEdge]) -> dict:
        if edge is None or not edge.edge_meta_json:
            return {}
        try:
            value = json.loads(edge.edge_meta_json)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _looks_like_restricted_publisher(self, publication: Optional[Publication], edge: Optional[CitationEdge]) -> bool:
        combined = " ".join([
            publication.doi or "" if publication else "",
            publication.venue or "" if publication else "",
            edge.edge_meta_json or "" if edge and edge.edge_meta_json else "",
        ]).lower()
        return any(
            token in combined
            for token in [
                "10.1145",
                "10.1109",
                "ieee",
                "acm",
                "dl.acm.org",
                "ieeexplore",
                "ieeexplore.ieee.org",
            ]
        )

    def _publisher_url(self, publication: Optional[Publication], edge: Optional[CitationEdge]) -> str:
        if edge and edge.edge_meta_json:
            try:
                meta = json.loads(edge.edge_meta_json)
            except json.JSONDecodeError:
                meta = {}
            for key in ("url", "source_url", "landing_page_url"):
                if meta.get(key):
                    return str(meta[key])
        if publication and publication.doi:
            return f"https://doi.org/{publication.doi}"
        return ""

    def _download(self, url: str) -> Tuple[bytes, str]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/pdf",
                "User-Agent": f"{settings.app_name}/pdf-discovery (mailto:local)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                content = response.read(settings.pdf_max_upload_bytes + 1)
        except socket.timeout:
            raise DownloadFailure("timeout", "PDF download timed out.")
        except urllib.error.URLError as exc:
            raise DownloadFailure("network_error", str(exc))
        if len(content) > settings.pdf_max_upload_bytes:
            raise DownloadFailure("file_too_large", "PDF is larger than configured max upload size.")
        return content, content_type

    def _filename_for_candidate(self, candidate: PdfCandidate) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate.title or "downloaded").strip("-")
        return f"{safe[:80] or 'downloaded'}.pdf"


def get_pdf_discovery_service(db: Session) -> PdfDiscoveryService:
    return PdfDiscoveryService(db, timeout_seconds=settings.provider_timeout_seconds)
