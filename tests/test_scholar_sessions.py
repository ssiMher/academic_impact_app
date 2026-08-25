import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    CitationAuthorAnnotation,
    CitationEdge,
    DeepAnalysisQueueItem,
    NotableAuthor,
    Publication,
    ScholarAnalysisSession,
    ScholarPublication,
)
from app.schemas.provider import ProviderAuthorIdentity, ProviderCitationEdge, ProviderPublication
from app.repositories.scholar_session_repo import ScholarSessionRepository
from app.repositories.task_repo import TaskRepository
from app.services.scholar_analysis_service import ScholarAnalysisService
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager


class StaticCitationProvider:
    provider_name = "openalex"

    def __init__(self, citing_paper: ProviderPublication):
        self.citing_paper = citing_paper

    def discover_citations(self, target_title: str):
        return [ProviderCitationEdge(target_title=target_title, citing_paper=self.citing_paper)]


class EmptyCitationProvider:
    provider_name = "openalex"

    def discover_citations(self, target_title: str):
        return []


class PagingCitationProvider:
    provider_name = "openalex"

    def __init__(
        self,
        *,
        total_count: int = 40,
        available_count: int = 40,
        on_request=None,
        include_open_access: bool = False,
    ):
        self.total_count = total_count
        self.available_count = available_count
        self.on_request = on_request
        self.include_open_access = include_open_access
        self.requested_limits = []
        self.last_citation_expansion = {}

    def discover_citations(self, target_title: str):
        return self._edges(target_title, self.available_count)

    def list_citing_papers(self, publication: ProviderPublication, limit: int = 100):
        if self.on_request is not None:
            self.on_request()
        self.requested_limits.append(limit)
        count = min(limit, self.available_count)
        self.last_citation_expansion = {
            "provider": self.provider_name,
            "openalex_work_id": "Wtarget",
            "openalex_cited_by_count": self.total_count,
            "cited_by_api_url": "https://api.openalex.org/works?filter=cites:Wtarget",
            "fetched_count": count,
            "limit_per_publication": limit,
            "cursor_pages": 2 if count > 25 else 1,
            "expansion_complete": count >= self.total_count,
        }
        return self._edges(publication.title, count)

    def _edges(self, target_title: str, count: int):
        return [
            ProviderCitationEdge(
                target_title=target_title,
                citing_paper=ProviderPublication(
                    title=f"OpenAlex Citing Paper {index}",
                    year=2025,
                    venue="OpenAlex Journal",
                    doi=f"10.0000/openalex.{index}",
                    openalex_id=f"W{index}",
                    source_url=f"https://openalex.org/W{index}",
                    open_access_pdf_url=(
                        f"https://repository.example/download/openalex-{index}"
                        if self.include_open_access
                        else None
                    ),
                    open_access_license=(
                        "cc-by" if self.include_open_access else None
                    ),
                    open_access_source=(
                        "Example Repository"
                        if self.include_open_access
                        else None
                    ),
                ),
            )
            for index in range(1, count + 1)
        ]


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


def test_create_scholar_session(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")

    assert session.id == 1
    assert session.display_name == "Grace Hopper"
    assert session.status == "created"
    assert session.publication_count >= 3


def test_scholar_publications_are_saved(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        publications = service.list_publications(session.id)

    assert len(publications) >= 3
    assert publications[0].local_code == "S001"
    assert publications[0].title
    assert publications[0].publication_id is not None


def test_expand_scholar_citations_task(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:2]]
        task = service.enqueue_expand_scholar_citations(session.id, selected_ids)

        assert task.task_type == "expand_scholar_citations"
        assert task.session_kind == "scholar_analysis"

        ran_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

        db.refresh(session)

    assert ran_task.status == "succeeded"
    assert ran_task.progress_total == 2
    assert ran_task.progress_current == 2
    assert session.citation_edge_count > 0


def test_expand_and_build_creates_citation_edges_and_queue_items(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:2]]
        task = service.enqueue_expand_and_build_scholar_queue(session.id, selected_ids)

        ran_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        db.refresh(session)
        queue_count = db.query(DeepAnalysisQueueItem).filter_by(
            scholar_session_id=session.id
        ).count()

    assert task.task_type == "expand_and_build_scholar_queue"
    assert ran_task.status == "succeeded"
    assert session.citation_edge_count > 0
    assert queue_count > 0


