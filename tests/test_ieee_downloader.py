import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisTask,
    CitationEdge,
    DeepAnalysisQueueItem,
    PdfAssetPublicationLink,
    Publication,
)
from app.repositories.task_repo import TaskRepository
from app.services.ieee_download_service import IeeeBrowserDownloader, IeeeDownloadResult
from app.services.ieee_session_service import IeeeSessionService, IeeeSessionStatus
from app.services.queue_pdf_download_service import (
    PdfDownloadResult,
    QueuePdfDownloadService,
)
from app.tasks.handlers.discover_pdfs_for_queue import handle_discover_pdfs_for_queue
from app.tasks.handlers.download_ieee_pdf import handle_download_ieee_pdf
from app.tasks.runner import TaskRunner
from app.tasks.task_manager import TaskManager
from scripts.ieee_browser_session_helper import classify_session_text
from tests.test_scholar_evidence import seed_queue_item
from tests.unit.test_pdf_service import VALID_PDF_BYTES


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ieee_item(db, tmp_path):
    session_id, item_id = seed_queue_item(db, tmp_path, pdf_ready=False)
    item = db.get(DeepAnalysisQueueItem, item_id)
    publication = db.get(Publication, item.citing_publication_id)
    publication.title = "A Precise IEEE Paper Title"
    publication.doi = "10.1109/TIM.2025.1234567"
    item.citing_paper_title = publication.title
    item.publisher_landing_url = "https://ieeexplore.ieee.org/document/12345678"
    db.commit()
    return session_id, item_id


def test_ieee_downloader_accepts_complete_pdf_from_configured_output(tmp_path, monkeypatch):
    tool = tmp_path / "ieee-download"
    tool.touch()
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    pdf_path = download_dir / "12345678_paper.pdf"
    pdf_path.write_bytes(VALID_PDF_BYTES)
    monkeypatch.setattr(
        "app.services.ieee_download_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"[成功] {pdf_path}\n",
        ),
    )

    result = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(download_dir),
    ).download("A Precise IEEE Paper Title")

    assert result.status == "downloaded"
    assert result.pdf_path == pdf_path


def test_ieee_downloader_detects_challenge_and_does_not_retry(tmp_path, monkeypatch):
    tool = tmp_path / "ieee-download"
    tool.touch()
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=1,
            stdout="Max challenge attempts exceeded. Please refresh the page.",
        )

    monkeypatch.setattr(
        "app.services.ieee_download_service.subprocess.run",
        fake_run,
    )

    result = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(tmp_path / "downloads"),
    ).download("IEEE paper")

    assert result.status == "challenge_blocked"
    assert result.reason == "ieee_challenge_blocked"
    assert len(calls) == 1


def test_ieee_batch_uses_one_helper_process_for_multiple_items(tmp_path, monkeypatch):
    tool = tmp_path / "ieee-download"
    tool.touch()
    (tmp_path / "ieee_download.py").touch()
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    calls = []
    output = "\n".join(
        [
            'IEEE_SESSION_JSON:{"event":"session","status":"authenticated"}',
            'IEEE_SESSION_JSON:{"event":"result","queue_item_id":1,"status":"failed","reason":"x"}',
            'IEEE_SESSION_JSON:{"event":"result","queue_item_id":2,"status":"failed","reason":"y"}',
        ]
    )

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(
        "app.services.ieee_download_service.subprocess.run",
        fake_run,
    )

    results = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(tmp_path / "downloads"),
    ).download_many(
        [
            {"queue_item_id": 1, "query": "First"},
            {"queue_item_id": 2, "query": "Second"},
        ],
        min_interval_seconds=0,
    )

    assert len(calls) == 1
    assert [value["queue_item_id"] for value in results] == [1, 2]


def test_ieee_pause_files_are_task_scoped(tmp_path):
    service = IeeeSessionService(
        command=str(tmp_path / "ieee-download"),
        work_dir=str(tmp_path),
    )

    service.request_pause(11)

    assert service.pause_path(11).is_file()
    assert not service.pause_path(12).exists()
    service.clear_pause_request(11)
    assert not service.pause_path(11).exists()


def test_ieee_login_fifo_uses_linux_runtime_directory(tmp_path):
    service = IeeeSessionService(
        command=str(tmp_path / "ieee-download"),
        work_dir=str(tmp_path),
    )

    assert service.fifo_path.name == "login.fifo"
    assert str(service.fifo_path).startswith(str(Path.cwd() / "var" / "run"))
    assert not str(service.fifo_path).startswith(str(tmp_path))


