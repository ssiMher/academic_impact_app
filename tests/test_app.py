from pathlib import Path

from starlette.requests import Request


def test_app_can_import():
    from app.main import app

    assert app is not None


def test_health_returns_ok():
    from app.main import health

    assert health() == {"status": "ok"}


def test_homepage_returns_ok():
    from app.main import homepage

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = homepage(request)
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "创建普通论文分析" in body
    assert 'href="/paper-sessions/new"' in body


def test_base_template_loads_app_css():
    from app.main import homepage

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = homepage(request)
    body = response.body.decode("utf-8")

    assert 'href="/static/css/app.css?v=' in body


def test_static_assets_have_cache_busting_version():
    source = (Path.cwd() / "app" / "templates" / "base.html").read_text(
        encoding="utf-8"
    )

    assert 'href="/static/css/app.css?v={{ static_asset_version }}"' in source
    assert 'src="/static/js/app.js?v={{ static_asset_version }}"' in source


def test_all_user_templates_extend_base_or_include_app_css():
    template_root = Path.cwd() / "app" / "templates"
    for template_path in template_root.rglob("*.html"):
        relative_parts = set(template_path.relative_to(template_root).parts)
        if template_path.name == "base.html" or "components" in relative_parts:
            continue
        source = template_path.read_text(encoding="utf-8")
        assert (
            '{% extends "base.html" %}' in source
            or 'href="/static/css/app.css"' in source
        ), str(template_path)
