"""DBLP author provider."""

import copy
import http.client
import json
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from pypinyin import Style, lazy_pinyin

from app.providers.base import AuthorProvider
from app.providers.errors import ProviderErrorCode, ProviderException
from app.schemas.provider import (
    DblpAuthorCandidate,
    ProviderAuthorIdentity,
    ProviderHealth,
    ProviderPublication,
)


_DBLP_PID_PATTERN = re.compile(r"^\d{2,3}/\d+(?:-\d+)?$")
_CJK_CHARACTER_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_COMPOUND_CHINESE_SURNAMES = {
    "欧阳",
    "太史",
    "端木",
    "上官",
    "司马",
    "东方",
    "独孤",
    "南宫",
    "万俟",
    "闻人",
    "夏侯",
    "诸葛",
    "尉迟",
    "公羊",
    "赫连",
    "澹台",
    "皇甫",
    "宗政",
    "濮阳",
    "公冶",
    "太叔",
    "申屠",
    "公孙",
    "慕容",
    "仲孙",
    "钟离",
    "长孙",
    "宇文",
    "司徒",
    "鲜于",
    "司空",
    "闾丘",
    "子车",
    "亓官",
    "司寇",
    "巫马",
    "公西",
    "颛孙",
    "壤驷",
    "公良",
    "漆雕",
    "乐正",
    "宰父",
    "谷梁",
    "拓跋",
    "夹谷",
    "轩辕",
    "令狐",
    "段干",
    "百里",
    "呼延",
    "东郭",
    "南门",
    "羊舌",
    "微生",
}
_DBLP_BASE_URLS = (
    "https://dblp.org",
    "https://dblp.dagstuhl.de",
    "https://dblp.uni-trier.de",
)
_DBLP_HOSTS = {
    "dblp.org",
    "www.dblp.org",
    "dblp.dagstuhl.de",
    "dblp.uni-trier.de",
}
_DBLP_FAILOVER_TIMEOUT_SECONDS = 5.0


class InvalidDblpPidError(ValueError):
    """Raised when a value is not an explicit, supported DBLP PID."""


class DblpAuthorNotFoundError(ProviderException):
    """Raised when DBLP has no profile for a validated PID."""


class DblpAuthorSearchError(ProviderException):
    """Raised when DBLP author search returns an unusable response."""


class DblpProviderUnavailableError(ProviderException):
    """Raised when DBLP cannot currently serve a request."""


def extract_dblp_pid(author_ref: str) -> Optional[str]:
    raw = (author_ref or "").strip()
    if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return None

    raw = re.sub(r"^dblp\s*:\s*", "", raw, flags=re.I).strip()
    if raw.lower().startswith("pid/"):
        raw = raw[4:]

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in _DBLP_HOSTS:
            return None
        path = parsed.path.strip("/")
        if not path.startswith("pid/"):
            return None
        raw = path[4:]

    raw = re.sub(r"\.(?:html|xml)$", "", raw, flags=re.I).strip("/")
    if not _DBLP_PID_PATTERN.fullmatch(raw):
        return None
    return raw


def is_dblp_pid(author_ref: str) -> bool:
    return extract_dblp_pid(author_ref) is not None


def author_name_to_dblp_query(author_name: str) -> str:
    normalized_name = (author_name or "").strip()
    if not _CJK_CHARACTER_PATTERN.search(normalized_name):
        return normalized_name

    chinese_name = "".join(_CJK_CHARACTER_PATTERN.findall(normalized_name))
    syllables = lazy_pinyin(
        chinese_name,
        style=Style.NORMAL,
        strict=False,
        errors="ignore",
    )
    if not syllables:
        return ""

    surname_length = (
        2
        if len(chinese_name) > 2
        and chinese_name[:2] in _COMPOUND_CHINESE_SURNAMES
        else 1
    )
    surname = " ".join(
        syllable.capitalize() for syllable in syllables[:surname_length]
    )
    given_name = " ".join(
        syllable.capitalize() for syllable in syllables[surname_length:]
    )
    return f"{given_name} {surname}".strip() if given_name else surname