def test_ieee_login_start_failure_cleans_fifo_and_profile_lock(
    tmp_path, monkeypatch
):
    tool = tmp_path / "ieee-download"
    tool.touch()
    service = IeeeSessionService(
        command=str(tool),
        work_dir=str(tmp_path),
        profile_dir=str(tmp_path / "profile"),
        runtime_dir=str(tmp_path / "runtime"),
    )
    real_open = os.open
    fifo_flags = []

    def tracking_open(path, flags, *args, **kwargs):
        if Path(path) == service.fifo_path:
            fifo_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("app.services.ieee_session_service.os.open", tracking_open)
    monkeypatch.setattr(
        "app.services.ieee_session_service.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no display")),
    )

    try:
        service.open_login_window()
    except OSError:
        pass
    else:
        raise AssertionError("Expected login process start failure")

    assert not service.fifo_path.exists()
    assert not service.lock_path.exists()
    status = service.status()
    assert status.status == "failed"
    assert "OSError" in status.message
    assert fifo_flags
    assert all(flags & os.O_NONBLOCK == 0 for flags in fifo_flags)


def test_dead_ieee_login_process_is_not_reported_as_open(tmp_path):
    service = IeeeSessionService(
        command=str(tmp_path / "ieee-download"),
        work_dir=str(tmp_path),
        profile_dir=str(tmp_path / "profile"),
        runtime_dir=str(tmp_path / "runtime"),
    )
    service._write_state(
        {
            "status": "waiting_for_login",
            "login_pid": 999_999_999,
            "message": "waiting",
        }
    )
    service.fifo_path.parent.mkdir(parents=True, exist_ok=True)
    service.fifo_path.touch()

    status = service.status()

    assert status.status == "unauthenticated"
    assert status.login_window_open is False
    assert not service.fifo_path.exists()
    assert "已退出" in status.message


def test_ieee_login_detection_does_not_block_when_fifo_has_no_reader(tmp_path):
    service = IeeeSessionService(
        command=str(tmp_path / "ieee-download"),
        work_dir=str(tmp_path),
        profile_dir=str(tmp_path / "profile"),
        runtime_dir=str(tmp_path / "runtime"),
    )
    service.fifo_path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(service.fifo_path, 0o600)

    started = time.monotonic()
    result = service._finish_login_process(999_999_999)

    assert result is False
    assert time.monotonic() - started < 1


def test_closed_browser_cleans_live_coordinator_state(tmp_path, monkeypatch):
    service = IeeeSessionService(
        command=str(tmp_path / "ieee-download"),
        work_dir=str(tmp_path),
        profile_dir=str(tmp_path / "profile"),
        runtime_dir=str(tmp_path / "runtime"),
    )
    service._write_state(
        {
            "status": "waiting_for_login",
            "login_pid": 424_242,
            "login_pid_start_time": "start-token",
            "login_started_at_epoch": time.time() - 60,
        }
    )
    terminated = []
    monkeypatch.setattr(
        "app.services.ieee_session_service._pid_alive",
        lambda pid, expected_start_time="": pid == 424_242,
    )
    monkeypatch.setattr(
        "app.services.ieee_session_service._browser_process_alive",
        lambda _pid: False,
    )
    monkeypatch.setattr(
        service,
        "_terminate_login_process",
        lambda pid: terminated.append(pid),
    )

    status = service.status()

    assert terminated == [424_242]
    assert status.login_window_open is False
    assert status.status == "unauthenticated"


def test_ieee_anonymous_account_navigation_is_not_personal_login():
    status = classify_session_text(
        "IEEE Xplore My Account Personal Account Sign In Create Account"
    )

    assert status["status"] == "unauthenticated"
    assert status["personal_login"] is False


def test_ieee_explicit_logout_control_confirms_personal_login():
    status = classify_session_text("IEEE Xplore My Account Sign Out")

    assert status["status"] == "authenticated"
    assert status["personal_login"] is True


def test_ieee_access_provided_by_confirms_institution_access():
    status = classify_session_text(
        "Access provided by: Nanjing University | Sign In"
    )

    assert status["status"] == "authenticated"
    assert status["institution_access"] is True
    assert "Nanjing University" in status["institution_name"]


