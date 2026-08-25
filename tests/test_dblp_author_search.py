import http.client
import json
import socket
import urllib.error

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.providers.implementations.dblp import (
    DblpAuthorProvider,
    InvalidDblpPidError,
    extract_dblp_pid,
    is_dblp_pid,
)
from app.repositories.scholar_session_repo import ScholarSessionRepository
from app.schemas.provider import ProviderAuthorIdentity
from app.services.scholar_analysis_service import (
    ScholarAnalysisService,
    get_scholar_analysis_service,
)


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.text.encode("utf-8")


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _search_payload():
    return {
        "result": {
            "hits": {
                "hit": [
                    {
                        "info": {
                            "author": "Lei Xie",
                            "url": "https://dblp.org/pid/12/3456",
                            "notes": {
                                "note": {
                                    "@type": "affiliation",
                                    "text": "Nanjing University, China",
                                }
                            },
                        }
                    },
                    {
                        "info": {
                            "author": "Lei Xie 0002",
                            "url": "https://dblp.org/pid/123/4567",
                            "notes": {
                                "note": {
                                    "@type": "affiliation",
                                    "text": "Delft University of Technology",
                                }
                            },
                        }
                    },
                ]
            }
        }
    }


def _profile_xml(pid, name, *, alias="", title="Reliable Systems", venue="TestConf"):
    alias_xml = f'<author pid="{pid}">{alias}</author>' if alias else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <dblpperson>
      <person name="{name}" pid="{pid}">{alias_xml}</person>
      <r>
        <inproceedings>
          <author pid="{pid}">{name}</author>
          <title>{title}.</title>
          <year>2025</year>
          <booktitle>{venue}</booktitle>
        </inproceedings>
      </r>
    </dblpperson>
    """


def _install_dblp_service(monkeypatch, provider=None):
    selected_provider = provider or DblpAuthorProvider(timeout_seconds=0.1)

    def override(db: Session = Depends(get_db)):
        return ScholarAnalysisService(
            ScholarSessionRepository(db),
            author_provider=selected_provider,
        )

    app.dependency_overrides[get_scholar_analysis_service] = override


def _install_author_responses(monkeypatch, *, search_payload=None):
    payload = _search_payload() if search_payload is None else search_payload

    def fake_urlopen(request, timeout):
        url = request.full_url
        if "/search/author/api?" in url:
            return FakeResponse(json.dumps(payload))
        if "/pid/12/3456.xml" in url:
            return FakeResponse(
                _profile_xml(
                    "12/3456",
                    "Lei Xie",
                    alias="Lei Xie 0001",
                    title="Secure Scholarly Search",
                    venue="SIGIR",
                )
            )
        if "/pid/123/4567.xml" in url:
            return FakeResponse(
                _profile_xml(
                    "123/4567",
                    "Lei Xie 0002",
                    title="Graph Representation Learning",
                    venue="KDD",
                )
            )
        raise AssertionError(f"Unexpected DBLP URL: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def test_author_name_is_not_treated_as_dblp_pid():
    assert is_dblp_pid("Lei Xie") is False
    assert extract_dblp_pid("Lei Xie") is None


@pytest.mark.parametrize("value", ["12/3456", "123/4567", "12/3456-1"])
def test_valid_dblp_pid_is_recognized(value):
    assert is_dblp_pid(value) is True
    assert extract_dblp_pid(value) == value


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://dblp.org/pid/12/3456.html", "12/3456"),
        ("https://dblp.org/pid/12/3456.xml", "12/3456"),
    ],
)
def test_dblp_profile_url_extracts_pid(url, expected):
    assert extract_dblp_pid(url) == expected


def test_dblp_author_search_url_encodes_spaces(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse(json.dumps({"result": {"hits": {"hit": []}}}))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    DblpAuthorProvider(timeout_seconds=0.1).search_authors("Lei Xie")

    assert "q=Lei+Xie" in captured["url"]
    assert "Lei Xie" not in captured["url"]


def test_dblp_author_search_converts_chinese_name_to_given_name_first_pinyin(
    monkeypatch,
):
    captured_urls = []

    def fake_urlopen(request, timeout):
        captured_urls.append(request.full_url)
        return FakeResponse(json.dumps({"result": {"hits": {"hit": []}}}))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    DblpAuthorProvider(timeout_seconds=0.1).search_authors("谢磊")

    assert len(captured_urls) == 1
    assert "q=Lei+Xie" in captured_urls[0]
    assert "%E8%B0%A2%E7%A3%8A" not in captured_urls[0]
    assert "谢磊" not in captured_urls[0]


def test_chinese_author_search_page_shows_pinyin_search_results(
    client,
    monkeypatch,
):
    requested_urls = []
    _install_dblp_service(monkeypatch)

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        if "/search/author/api?" in request.full_url:
            assert "q=Lei+Xie" in request.full_url
            return FakeResponse(json.dumps(_search_payload()))
        if "/pid/12/3456.xml" in request.full_url:
            return FakeResponse(_profile_xml("12/3456", "Lei Xie"))
        if "/pid/123/4567.xml" in request.full_url:
            return FakeResponse(_profile_xml("123/4567", "Lei Xie 0002"))
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "谢磊"},
    )

    assert response.status_code == 200
    assert "Lei Xie" in response.text
    assert "12/3456" in response.text
    assert all("%E8%B0%A2%E7%A3%8A" not in url for url in requested_urls)


def test_dblp_author_search_falls_back_to_official_mirror(monkeypatch):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        if request.full_url.startswith("https://dblp.org/"):
            raise urllib.error.URLError(socket.timeout("timed out"))
        if "/search/author/api?" in request.full_url:
            return FakeResponse(json.dumps(_search_payload()))
        if "/pid/12/3456.xml" in request.full_url:
            return FakeResponse(_profile_xml("12/3456", "Lei Xie"))
        if "/pid/123/4567.xml" in request.full_url:
            return FakeResponse(_profile_xml("123/4567", "Lei Xie 0002"))
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    candidates = DblpAuthorProvider(timeout_seconds=30).search_authors("Lei Xie")

    assert len(candidates) == 2
    assert requested_urls[0].startswith("https://dblp.org/search/author/api?")
    assert requested_urls[1].startswith(
        "https://dblp.dagstuhl.de/search/author/api?"
    )
    assert all(
        not url.startswith("https://dblp.org/pid/")
        for url in requested_urls[2:]
    )


def test_dblp_author_search_returns_same_name_candidates(monkeypatch):
    _install_author_responses(monkeypatch)

    candidates = DblpAuthorProvider(timeout_seconds=0.1).search_authors("Lei Xie")

    assert [candidate.pid for candidate in candidates] == ["12/3456", "123/4567"]
    assert candidates[0].name == "Lei Xie"
    assert candidates[0].affiliations == ["Nanjing University, China"]
    assert candidates[1].affiliations == ["Delft University of Technology"]
    assert candidates[0].publication_count is None


def test_dblp_author_search_does_not_request_candidate_profiles(monkeypatch):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        if "/search/author/api?" in request.full_url:
            return FakeResponse(json.dumps(_search_payload()))
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    candidates = DblpAuthorProvider(timeout_seconds=30).search_authors("Lei Xie")

    assert [candidate.pid for candidate in candidates] == ["12/3456", "123/4567"]
    assert len(requested_urls) == 1
    assert "/search/author/api?" in requested_urls[0]


def test_author_search_page_shows_name_pid_and_description(client, monkeypatch):
    _install_dblp_service(monkeypatch)
    _install_author_responses(monkeypatch)

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Lei Xie"},
    )

    assert response.status_code == 200
    assert "Lei Xie" in response.text
    assert "12/3456" in response.text
    assert "Nanjing University, China" in response.text
    assert "Delft University of Technology" in response.text
    assert "选择作者后将加载该 PID 的完整论文列表" in response.text
    assert "https://dblp.org/pid/12/3456.html" in response.text


def test_author_search_page_does_not_depend_on_candidate_profiles(client, monkeypatch):
    _install_dblp_service(monkeypatch)

    def fake_urlopen(request, timeout):
        if "/search/author/api?" in request.full_url:
            return FakeResponse(json.dumps(_search_payload()))
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Lei Xie"},
    )

    assert response.status_code == 200
    assert "DBLP 当前暂时不可用" not in response.text
    assert "12/3456" in response.text
    assert "123/4567" in response.text
    assert "详细论文信息暂时无法加载" not in response.text


def test_default_fake_provider_search_form_still_creates_session(client):
    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Grace Hopper"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/scholar-sessions/1"


def test_same_name_candidates_require_user_selection(client, monkeypatch):
    requested_urls = []
    _install_dblp_service(monkeypatch)
    _install_author_responses(monkeypatch)
    original_urlopen = __import__("urllib.request", fromlist=["urlopen"]).urlopen

    def recording_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return original_urlopen(request, timeout)

    monkeypatch.setattr("urllib.request.urlopen", recording_urlopen)

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Lei Xie"},
    )

    assert response.status_code == 200
    assert response.history == []
    assert response.text.count("选择此作者并创建会话") == 2
    assert all("/pid/Lei Xie.xml" not in url for url in requested_urls)


def test_name_submitted_to_create_route_searches_before_creation(client, monkeypatch):
    requested_urls = []
    _install_dblp_service(monkeypatch)
    _install_author_responses(monkeypatch)
    search_urlopen = __import__("urllib.request", fromlist=["urlopen"]).urlopen

    def recording_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return search_urlopen(request, timeout)

    monkeypatch.setattr("urllib.request.urlopen", recording_urlopen)

    response = client.post(
        "/scholar-sessions",
        data={"author_ref": "Lei Xie"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "找到多个同名作者" in response.text
    assert any("/search/author/api?" in url for url in requested_urls)
    assert all("/pid/Lei Xie.xml" not in url for url in requested_urls)


def test_selected_dblp_pid_creates_scholar_session(client, monkeypatch):
    _install_dblp_service(monkeypatch)
    _install_author_responses(monkeypatch)

    response = client.post(
        "/scholar-sessions",
        data={"dblp_pid": "12/3456"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/scholar-sessions/1"
    detail = client.get("/scholar-sessions/1")
    assert "Lei Xie" in detail.text
    assert "12/3456" in detail.text


def test_selected_pid_loads_profile_after_author_search(
    client,
    monkeypatch,
):
    provider = DblpAuthorProvider(timeout_seconds=0.1)
    _install_dblp_service(monkeypatch, provider=provider)
    requested_urls = []

    def author_search_response(request, timeout):
        requested_urls.append(request.full_url)
        if "/search/author/api?" in request.full_url:
            return FakeResponse(json.dumps(_search_payload()))
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr(
        "urllib.request.urlopen",
        author_search_response,
    )

    search_response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Lei Xie"},
    )
    assert search_response.status_code == 200
    assert "12/3456" in search_response.text
    requests_after_search = len(requested_urls)

    def selected_profile_is_available(request, timeout):
        requested_urls.append(request.full_url)
        if "/pid/12/3456.xml" in request.full_url:
            return FakeResponse(
                _profile_xml(
                    "12/3456",
                    "Lei Xie",
                    title="Selected Author Publication",
                    venue="SIGIR",
                )
            )
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", selected_profile_is_available)
    create_response = client.post(
        "/scholar-sessions",
        data={"dblp_pid": "12/3456"},
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    assert create_response.headers["location"] == "/scholar-sessions/1"
    assert len(requested_urls) == requests_after_search + 1
    detail = client.get("/scholar-sessions/1")
    assert "Lei Xie" in detail.text
    assert "12/3456" in detail.text
    assert "Selected Author Publication" in detail.text


def test_empty_session_can_retry_dblp_publication_sync(
    client,
    monkeypatch,
    db_session_factory,
):
    provider = DblpAuthorProvider(timeout_seconds=0.1)
    _install_dblp_service(monkeypatch, provider=provider)
    db = db_session_factory()
    ScholarSessionRepository(db).create_with_publications(
        ProviderAuthorIdentity(
            display_name="Lei Xie",
            dblp_id="12/3456",
        )
    )
    db.close()

    empty_detail = client.get("/scholar-sessions/1")
    assert "重新从 DBLP 同步论文" in empty_detail.text

    def profile_is_available(request, timeout):
        if "/pid/12/3456.xml" in request.full_url:
            return FakeResponse(
                _profile_xml(
                    "12/3456",
                    "Lei Xie",
                    title="Recovered DBLP Publication",
                    venue="SIGIR",
                )
            )
        raise AssertionError(f"Unexpected DBLP URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", profile_is_available)
    sync_response = client.post(
        "/scholar-sessions/1/refresh-dblp-publications",
        follow_redirects=False,
    )

    assert sync_response.status_code == 303
    assert sync_response.headers["location"].endswith("dblp_sync=success")
    synced_detail = client.get(sync_response.headers["location"])
    assert "Recovered DBLP Publication" in synced_detail.text
    assert "SIGIR" in synced_detail.text

    second_sync = client.post(
        "/scholar-sessions/1/refresh-dblp-publications",
        follow_redirects=False,
    )
    assert second_sync.status_code == 303
    second_detail = client.get(second_sync.headers["location"])
    assert second_detail.text.count("Recovered DBLP Publication") == 1


def test_empty_session_dblp_sync_timeout_shows_message(
    client,
    monkeypatch,
    db_session_factory,
):
    provider = DblpAuthorProvider(timeout_seconds=0.1)
    _install_dblp_service(monkeypatch, provider=provider)
    db = db_session_factory()
    ScholarSessionRepository(db).create_with_publications(
        ProviderAuthorIdentity(
            display_name="Lei Xie",
            dblp_id="12/3456",
        )
    )
    db.close()

    def profiles_timeout(request, timeout):
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(
        "urllib.request.urlopen",
        profiles_timeout,
    )

    sync_response = client.post(
        "/scholar-sessions/1/refresh-dblp-publications",
        follow_redirects=False,
    )

    assert sync_response.status_code == 303
    assert sync_response.headers["location"].endswith("dblp_sync=unavailable")
    detail = client.get(sync_response.headers["location"])
    assert "DBLP 当前暂时不可用，论文尚未同步，请稍后重试" in detail.text


def test_direct_dblp_pid_can_create_session(client, monkeypatch):
    _install_dblp_service(monkeypatch)
    _install_author_responses(monkeypatch)

    response = client.post(
        "/scholar-sessions",
        data={"author_ref": " https://dblp.org/pid/12/3456.xml "},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_dblp_search_no_results_shows_message(client, monkeypatch):
    _install_dblp_service(monkeypatch)
    _install_author_responses(
        monkeypatch,
        search_payload={"result": {"hits": {"hit": []}}},
    )

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Nobody Here"},
    )

    assert response.status_code == 200
    assert "未找到匹配作者" in response.text


def test_dblp_timeout_does_not_return_500(client, monkeypatch):
    _install_dblp_service(monkeypatch)

    def fake_timeout(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_timeout)

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Lei Xie"},
    )

    assert response.status_code == 200
    assert "DBLP 当前暂时不可用" in response.text


def test_invalid_author_input_does_not_build_pid_url(monkeypatch):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse("")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = DblpAuthorProvider(timeout_seconds=0.1)

    with pytest.raises(InvalidDblpPidError):
        provider.resolve_author("Lei Xie")

    assert requested_urls == []


def test_author_search_does_not_invent_affiliation(client, monkeypatch):
    _install_dblp_service(monkeypatch)
    payload = _search_payload()
    for hit in payload["result"]["hits"]["hit"]:
        hit["info"].pop("notes", None)
    _install_author_responses(monkeypatch, search_payload=payload)

    response = client.post(
        "/scholar-sessions/author-search",
        data={"author_query": "Lei Xie"},
    )

    assert "DBLP 机构信息:</strong> 未提供" in response.text
    assert "Nanjing University" not in response.text