def test_expand_and_build_handles_no_citation_edges(db_session_factory, monkeypatch):
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: EmptyCitationProvider(),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:1]]
        service.enqueue_expand_and_build_scholar_queue(session.id, selected_ids)

        ran_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        db.refresh(session)
        queue_count = db.query(DeepAnalysisQueueItem).filter_by(
            scholar_session_id=session.id
        ).count()

    assert ran_task.status == "succeeded"
    assert session.citation_edge_count == 0
    assert queue_count == 0
    assert "没有扩展到引用，无法构建队列" in ran_task.stage_message


def test_citation_edges_are_saved(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:1]]
        service.enqueue_expand_scholar_citations(session.id, selected_ids)
        TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

        edges = db.query(CitationEdge).all()
        saved_session = db.get(ScholarAnalysisSession, session.id)

    assert edges
    assert edges[0].provider_name == "fake"
    assert edges[0].self_citation_status == "unknown"
    assert edges[0].third_party_status == "third_party"
    assert saved_session.citation_edge_count == len(edges)


def test_expand_citations_not_limited_to_default_25(db_session_factory, monkeypatch):
    provider = PagingCitationProvider(total_count=40, available_count=40)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(session.id, [selected_id])
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        edge_count = db.query(CitationEdge).filter_by(scholar_session_id=session.id).count()

    assert provider.requested_limits == [100]
    assert edge_count == 40
    assert "fetched=40" in task.stage_message
    assert "complete=true" in task.stage_message


def test_expand_citations_respects_user_limit(db_session_factory, monkeypatch):
    provider = PagingCitationProvider(total_count=40, available_count=40)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(session.id, [selected_id], limit_per_publication=10)
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        edge_count = db.query(CitationEdge).filter_by(scholar_session_id=session.id).count()

    assert provider.requested_limits == [10]
    assert edge_count == 10
    assert "limit=10" in task.stage_message
    assert "complete=false" in task.stage_message


def test_expand_citations_does_not_hold_transaction_during_provider_request(
    db_session_factory,
    monkeypatch,
):
    transaction_states = []
    with Session(db_session_factory.kw["bind"]) as db:
        provider = PagingCitationProvider(
            total_count=1,
            available_count=1,
            on_request=lambda: transaction_states.append(db.in_transaction()),
        )
        monkeypatch.setattr(
            "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
            lambda: provider,
        )
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(
            session.id,
            [selected_id],
            limit_per_publication=1,
        )

        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

    assert task.status == "succeeded"
    assert transaction_states == [False]


def test_reexpanding_citations_refreshes_open_access_pdf_metadata(
    db_session_factory,
    monkeypatch,
):
    provider = PagingCitationProvider(total_count=1, available_count=1)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(
            session.id,
            [selected_id],
            limit_per_publication=1,
        )
        runner = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        )
        runner.run_once()

        provider.include_open_access = True
        service.enqueue_expand_scholar_citations(
            session.id,
            [selected_id],
            limit_per_publication=1,
        )
        runner.run_once()

        edge = db.query(CitationEdge).filter_by(
            scholar_session_id=session.id
        ).one()
        metadata = json.loads(edge.edge_meta_json)

    assert (
        metadata["open_access_pdf_url"]
        == "https://repository.example/download/openalex-1"
    )
    assert metadata["is_open_access"] is True
    assert metadata["license"] == "cc-by"
    assert metadata["url_type"] == "direct_pdf"


def test_expand_citations_reports_total_and_fetched_counts(db_session_factory, monkeypatch):
    provider = PagingCitationProvider(total_count=40, available_count=25)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(session.id, [selected_id], limit_per_publication=25)
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

    assert "provider=openalex" in task.stage_message
    assert "openalex_cited_by_count=40" in task.stage_message
    assert "fetched=25" in task.stage_message
    assert "saved_edges=25" in task.stage_message
    assert "duplicates=0" in task.stage_message
    assert "limit=25" in task.stage_message
    assert "pages=1" in task.stage_message
    assert "complete=false" in task.stage_message


def test_page_shows_openalex_total_vs_expanded_edges(client, db_session_factory, monkeypatch):
    provider = PagingCitationProvider(total_count=40, available_count=25)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    response = client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    expand = client.post(
        "/scholar-sessions/1/expand-citations",
        data={"publication_ids": ["1"], "limit_per_publication": "25"},
        follow_redirects=False,
    )
    assert expand.status_code == 303
    with Session(db_session_factory.kw["bind"]) as db:
        TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

    detail = client.get("/scholar-sessions/1")

    assert detail.status_code == 200
    assert "OpenAlex 总引用数" in detail.text
    assert "25 / 40" in detail.text
    assert "Google Scholar" in detail.text


