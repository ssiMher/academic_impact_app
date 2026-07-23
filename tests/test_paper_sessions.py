import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AnalysisTask, PaperAnalysisSession


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


def test_new_paper_session_page_returns_200(client):
    response = client.get("/paper-sessions/new")

    assert response.status_code == 200
    assert "创建普通论文分析" in response.text


def test_post_creates_session_and_redirects_to_detail(client, db_session_factory):
    response = client.post(
        "/paper-sessions",
        data={
            "query_text": "Evidence-aware citation analysis",
            "query_kind": "title",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/paper-sessions/1"

    with Session(db_session_factory.kw["bind"]) as db:
        saved_session = db.query(PaperAnalysisSession).one()

    assert saved_session.query_text == "Evidence-aware citation analysis"
    assert saved_session.query_kind == "title"
    assert saved_session.status == "created"


def test_detail_page_displays_query_text_and_status(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(
            query_text="Human-reviewed academic impact",
            query_kind="title",
            status="created",
        )
        db.add(session)
        db.commit()
        session_id = session.id

    response = client.get(f"/paper-sessions/{session_id}")

    assert response.status_code == 200
    assert "Human-reviewed academic impact" in response.text
    assert "created" in response.text


def test_post_discover_creates_task_and_redirects_without_running(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(
            query_text="Discoverable academic impact",
            query_kind="title",
            status="created",
        )
        db.add(session)
        db.commit()
        session_id = session.id

    response = client.post(
        f"/paper-sessions/{session_id}/discover",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/paper-sessions/{session_id}"

    with Session(db_session_factory.kw["bind"]) as db:
        task = db.query(AnalysisTask).one()

    assert task.session_kind == "paper_analysis"
    assert task.session_id == session_id
    assert task.task_type == "discover_paper"
    assert task.status == "pending"


def test_detail_page_displays_recent_task(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        session = PaperAnalysisSession(
            query_text="Task-visible academic impact",
            query_kind="title",
            status="created",
        )
        db.add(session)
        db.flush()
        task = AnalysisTask(
            session_kind="paper_analysis",
            session_id=session.id,
            task_type="discover_paper",
            status="pending",
            stage="queued",
        )
        db.add(task)
        db.commit()
        session_id = session.id

    response = client.get(f"/paper-sessions/{session_id}")

    assert response.status_code == 200
    assert "discover_paper" in response.text
    assert "pending" in response.text


def test_task_status_api_returns_task_state(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        task = AnalysisTask(
            session_kind="paper_analysis",
            session_id=123,
            task_type="discover_paper",
            status="pending",
            stage="queued",
        )
        db.add(task)
        db.commit()
        task_id = task.id

    response = client.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["id"] == task_id
    assert response.json()["status"] == "pending"
    assert response.json()["task_type"] == "discover_paper"