class DblpAuthorProvider(AuthorProvider):
    provider_name = "dblp"

    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self._preferred_base_url = _DBLP_BASE_URLS[0]
        self._identity_cache = {}
        self._complete_identity_pids = set()
        self._identity_cache_lock = threading.Lock()

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="DBLP author provider is configured.",
        )

    def search_authors(
        self,
        query: str,
        limit: int = 10,
    ) -> List[DblpAuthorCandidate]:
        normalized_query = (query or "").strip()
        if (
            not normalized_query
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in normalized_query
            )
        ):
            raise DblpAuthorSearchError(
                code=ProviderErrorCode.INVALID_RESPONSE,
                message="DBLP author search query is invalid.",
                provider_name=self.provider_name,
            )
        search_query = author_name_to_dblp_query(normalized_query)
        if not search_query:
            raise DblpAuthorSearchError(
                code=ProviderErrorCode.INVALID_RESPONSE,
                message="DBLP author search query could not be converted.",
                provider_name=self.provider_name,
            )
        safe_limit = max(1, min(int(limit), 50))
        params = urllib.parse.urlencode(
            {"q": search_query, "format": "json", "h": safe_limit}
        )
        payload = self._read_json(f"https://dblp.org/search/author/api?{params}")
        hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        if not isinstance(hits, list):
            raise DblpAuthorSearchError(
                code=ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                message="DBLP returned invalid author search results.",
                provider_name=self.provider_name,
            )
        search_results = []
        for hit in hits:
            info = hit.get("info", {}) if isinstance(hit, dict) else {}
            if not isinstance(info, dict):
                continue
            pid = extract_dblp_pid(str(info.get("urlpt") or info.get("url") or ""))
            name = self._search_author_name(info.get("author"))
            if pid and name:
                search_results.append(
                    (pid, name, self._search_affiliations(info.get("notes")))
                )
        if not search_results:
            return []

        for pid, name, _ in search_results:
            self._cache_identity(
                ProviderAuthorIdentity(
                    display_name=name,
                    dblp_id=pid,
                    publications=[],
                ),
                complete=False,
            )
        candidates = [
            self._basic_candidate(pid, name, affiliations)
            for pid, name, affiliations in search_results
        ]
        return candidates

    def resolve_author(self, author_ref: str) -> ProviderAuthorIdentity:
        pid = extract_dblp_pid(author_ref)
        if not pid:
            raise InvalidDblpPidError(
                "Expected a DBLP PID or DBLP author profile URL."
            )
        return self.resolve_author_by_pid(pid)

    def resolve_author_by_pid(self, dblp_pid: str) -> ProviderAuthorIdentity:
        pid = extract_dblp_pid(dblp_pid)
        if not pid:
            raise InvalidDblpPidError("The selected DBLP PID is invalid.")
        cached_identity = self._cached_identity(pid, complete_only=True)
        if cached_identity is not None:
            return cached_identity
        root = self._read_profile(pid)
        identity = self._identity_from_profile(root, pid, "待解析")
        self._cache_identity(identity)
        return identity

    def resolve_author_name_by_pid(self, dblp_pid: str) -> Optional[str]:
        pid = extract_dblp_pid(dblp_pid)
        if not pid:
            return None
        root = self._read_profile(pid)
        person = root.find("person")
        if person is not None:
            person_name = (person.attrib.get("name") or "").strip()
            if person_name and not self._looks_like_pid(person_name):
                return person_name
        return self._fallback_name_from_author_pid(root, pid)

    def list_publications(self, author_identity: ProviderAuthorIdentity) -> ProviderAuthorIdentity:
        pid = extract_dblp_pid(author_identity.dblp_id or "")
        if not pid:
            raise InvalidDblpPidError("DBLP author PID is missing or invalid.")
        root = self._read_profile(pid)
        return self._identity_from_profile(root, pid, author_identity.display_name)

    def _identity_from_profile(
        self,
        root,
        pid: str,
        fallback_display_name: str,
    ) -> ProviderAuthorIdentity:
        person = root.find("person")
        raw_display_name = (
            person.attrib.get("name")
            if person is not None
            else fallback_display_name
        ) or fallback_display_name
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
        return extract_dblp_pid(author_ref) or ""

    def _basic_candidate(
        self,
        pid: str,
        name: str,
        affiliations: Optional[List[str]] = None,
    ) -> DblpAuthorCandidate:
        return DblpAuthorCandidate(
            pid=pid,
            name=name,
            affiliations=affiliations or [],
            dblp_url=self._profile_url(pid, suffix=".html"),
            short_description=(
                "候选信息来自 DBLP 官方作者搜索。"
                "选择作者后将加载该 PID 的完整论文列表。"
            ),
        )

    def _cache_identity(
        self,
        identity: ProviderAuthorIdentity,
        *,
        complete: bool = True,
    ) -> None:
        pid = extract_dblp_pid(identity.dblp_id or "")
        if not pid:
            return
        with self._identity_cache_lock:
            if not complete and pid in self._complete_identity_pids:
                return
            self._identity_cache[pid] = copy.deepcopy(identity)
            if complete:
                self._complete_identity_pids.add(pid)

    def _cached_identity(
        self,
        pid: str,
        *,
        complete_only: bool = False,
    ) -> Optional[ProviderAuthorIdentity]:
        with self._identity_cache_lock:
            if complete_only and pid not in self._complete_identity_pids:
                return None
            identity = self._identity_cache.get(pid)
            return copy.deepcopy(identity) if identity is not None else None

    def _read_profile(
        self,
        pid: str,
        *,
        timeout_seconds: Optional[float] = None,
    ):
        xml_text = self._read_text(
            self._profile_url(pid, suffix=".xml"),
            timeout_seconds=timeout_seconds,
        )
        try:
            return ET.fromstring(xml_text)
        except (ET.ParseError, UnicodeError) as exc:
            raise DblpProviderUnavailableError(
                code=ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                message="DBLP returned invalid author XML.",
                provider_name=self.provider_name,
            ) from exc

    def _profile_url(self, pid: str, *, suffix: str) -> str:
        validated_pid = extract_dblp_pid(pid)
        if not validated_pid:
            raise InvalidDblpPidError("The DBLP PID is invalid.")
        encoded_pid = "/".join(
            urllib.parse.quote(part, safe="") for part in validated_pid.split("/")
        )
        return f"https://dblp.org/pid/{encoded_pid}{suffix}"

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
        except (json.JSONDecodeError, TypeError, UnicodeError) as exc:
            raise DblpAuthorSearchError(
                code=ProviderErrorCode.PROVIDER_SCHEMA_ERROR,
                message="DBLP returned invalid author search JSON.",
                provider_name=self.provider_name,
            ) from exc

    def _read_text(
        self,
        url: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        request_timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        urls = self._official_mirror_urls(url)
        last_error = None
        for request_url, base_url in urls:
            try:
                text = self._read_text_once(
                    request_url,
                    timeout_seconds=min(
                        request_timeout,
                        _DBLP_FAILOVER_TIMEOUT_SECONDS,
                    ),
                )
            except DblpProviderUnavailableError as exc:
                last_error = exc
                continue
            self._preferred_base_url = base_url
            return text
        if last_error is not None:
            raise last_error
        return self._read_text_once(url, timeout_seconds=request_timeout)

    def _official_mirror_urls(self, url: str):
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname not in _DBLP_HOSTS:
            return [(url, "")]
        ordered_bases = [self._preferred_base_url]
        ordered_bases.extend(
            base_url
            for base_url in _DBLP_BASE_URLS
            if base_url != self._preferred_base_url
        )
        path_and_query = urllib.parse.urlunsplit(
            ("", "", parsed.path, parsed.query, parsed.fragment)
        )
        return [
            (f"{base_url}{path_and_query}", base_url)
            for base_url in ordered_bases
        ]

    def _read_text_once(self, url: str, *, timeout_seconds: float) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, application/xml, text/xml;q=0.9",
                "User-Agent": "academic-impact-app/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read().decode("utf-8")
        except (socket.timeout, TimeoutError) as exc:
            raise DblpProviderUnavailableError(
                code=ProviderErrorCode.TIMEOUT,
                message="DBLP request timed out.",
                provider_name=self.provider_name,
            ) from exc
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise DblpAuthorNotFoundError(
                    code=ProviderErrorCode.NOT_FOUND,
                    message="DBLP author was not found.",
                    provider_name=self.provider_name,
                ) from exc
            raise DblpProviderUnavailableError(
                code=ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                message=f"DBLP request failed with HTTP {exc.code}.",
                provider_name=self.provider_name,
            ) from exc
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            ConnectionError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise DblpProviderUnavailableError(
                code=ProviderErrorCode.TRANSIENT_NETWORK_ERROR,
                message="DBLP network request failed.",
                provider_name=self.provider_name,
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
        return is_dblp_pid(value)

    def _fallback_name_from_author_pid(self, root, pid: str) -> Optional[str]:
        for author in root.findall(".//author"):
            author_pid = extract_dblp_pid(author.attrib.get("pid", ""))
            if author_pid == pid:
                author_name = (author.text or "").strip()
                if author_name and not self._looks_like_pid(author_name):
                    return author_name
        return None

    def _search_author_name(self, value) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return str(value.get("text") or value.get("#text") or "").strip()
        return ""

    def _search_affiliations(self, notes) -> List[str]:
        if not isinstance(notes, dict):
            return []
        raw_notes = notes.get("note", [])
        if isinstance(raw_notes, dict):
            raw_notes = [raw_notes]
        if not isinstance(raw_notes, list):
            return []
        affiliations = []
        for note in raw_notes:
            if not isinstance(note, dict) or note.get("@type") != "affiliation":
                continue
            affiliation = str(
                note.get("text") or note.get("#text") or ""
            ).strip()
            if affiliation and affiliation not in affiliations:
                affiliations.append(affiliation)
        return affiliations