def test_expansion_incomplete_warning_when_fetched_less_than_total(client, db_session_factory, monkeypatch):
    provider = PagingCitationProvider(total_count=40, available_count=25)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    client.post("/scholar-sessions", data={"author_ref": "Grace Hopper"}, follow_redirects=False)
    client.post(
        "/scholar-sessions/1/expand-citations",
        data={"publication_ids": ["1"], "limit_per_publication": "25"},
        follow_redirects=False,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

    detail = client.get("/scholar-sessions/1")

    assert "当前只扩展了部分引用，请提高 limit 或继续扩展。" in detail.text


def test_no_duplicate_edges_when_rerun_expansion(db_session_factory, monkeypatch):
    provider = PagingCitationProvider(total_count=3, available_count=3)
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(session.id, [selected_id], limit_per_publication=10)
        TaskRunner(task_repository=TaskRepository(db), task_manager=TaskManager()).run_once()
        first_count = db.query(CitationEdge).filter_by(scholar_session_id=session.id).count()
        service.enqueue_expand_scholar_citations(session.id, [selected_id], limit_per_publication=10)
        task = TaskRunner(task_repository=TaskRepository(db), task_manager=TaskManager()).run_once()
        second_count = db.query(CitationEdge).filter_by(scholar_session_id=session.id).count()

    assert first_count == 3
    assert second_count == 3
    assert "duplicates=3" in task.stage_message


def test_scholar_detail_page(client, db_session_factory):
    response = client.get("/scholar-sessions/new")
    assert response.status_code == 200
    assert "创建学者分析" in response.text

    response = client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/scholar-sessions/1"

    detail = client.get("/scholar-sessions/1")
    assert detail.status_code == 200
    assert "Grace Hopper" in detail.text
    assert "Fake Scholar Publication" in detail.text
    assert "Citation edges" in detail.text

    expand = client.post(
        "/scholar-sessions/1/expand-citations",
        data={"publication_ids": ["1", "2"]},
        follow_redirects=False,
    )
    assert expand.status_code == 303
    assert expand.headers["location"] == "/scholar-sessions/1"

    with Session(db_session_factory.kw["bind"]) as db:
        task_count = db.query(ScholarPublication).count()
    assert task_count >= 3


def test_scholar_detail_shows_one_click_expand_build_button(client):
    client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )

    detail = client.get("/scholar-sessions/1")

    assert detail.status_code == 200
    assert "一键扩展引用并构建队列" in detail.text
    assert 'name="limit_per_publication" value="500"' in detail.text


def test_scholar_detail_shows_import_honor_csv_button(client):
    client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )

    detail = client.get("/scholar-sessions/1")

    assert detail.status_code == 200
    assert "导入重要引用作者 CSV" in detail.text


def test_advanced_buttons_still_available(client):
    client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )

    detail = client.get("/scholar-sessions/1")

    assert detail.status_code == 200
    assert "仅扩展引用" in detail.text
    assert "仅重建队列" in detail.text