def test_legacy_ieee_authenticated_state_requires_revalidation(tmp_path):
    service = IeeeSessionService(
        command=str(tmp_path / "ieee-download"),
        work_dir=str(tmp_path),
        profile_dir=str(tmp_path / "profile"),
        runtime_dir=str(tmp_path / "runtime"),
    )
    service._write_state(
        {
            "status": "authenticated",
            "personal_login": True,
            "institution_access": False,
        }
    )

    status = service.status()

    assert status.status == "session_expired"
    assert status.personal_login is False
    assert "重新检测" in status.message


def test_single_ieee_download_respects_profile_lock(tmp_path):
    tool = tmp_path / "ieee-download"
    tool.touch()
    profile = tmp_path / "custom_profile"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    lock = runtime / "profile.lock"
    lock.write_text(str(__import__("os").getpid()), encoding="ascii")
    downloader = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(tmp_path / "downloads"),
        profile_dir=str(profile),
        runtime_dir=str(runtime),
    )

    try:
        downloader.download("Locked paper")
    except RuntimeError as exc:
        assert "already in use" in str(exc)
    else:
        raise AssertionError("Expected profile lock contention")
    finally:
        lock.unlink(missing_ok=True)


def test_ieee_downloader_rejects_html_or_incomplete_output(tmp_path, monkeypatch):
    tool = tmp_path / "ieee-download"
    tool.touch()
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    bad_path = download_dir / "login.pdf"
    bad_path.write_bytes(b"<html>Institutional Sign In</html>")
    monkeypatch.setattr(
        "app.services.ieee_download_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"[成功] {bad_path}\n",
        ),
    )

    result = IeeeBrowserDownloader(
        command=str(tool),
        work_dir=str(tmp_path),
        download_dir=str(download_dir),
    ).download("Paper")

    assert result.status == "requires_login"
    assert result.pdf_path is None


def test_ieee_download_route_enqueues_queue_item_payload(tmp_path):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    db.close()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/scholar-sessions/{session_id}/queue/{item_id}/download-ieee-pdf",
            follow_redirects=False,
        )
        assert response.status_code == 303
        verify = factory()
        task = verify.query(AnalysisTask).filter_by(task_type="download_ieee_pdf").one()
        assert json.loads(task.payload_json) == {"queue_item_id": item_id}
        verify.close()
    finally:
        app.dependency_overrides.clear()


def test_ieee_download_task_imports_asset_and_binds_queue_item(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    pdf_path = tmp_path / "downloads" / "12345678_paper.pdf"
    pdf_path.parent.mkdir()
    pdf_path.write_bytes(VALID_PDF_BYTES)
    task = TaskRepository(db).create(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="download_ieee_pdf",
        payload={"queue_item_id": item_id},
    )

    fake_settings = SimpleNamespace(
        ieee_downloader_command="ieee-download",
        ieee_downloader_work_dir=str(tmp_path),
        ieee_downloader_download_dir=str(pdf_path.parent),
        ieee_downloader_timeout_seconds=30,
        pdf_asset_dir=str(tmp_path / "assets"),
        extracted_text_dir=str(tmp_path / "text"),
        pdf_max_upload_bytes=10_000_000,
    )
    fake_settings.provider_timeout_seconds = 20
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.settings",
        fake_settings,
    )
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.IeeeBrowserDownloader.download",
        lambda self, query: IeeeDownloadResult("downloaded", "ok", pdf_path),
    )
    monkeypatch.setattr(
        "app.services.pdf_service.extract_pdf_text",
        lambda pdf_path, output_path: output_path.write_text("IEEE paper text", encoding="utf-8"),
    )

    result = TaskRunner(
        task_repository=TaskRepository(db),
        task_manager=TaskManager(),
    ).run_once()

    item = db.get(DeepAnalysisQueueItem, item_id)
    assert result.id == task.id
    assert result.status == "succeeded"
    assert item.pdf_asset_id is not None
    assert item.pdf_readiness_status == "reused_pdf"
    assert item.pdf_source == "ieee_browser_helper"
    assert db.query(PdfAssetPublicationLink).filter_by(
        pdf_asset_id=item.pdf_asset_id,
        publication_id=item.citing_publication_id,
    ).count() == 1
    db.close()


