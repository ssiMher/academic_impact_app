from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def read_python_files(path: Path):
    return sorted(path.glob("*.py"))


def test_services_do_not_import_old_project_core_or_session_state():
    forbidden = (
        "academic_impact_web",
        "impact_core",
        "scholar_core",
        "run_pipeline",
        "session.json",
    )

    for path in read_python_files(APP_ROOT / "services"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_routers_do_not_import_legacy_adapters():
    for path in read_python_files(APP_ROOT / "routers"):
        source = path.read_text(encoding="utf-8")
        assert "app.legacy.adapters" not in source, path


def test_legacy_adapters_do_not_access_database_network_or_web_responses():
    forbidden = (
        "requests.",
        "requests.get",
        "requests.post",
        "httpx.",
        "urllib.request",
        "urlopen",
        "aiohttp",
        "from sqlalchemy",
        "from app.db",
        "SessionLocal",
        "FileResponse",
        "HTMLResponse",
        "RedirectResponse",
        "TemplateResponse",
    )

    for path in read_python_files(APP_ROOT / "legacy" / "adapters"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_legacy_adapters_do_not_return_session_json_state_shape():
    forbidden_state_keys = (
        '"papers"',
        '"task_state"',
        '"pending_discover"',
        '"session_dir"',
        '"session.json"',
    )

    for path in read_python_files(APP_ROOT / "legacy" / "adapters"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden_state_keys), path


def test_legacy_adapters_do_not_depend_on_user_absolute_paths():
    forbidden_path_markers = (
        "/home/",
        "/Users/",
        "/mnt/",
        "C:\\",
        "ACADEMIC_IMPACT_DOWNLOAD_DIR",
    )

    for path in read_python_files(APP_ROOT / "legacy" / "adapters"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden_path_markers), path