def test_scholar_detail_shows_honor_import_summary(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.flush()
        notable = NotableAuthor(
            name="Ramesh Govindan",
            fellow_status="IEEE Fellow",
            source="honor_csv_import",
            is_manual_verified=True,
        )
        db.add(notable)
        db.flush()
        db.add(
            CitationAuthorAnnotation(
                scholar_session_id=session.id,
                notable_author_id=notable.id,
                citing_author_name="Ramesh Govindan",
                honor_category="IEEE Fellow",
                match_method="title_exact",
                match_score=1.0,
                match_status="matched",
                is_important=True,
            )
        )
        db.commit()
        session_id = session.id

    detail = client.get(f"/scholar-sessions/{session_id}")

    assert detail.status_code == 200
    assert "最近一次重要引用作者导入摘要" in detail.text
    assert "成功匹配" in detail.text


def test_scholar_detail_shows_notable_author_counts(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = ScholarAnalysisSession(
            display_name="Grace Hopper",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.flush()
        notable = NotableAuthor(
            name="Ramesh Govindan",
            fellow_status="ACM Fellow",
            source="honor_csv_import",
            is_manual_verified=True,
        )
        db.add(notable)
        db.flush()
        db.add(
            CitationAuthorAnnotation(
                scholar_session_id=session.id,
                notable_author_id=notable.id,
                citing_author_name="Ramesh Govindan",
                honor_category="ACM Fellow",
                match_method="title_exact",
                match_score=1.0,
                match_status="matched",
                is_important=True,
            )
        )
        db.commit()
        session_id = session.id

    detail = client.get(f"/scholar-sessions/{session_id}")

    assert detail.status_code == 200
    assert "重要作者数量" in detail.text
    assert "重要引用数量" in detail.text


def test_combined_task_stage_messages_are_clear(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:1]]
        service.enqueue_expand_and_build_scholar_queue(session.id, selected_ids)
        ran_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

    assert ran_task.status == "succeeded"
    assert "阶段 1：扩展引用完成" in ran_task.stage_message
    assert "阶段 2：构建队列完成" in ran_task.stage_message
    assert "已扩展引用数=" in ran_task.stage_message
    assert "已生成队列条目数=" in ran_task.stage_message
    assert "provider=" in ran_task.stage_message
    assert "自动复用PDF=" in ran_task.stage_message


def test_scholar_new_page_uses_dashboard_layout(client):
    response = client.get("/scholar-sessions/new")

    assert response.status_code == 200
    assert "app-shell" in response.text
    assert "stat-card" in response.text
    assert "创建学者分析会话" in response.text


def test_scholar_new_page_no_fake_provider_phase_text(client):
    response = client.get("/scholar-sessions/new")

    assert response.status_code == 200
    assert "当前 Phase 10" not in response.text
    assert "FakeAuthorProvider" not in response.text
    assert "FakeCitationProvider" not in response.text


def test_scholar_detail_shows_workflow_stats(client):
    response = client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    detail = client.get("/scholar-sessions/1")

    assert detail.status_code == 200
    assert "Expanded citation edges" in detail.text
    assert "They are not the total citation count from Google Scholar or OpenAlex" in detail.text
    assert "Deep analysis queue count" in detail.text
    assert "PDF ready count" in detail.text
    assert "Analyzed item count" in detail.text
    assert "Strong evidence count" in detail.text
    assert "Recent tasks" in detail.text


def test_no_real_network_for_scholar_mvp():
    checked_paths = [
        "app/services/scholar_analysis_service.py",
        "app/tasks/handlers/expand_scholar_citations.py",
        "app/routers/scholar_sessions.py",
    ]
    forbidden = ("requests.", "httpx.", "urllib.request", "urlopen", "aiohttp")

    for path in checked_paths:
        source = (Path.cwd() / path).read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_scholar_mvp_full_flow_and_counts_are_consistent(client, db_session_factory):
    response = client.post(
        "/scholar-sessions",
        data={"author_ref": "Grace Hopper"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        publications = service.list_publications(1)
        selected_ids = [publication.id for publication in publications[:2]]

    expand = client.post(
        "/scholar-sessions/1/expand-citations",
        data={"publication_ids": [str(publication_id) for publication_id in selected_ids]},
        follow_redirects=False,
    )
    assert expand.status_code == 303

    with Session(db_session_factory.kw["bind"]) as db:
        task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        session = db.get(ScholarAnalysisSession, 1)
        scholar_publication_count = db.query(ScholarPublication).count()
        edge_count = db.query(CitationEdge).count()

    assert task.status == "succeeded"
    assert session.publication_count == scholar_publication_count
    assert session.citation_edge_count == edge_count

    detail = client.get("/scholar-sessions/1")
    assert detail.status_code == 200
    assert "Grace Hopper" in detail.text
    assert "pid/fake/Scholar" in detail.text
    assert "Publication count" in detail.text
    assert str(scholar_publication_count) in detail.text
    assert "Citation edges" in detail.text
    assert str(edge_count) in detail.text
    assert "expand_scholar_citations" in detail.text


def test_expand_scholar_citations_is_idempotent_across_retries(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:2]]
        service.enqueue_expand_scholar_citations(session.id, selected_ids)
        TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()

        first_publication_count = db.query(Publication).count()
        first_edge_count = db.query(CitationEdge).count()
        db.refresh(session)
        assert session.citation_edge_count == first_edge_count

        service.enqueue_expand_scholar_citations(session.id, selected_ids)
        retry_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        db.refresh(session)

        second_publication_count = db.query(Publication).count()
        second_edge_count = db.query(CitationEdge).count()

    assert retry_task.status == "succeeded"
    assert second_publication_count == first_publication_count
    assert second_edge_count == first_edge_count
    assert session.citation_edge_count == first_edge_count


def test_empty_publications_from_provider_creates_safe_session(db_session_factory):
    class EmptyAuthorProvider:
        def resolve_author(self, author_ref):
            return ProviderAuthorIdentity(display_name=author_ref, publications=[])

    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(
            ScholarSessionRepository(db),
            author_provider=EmptyAuthorProvider(),
        )
        session = service.create_scholar_session("No Papers")
        publications = service.list_publications(session.id)

    assert session.display_name == "No Papers"
    assert session.status == "no_publications"
    assert session.publication_count == 0
    assert publications == []


def test_scholar_session_created_from_dblp_id_has_real_display_name(db_session_factory):
    class DblpLikeProvider:
        def resolve_author(self, author_ref):
            return ProviderAuthorIdentity(
                display_name="Jingyi Ning",
                dblp_id="275/7641",
                publications=[],
            )

    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(
            ScholarSessionRepository(db),
            author_provider=DblpLikeProvider(),
        )
        session = service.create_scholar_session("275/7641")

    assert session.display_name == "Jingyi Ning"
    assert session.dblp_id == "275/7641"


def test_scholar_detail_separates_display_name_and_dblp_id(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = ScholarAnalysisSession(
            display_name="Jingyi Ning",
            dblp_id="275/7641",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        session_id = session.id

    detail = client.get(f"/scholar-sessions/{session_id}")

    assert detail.status_code == 200
    assert "Jingyi Ning" in detail.text
    assert "275/7641" in detail.text


def test_dblp_pid_input_resolves_author_display_name(db_session_factory):
    class DblpLikeProvider:
        def resolve_author(self, author_ref):
            return ProviderAuthorIdentity(
                display_name="Jingyi Ning",
                dblp_id="275/7641",
                publications=[],
            )

    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(
            ScholarSessionRepository(db),
            author_provider=DblpLikeProvider(),
        )
        session = service.create_scholar_session("275/7641")

    assert session.display_name == "Jingyi Ning"


def test_existing_pending_display_name_updated_after_resolution(db_session_factory):
    class DblpLikeProvider:
        def resolve_author_name_by_pid(self, dblp_pid):
            return "Jingyi Ning"

    with Session(db_session_factory.kw["bind"]) as db:
        session = ScholarAnalysisSession(
            display_name="待解析",
            dblp_id="275/7641",
            status="created",
            publication_count=0,
            citation_edge_count=0,
        )
        db.add(session)
        db.commit()
        service = ScholarAnalysisService(
            ScholarSessionRepository(db),
            author_provider=DblpLikeProvider(),
        )
        detail = service.get_scholar_detail(session.id)
        db.refresh(session)

    assert detail is not None
    assert session.display_name == "Jingyi Ning"


def test_scholar_routes_return_clear_errors(client):
    missing = client.get("/scholar-sessions/999")
    assert missing.status_code == 404

    empty_selection = client.post(
        "/scholar-sessions/999/expand-citations",
        data={},
        follow_redirects=False,
    )
    assert empty_selection.status_code == 400
    assert "At least one publication" in empty_selection.text


def test_expand_scholar_citations_failure_marks_task_failed(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_ids = [publication.id for publication in service.list_publications(session.id)[:1]]
        service.enqueue_expand_scholar_citations(session.id, selected_ids)

        def failing_handler(db, task):
            raise RuntimeError("fake citation provider failed")

        failed_task = TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager({"expand_scholar_citations": failing_handler}),
        ).run_once()

    assert failed_task.status == "failed"
    assert "fake citation provider failed" in failed_task.error_message


def test_openalex_citing_publication_doi_saved(db_session_factory, monkeypatch):
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: StaticCitationProvider(
            ProviderPublication(
                title="OpenAlex Citing Paper",
                year=2025,
                doi="10.1145/example",
                source_url="https://openalex.org/W100",
            )
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(session.id, [selected_id])
        TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        publication = (
            db.query(Publication)
            .filter(Publication.title == "OpenAlex Citing Paper")
            .one()
        )

    assert publication.doi == "10.1145/example"


def test_openalex_citing_publication_openalex_id_saved_when_available(
    db_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.tasks.handlers.expand_scholar_citations.get_citation_provider",
        lambda: StaticCitationProvider(
            ProviderPublication(
                title="OpenAlex ID Citing Paper",
                year=2025,
                doi="10.1145/openalex-id",
                openalex_id="W987654",
                source_url="https://openalex.org/W987654",
            )
        ),
    )
    with Session(db_session_factory.kw["bind"]) as db:
        service = ScholarAnalysisService(ScholarSessionRepository(db))
        session = service.create_scholar_session("Grace Hopper")
        selected_id = service.list_publications(session.id)[0].id
        service.enqueue_expand_scholar_citations(session.id, [selected_id])
        TaskRunner(
            task_repository=TaskRepository(db),
            task_manager=TaskManager(),
        ).run_once()
        publication = (
            db.query(Publication)
            .filter(Publication.title == "OpenAlex ID Citing Paper")
            .one()
        )

    assert publication.openalex_id == "W987654"