def test_ieee_download_task_records_login_required(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="download_ieee_pdf",
        payload_json=json.dumps({"queue_item_id": item_id}),
        status="running",
    )
    db.add(task)
    db.commit()
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.settings",
        SimpleNamespace(
            ieee_downloader_command="ieee-download",
            ieee_downloader_work_dir=str(tmp_path),
            ieee_downloader_download_dir=str(tmp_path / "downloads"),
            ieee_downloader_timeout_seconds=30,
            pdf_asset_dir=str(tmp_path / "assets"),
            extracted_text_dir=str(tmp_path / "text"),
            pdf_max_upload_bytes=10_000_000,
            provider_timeout_seconds=20,
        ),
    )
    monkeypatch.setattr(
        "app.services.queue_pdf_download_service.IeeeBrowserDownloader.download",
        lambda self, query: IeeeDownloadResult(
            "requires_login", "Institutional Sign In", reason="ieee_session_required"
        ),
    )

    handle_download_ieee_pdf(db, task)

    item = db.get(DeepAnalysisQueueItem, item_id)
    assert item.pdf_access_status == "requires_login"
    assert item.requires_login_reason == "ieee_browser_session_required"
    assert "机构登录" in task.stage_message
    db.close()


def test_ieee_queue_helper_shows_automatic_download_action(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, _item_id = _ieee_item(db, tmp_path)
    db.close()
    original_settings = __import__(
        "app.services.scholar_queue_service", fromlist=["settings"]
    ).settings
    fake_settings = SimpleNamespace(
        ieee_downloader_command="ieee-download",
        ieee_downloader_portal_url="http://127.0.0.1:8090/",
        pdf_library_dirs=original_settings.pdf_library_dirs,
        pdf_index_path=original_settings.pdf_index_path,
        pdf_max_scan_files=original_settings.pdf_max_scan_files,
        pdf_match_threshold=original_settings.pdf_match_threshold,
    )
    monkeypatch.setattr("app.services.scholar_queue_service.settings", fake_settings)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            f"/scholar-sessions/{session_id}/queue?view=need_pdf"
        )
        assert response.status_code == 200
        assert "通过 IEEE 浏览器助手自动下载" in response.text
        assert "主系统不接收或保存 IEEE 账号密码" in response.text
        assert "打开 IEEE 助手登录页" in response.text
    finally:
        app.dependency_overrides.clear()


def test_unified_queue_download_service_uses_ieee_after_open_discovery(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    _session_id, item_id = _ieee_item(db, tmp_path)
    pdf_path = tmp_path / "downloads" / "paper.pdf"
    pdf_path.parent.mkdir()
    pdf_path.write_bytes(VALID_PDF_BYTES)

    class NoOpenPdf:
        def discover_and_download_for_queue_item(self, *, item_id, pdf_service):
            return {"status": "requires_login"}

    class FakeIeee:
        def download(self, query):
            return IeeeDownloadResult("downloaded", "ok", pdf_path)

    monkeypatch.setattr(
        "app.services.pdf_service.extract_pdf_text",
        lambda pdf_path, output_path: output_path.write_text(
            "IEEE text", encoding="utf-8"
        ),
    )
    service = QueuePdfDownloadService(
        db,
        pdf_service=__import__(
            "tests.test_pdf_discovery", fromlist=["_pdf_service"]
        )._pdf_service(db, tmp_path),
        discovery_service=NoOpenPdf(),
        ieee_downloader=FakeIeee(),
    )

    result = service.download_pdf_for_queue_item(
        item_id,
        allow_restricted_browser=True,
    )

    item = db.get(DeepAnalysisQueueItem, item_id)
    assert result.status == "downloaded"
    assert result.source == "ieee_browser_helper"
    assert item.pdf_asset_id == result.pdf_asset_id
    assert item.pdf_discovery_status == "downloaded"
    db.close()


def test_batch_pdf_download_continues_and_records_per_item_failure(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    session_id, first_id = _ieee_item(db, tmp_path)
    first = db.get(DeepAnalysisQueueItem, first_id)
    second_publication = Publication(
        title="Second IEEE Paper",
        doi="10.1109/TIM.2025.7654321",
        venue="IEEE TIM",
        authors_json="[]",
    )
    db.add(second_publication)
    db.flush()
    second_edge = CitationEdge(
        scholar_session_id=session_id,
        cited_publication_id=first.cited_publication_id,
        citing_publication_id=second_publication.id,
        provider_name="fake",
    )
    db.add(second_edge)
    db.flush()
    second = DeepAnalysisQueueItem(
        scholar_session_id=session_id,
        citation_edge_id=second_edge.id,
        cited_publication_id=first.cited_publication_id,
        citing_publication_id=second_publication.id,
        queue_status="pending",
        priority_score=1,
        priority_reasons_json="[]",
        third_party_status="third_party",
        self_citation_status="not_self_citation",
        pdf_readiness_status="need_pdf",
        citing_paper_title=second_publication.title,
        cited_paper_title=first.cited_paper_title,
        citing_authors_json="[]",
        cited_authors_json="[]",
        provider_name="fake",
    )
    db.add(second)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        payload_json="{}",
        status="running",
    )
    db.add(task)
    db.commit()

    class FakeBatchService:
        def __init__(self, db):
            pass

        def download_pdf_for_queue_item(
            self, item_id, *, allow_restricted_browser=False, force=False
        ):
            assert allow_restricted_browser is True
            if item_id == first_id:
                return PdfDownloadResult(
                    item_id,
                    "downloaded",
                    source="ieee_browser_helper",
                    pdf_asset_id=10,
                )
            return PdfDownloadResult(
                item_id,
                "failed",
                source="ieee_browser_helper",
                reason="title_match_failed",
            )

    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.QueuePdfDownloadService",
        FakeBatchService,
    )

    handle_discover_pdfs_for_queue(db, task)

    summary = json.loads(task.payload_json)["result_summary"]
    assert summary["downloaded"] == 1
    assert summary["ieee_downloaded"] == 1
    assert summary["failed"] == 1
    assert summary["failures"] == [
        {
            "queue_item_id": second.id,
            "citing_paper_title": "Second IEEE Paper",
            "reason": "title_match_failed",
        }
    ]
    db.close()


