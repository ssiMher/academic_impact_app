"""DBLP author provider."""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from app.legacy.adapters.dblp_normalize_adapter import normalize_dblp_id
from app.providers.base import AuthorProvider
from app.providers.errors import ProviderErrorCode, ProviderException
from app.schemas.provider import ProviderAuthorIdentity, ProviderHealth, ProviderPublication


class DblpAuthorProvider(AuthorProvider):
    provider_name = "dblp"

    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="DBLP author provider is configured.",
        )

    def search_authors(self, query: str, limit: int = 5) -> List[ProviderAuthorIdentity]:
        params = urllib.parse.urlencode({"q": query, "format": "json", "h": limit})
        payload = self._read_json(f"https://dblp.org/search/author/api?{params}")
        hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        identities = []
        for hit in hits:
            info = hit.get("info", {}) if isinstance(hit, dict) else {}
            pid = self.normalize_author_ref(str(info.get("urlpt") or info.get("url") or ""))
            name = str(info.get("author") or "").strip()
            if name:
                identities.append(ProviderAuthorIdentity(display_name=name, dblp_id=pid or None))
        return identities

    def resolve_author(self, author_ref: str) -> ProviderAuthorIdentity:
        pid = self.normalize_author_ref(author_ref)
        if not pid:
            candidates = self.search_authors(author_ref, limit=1)
            if not candidates:
                raise self._exception(ProviderErrorCode.NOT_FOUND, "DBLP author was not found.")
            pid = candidates[0].dblp_id or ""
        return self.list_publications(
            ProviderAuthorIdentity(display_name="待解析", dblp_id=pid)
        )

    def resolve_author_name_by_pid(self, dblp_pid: str) -> Optional[str]:
        pid = self.normalize_author_ref(dblp_pid)
        if not pid:
            return None
        xml_text = self._read_text(f"https://dblp.org/pid/{pid}.xml")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "DBLP returned invalid author XML.",
            ) from exc
        person = root.find("person")
        if person is not None:
            person_name = (person.attrib.get("name") or "").strip()
            if person_name and not self._looks_like_pid(person_name):
                return person_name
        return self._fallback_name_from_author_pid(root, pid)

    def list_publications(self, author_identity: ProviderAuthorIdentity) -> ProviderAuthorIdentity:
        pid = self.normalize_author_ref(author_identity.dblp_id or "")
        if not pid:
            raise self._exception(ProviderErrorCode.NOT_FOUND, "DBLP author pid is missing.")
        xml_text = self._read_text(f"https://dblp.org/pid/{pid}.xml")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "DBLP returned invalid author XML.",
            ) from exc

        person = root.find("person")
        raw_display_name = (
            person.attrib.get("name")
            if person is not None
            else author_identity.display_name
        ) or author_identity.display_name
        display_name = (
            raw_display_name
            if raw_display_name and raw_display_name != pid and not self._looks_like_pid(raw_display_name)
            else "待解析"
        )
        publications = []
        for record in root.findall("r"):
            child = next(iter(record), None)
            if child is None:
                continue
            publication = self._publication_from_record(child)
            if publication is not None:
                publications.append(publication)
        if display_name == "待解析":
            fallback_name = self._fallback_name_from_author_pid(root, pid)
            if fallback_name:
                display_name = fallback_name
        return ProviderAuthorIdentity(
            display_name=display_name,
            dblp_id=pid,
            publications=publications,
        )

    def normalize_author_ref(self, author_ref: str) -> str:
        normalized = normalize_dblp_id(author_ref)
        if normalized.startswith("pid/"):
            normalized = normalized[len("pid/") :]
        return normalized.strip("/")

    def _publication_from_record(self, record) -> Optional[ProviderPublication]:
        title = self._text(record, "title").rstrip(".").strip()
        if not title:
            return None
        year = self._safe_int(self._text(record, "year"))
        venue = self._text(record, "journal") or self._text(record, "booktitle")
        ee_values = [node.text or "" for node in record.findall("ee")]
        doi = self._extract_doi(ee_values)
        return ProviderPublication(
            title=title,
            year=year,
            venue=venue or None,
            doi=doi,
            authors=[node.text or "" for node in record.findall("author") if node.text],
            source_url=ee_values[0] if ee_values else None,
        )

    def _read_json(self, url: str) -> dict:
        try:
            return json.loads(self._read_text(url))
        except json.JSONDecodeError as exc:
            raise self._exception(
                ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                "DBLP returned invalid JSON.",
            ) from exc

    def _read_text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except socket.timeout as exc:
            raise self._exception(ProviderErrorCode.TIMEOUT, "DBLP request timed out.") from exc
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise self._exception(ProviderErrorCode.NOT_FOUND, "DBLP author was not found.") from exc
            raise self._exception(
                ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                f"DBLP request failed with HTTP {exc.code}.",
            ) from exc
        except urllib.error.URLError as exc:
            raise self._exception(
                ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                "DBLP network request failed.",
            ) from exc

    def _text(self, record, tag: str) -> str:
        node = record.find(tag)
        return (node.text or "").strip() if node is not None else ""

    def _safe_int(self, value: str) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_doi(self, values: List[str]) -> Optional[str]:
        for value in values:
            lowered = value.lower()
            marker = "doi.org/"
            if marker in lowered:
                return value[lowered.index(marker) + len(marker):].strip()
        return None

    def _exception(self, code: ProviderErrorCode, message: str) -> ProviderException:
        return ProviderException(code=code, message=message, provider_name=self.provider_name)

    def _looks_like_pid(self, value: str) -> bool:
        return bool(value and value.count("/") == 1 and all(part.isdigit() for part in value.split("/")))

    def _fallback_name_from_author_pid(self, root, pid: str) -> Optional[str]:
        for author in root.findall(".//author"):
            author_pid = self.normalize_author_ref(author.attrib.get("pid", ""))
            if author_pid == pid:
                author_name = (author.text or "").strip()
                if author_name and not self._looks_like_pid(author_name):
                    return author_name
        return None
