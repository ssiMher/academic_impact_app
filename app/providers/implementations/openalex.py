"""OpenAlex metadata and citation provider."""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from app.providers.base import CitationProvider, MetadataProvider
from app.providers.errors import ProviderErrorCode, ProviderException
from app.schemas.provider import ProviderCitationEdge, ProviderHealth, ProviderPublication


class OpenAlexProvider(CitationProvider, MetadataProvider):
    provider_name = "openalex"
    base_url = "https://api.openalex.org"

    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.last_citation_expansion: dict = {}

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="OpenAlex provider is configured.",
        )

    def discover_citations(self, target_title: str) -> List[ProviderCitationEdge]:
        publication = self.resolve_paper(target_title)
        if publication is None:
            raise self._exception(ProviderErrorCode.NOT_FOUND, "OpenAlex paper was not found.")
        return self.list_citing_papers(publication, limit=100)

    def resolve_publication(self, query: str) -> Optional[ProviderPublication]:
        return self.resolve_paper(query)

    def enrich_publication(self, ref: str) -> Optional[ProviderPublication]:
        return self.resolve_paper(ref)

    def resolve_paper(self, paper_ref: str) -> Optional[ProviderPublication]:
        ref = (paper_ref or "").strip()
        if not ref:
            return None
        if self._looks_like_openalex_work(ref):
            payload = self._read_json(f"{self.base_url}/works/{self._openalex_work_id(ref)}")
            return self._publication_from_work(payload)
        if self._looks_like_doi(ref):
            doi = self._normalize_doi(ref)
            params = urllib.parse.urlencode({"filter": f"doi:{doi}", "per-page": 1})
            payload = self._read_json(f"{self.base_url}/works?{params}")
            return self._first_publication(payload)
        params = urllib.parse.urlencode({"search": ref, "per-page": 1})
        payload = self._read_json(f"{self.base_url}/works?{params}")
        return self._first_publication(payload)

    def list_citing_papers(
        self,
        publication: ProviderPublication,
        limit: int = 100,
    ) -> List[ProviderCitationEdge]:
        work_id = self._openalex_work_id(publication.source_url or "")
        if not work_id:
            resolved = self.resolve_paper(publication.doi or publication.title)
            if resolved is not None:
                publication = resolved
            work_id = self._openalex_work_id(resolved.source_url or "") if resolved else ""
        if not work_id:
            raise self._exception(ProviderErrorCode.NOT_FOUND, "OpenAlex work id was not found.")
        limit = max(0, int(limit or 100))
        page_size = min(100, limit) if limit else 100
        cited_by_api_url = publication.openalex_cited_by_api_url or f"{self.base_url}/works?filter=cites:{work_id}"
        cited_by_count = publication.openalex_cited_by_count
        results = []
        cursor = "*"
        cursor_pages = 0
        while True:
            remaining = limit - len(results) if limit else page_size
            if limit and remaining <= 0:
                break
            current_page_size = min(page_size, remaining) if limit else page_size
            page_url = self._with_query_params(
                cited_by_api_url,
                {
                    "per-page": current_page_size,
                    "cursor": cursor,
                },
            )
            payload = self._read_json(page_url)
            meta = payload.get("meta") or {}
            if cited_by_count is None and isinstance(meta, dict):
                count = meta.get("count")
                if isinstance(count, int):
                    cited_by_count = count
            page_results = payload.get("results", [])
            if not isinstance(page_results, list):
                raise self._exception(
                    ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                    "OpenAlex citing papers response has invalid results.",
                )
            cursor_pages += 1
            if not page_results:
                break
            results.extend(work for work in page_results if isinstance(work, dict))
            next_cursor = str(meta.get("next_cursor") or "") if isinstance(meta, dict) else ""
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        if limit:
            results = results[:limit]
        fetched_count = len(results)
        complete = bool(
            cited_by_count is None
            or fetched_count >= cited_by_count
            or (limit and fetched_count < limit)
        )
        self.last_citation_expansion = {
            "provider": self.provider_name,
            "openalex_work_id": work_id,
            "openalex_cited_by_count": cited_by_count,
            "cited_by_api_url": cited_by_api_url,
            "fetched_count": fetched_count,
            "limit_per_publication": limit,
            "cursor_pages": cursor_pages,
            "expansion_complete": complete,
        }
        return [
            ProviderCitationEdge(
                target_title=publication.title,
                citing_paper=self._publication_from_work(work),
            )
            for work in results
            if isinstance(work, dict)
        ]

    def _first_publication(self, payload: dict) -> Optional[ProviderPublication]:
        results = payload.get("results", [])
        if not results:
            return None
        if not isinstance(results, list) or not isinstance(results[0], dict):
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "OpenAlex response has invalid results.",
            )
        return self._publication_from_work(results[0])

    def _publication_from_work(self, work: dict) -> ProviderPublication:
        title = str(work.get("title") or work.get("display_name") or "").strip()
        if not title:
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "OpenAlex work is missing title.",
            )
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        return ProviderPublication(
            title=title,
            year=work.get("publication_year"),
            venue=source.get("display_name"),
            doi=self._normalize_doi(work.get("doi") or ""),
            openalex_id=self._openalex_work_id(work.get("id") or ""),
            openalex_cited_by_count=work.get("cited_by_count"),
            openalex_cited_by_api_url=work.get("cited_by_api_url"),
            authors=self._authors_from_work(work),
            source_url=work.get("id"),
        )

    def _with_query_params(self, base_url: str, params: dict) -> str:
        parsed = urllib.parse.urlparse(base_url)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        for key, value in params.items():
            query[key] = str(value)
        return urllib.parse.urlunparse(
            parsed._replace(query=urllib.parse.urlencode(query))
        )

    def _authors_from_work(self, work: dict) -> List[str]:
        authors = []
        for authorship in work.get("authorships") or []:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author") or {}
            name = str(author.get("display_name") or "").strip()
            if name:
                authors.append(name)
        return authors

    def _read_json(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            raise self._exception(ProviderErrorCode.TIMEOUT, "OpenAlex request timed out.") from exc
        except urllib.error.HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "OpenAlex returned invalid JSON.",
            ) from exc
        except urllib.error.URLError as exc:
            raise self._exception(
                ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                "OpenAlex network request failed.",
            ) from exc

    def _map_http_error(self, exc: urllib.error.HTTPError) -> ProviderException:
        if exc.code == 404:
            return self._exception(ProviderErrorCode.NOT_FOUND, "OpenAlex resource was not found.")
        if exc.code == 429:
            return self._exception(ProviderErrorCode.RATE_LIMIT, "OpenAlex rate limit exceeded.")
        if 500 <= exc.code <= 599:
            return self._exception(
                ProviderErrorCode.TRANSIENT_PROVIDER_ERROR,
                "OpenAlex returned a transient server error.",
            )
        return self._exception(
            ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
            f"OpenAlex returned HTTP {exc.code}.",
        )

    def _looks_like_openalex_work(self, value: str) -> bool:
        return bool(self._openalex_work_id(value))

    def _openalex_work_id(self, value: str) -> str:
        raw = (value or "").strip().rstrip("/")
        if not raw:
            return ""
        if raw.startswith("https://openalex.org/"):
            raw = raw.rsplit("/", 1)[-1]
        return raw if raw.upper().startswith("W") else ""

    def _looks_like_doi(self, value: str) -> bool:
        normalized = self._normalize_doi(value)
        return normalized.startswith("10.") and "/" in normalized

    def _normalize_doi(self, value: str) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        lowered = raw.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if lowered.startswith(prefix):
                return raw[len(prefix):]
        return raw

    def _exception(self, code: ProviderErrorCode, message: str) -> ProviderException:
        return ProviderException(code=code, message=message, provider_name=self.provider_name)