def test_first_unauthenticated_ieee_item_pauses_without_downloading_remaining(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        status="running",
    )
    db.add(task)
    db.commit()
    calls = {"batch": 0, "opened": 0}

    class FakeDownloadService:
        def __init__(self, _db):
            pass

        def discover_open_pdf_for_queue_item(self, queue_item_id):
            return PdfDownloadResult(queue_item_id, "requires_login")

        def download_ieee_batch(self, _ids):
            calls["batch"] += 1
            return []

    class FakeSession:
        def status(self, *, probe=False):
            return IeeeSessionStatus("unauthenticated")

        def open_login_window(self):
            calls["opened"] += 1
            return IeeeSessionStatus("waiting_for_login", login_window_open=True)

    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.QueuePdfDownloadService",
        FakeDownloadService,
    )
    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.IeeeSessionService",
        FakeSession,
    )

    handle_discover_pdfs_for_queue(db, task)

    payload = json.loads(task.payload_json)
    assert task.status == "waiting_for_login"
    assert task.progress_total == 1
    assert task.progress_current == 0
    assert payload["pending_ieee_item_ids"] == [item_id]
    assert calls == {"batch": 0, "opened": 1}
    db.close()


def test_challenge_stops_ieee_stage_and_preserves_checkpoint(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        status="running",
    )
    db.add(task)
    db.commit()

    class FakeDownloadService:
        def __init__(self, _db):
            pass

        def discover_open_pdf_for_queue_item(self, queue_item_id):
            return PdfDownloadResult(queue_item_id, "requires_login")

    class FakeSession:
        def status(self, *, probe=False):
            return IeeeSessionStatus(
                "challenge_blocked",
                challenge_detected=True,
            )

    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.QueuePdfDownloadService",
        FakeDownloadService,
    )
    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.IeeeSessionService",
        FakeSession,
    )

    handle_discover_pdfs_for_queue(db, task)

    payload = json.loads(task.payload_json)
    assert task.status == "challenge_blocked"
    assert payload["pending_ieee_item_ids"] == [item_id]
    assert payload["progress_summary"]["challenge_blocked_count"] == 1
    db.close()


def test_authenticated_resume_downloads_only_pending_ieee_items(tmp_path, monkeypatch):
    factory = _session_factory()
    db = factory()
    session_id, item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        status="running",
        progress_total=1,
        payload_json=json.dumps(
            {
                "discovery_completed": True,
                "pending_ieee_item_ids": [item_id],
                "progress_summary": {},
                "resume_requested": True,
            }
        ),
    )
    db.add(task)
    db.commit()
    received = []

    class FakeDownloadService:
        def __init__(self, _db):
            pass

        def download_ieee_batch(self, item_ids, *, stop_file=None):
            received.extend(item_ids)
            assert stop_file.name.endswith(f"_{task.id}")
            return [
                PdfDownloadResult(
                    item_ids[0],
                    "downloaded",
                    source="ieee_browser_helper",
                    pdf_asset_id=99,
                )
            ]

    class FakeSession:
        def status(self, *, probe=False):
            return IeeeSessionStatus("authenticated", institution_access=True)

        def record_download_success(self):
            pass

        def pause_path(self, task_id):
            return tmp_path / f"ieee_pause_{task_id}"

        def clear_pause_request(self, task_id):
            self.pause_path(task_id).unlink(missing_ok=True)

    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.QueuePdfDownloadService",
        FakeDownloadService,
    )
    monkeypatch.setattr(
        "app.tasks.handlers.discover_pdfs_for_queue.IeeeSessionService",
        FakeSession,
    )

    handle_discover_pdfs_for_queue(db, task)

    payload = json.loads(task.payload_json)
    assert received == [item_id]
    assert task.progress_current == task.progress_total == 1
    assert payload["result_summary"]["ieee_downloaded"] == 1
    assert payload["result_summary"]["resumed_count"] == 1
    db.close()


def test_task_runner_does_not_overwrite_waiting_for_login_status(tmp_path):
    factory = _session_factory()
    db = factory()
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=1,
        task_type="hold_test",
        status="pending",
    )
    db.add(task)
    db.commit()

    class HoldManager:
        def run(self, db, task):
            task.status = "waiting_for_login"
            task.stage = "waiting_for_login"
            db.commit()

    runner = TaskRunner(
        task_repository=TaskRepository(db),
        task_manager=HoldManager(),
    )
    result = runner.run_once()

    assert result.status == "waiting_for_login"
    assert result.stage == "waiting_for_login"
    db.close()


def test_queue_page_shows_ieee_session_actions_for_waiting_task(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    session_id, _item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        status="waiting_for_login",
        stage="waiting_for_login",
        payload_json=json.dumps(
            {
                "ieee_session_status": {
                    "status": "waiting_for_login",
                    "message": "请完成机构登录",
                }
            }
        ),
    )
    db.add(task)
    db.commit()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            f"/scholar-sessions/{session_id}/queue?discover_task_id={task.id}"
        )
        assert response.status_code == 200
        assert "打开 IEEE 登录窗口" in response.text
        assert "检测登录状态" in response.text
        assert "继续 IEEE 下载" in response.text
        assert "<dt>个人账号</dt>" in response.text
        assert "<dt>机构访问</dt>" in response.text
        assert 'data-task-role="ieee-personal-login"' in response.text
        assert 'data-task-role="ieee-institution-access"' in response.text
        assert 'data-task-role="ieee-access-status"' not in response.text
        assert f"/scholar-sessions/{session_id}/tasks/{task.id}/resume" in response.text
        assert 'data-active="true"' in response.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_ieee_login_route_redirects_instead_of_500_on_start_failure(
    tmp_path, monkeypatch
):
    factory = _session_factory()
    db = factory()
    session_id, _item_id = _ieee_item(db, tmp_path)
    task = AnalysisTask(
        session_kind="scholar_analysis",
        session_id=session_id,
        task_type="discover_pdfs_for_queue",
        status="waiting_for_login",
        payload_json="{}",
    )
    db.add(task)
    db.commit()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(
        IeeeSessionService,
        "open_login_window",
        lambda self: (_ for _ in ()).throw(OSError("unsupported fifo")),
    )
    monkeypatch.setattr(
        IeeeSessionService,
        "record_failure",
        lambda self, message: IeeeSessionStatus("failed", message=message),
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            f"/scholar-sessions/{session_id}/ieee-session/open",
            data={"task_id": task.id},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with factory() as verify_db:
            refreshed = verify_db.get(AnalysisTask, task.id)
            payload = json.loads(refreshed.payload_json)
            assert payload["ieee_session_status"]["status"] == "failed"
            assert "OSError" in payload["ieee_session_status"]["message"]
    finally:
        app.dependency_overrides.clear()
        db.close()
