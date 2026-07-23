import os


def test_settings_loads_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_IMPACT_TEST_DOTENV_VALUE", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text('ACADEMIC_IMPACT_TEST_DOTENV_VALUE="dotenv-model"\n', encoding="utf-8")

    from app.core.config import load_dotenv_file

    load_dotenv_file(env_path)

    assert os.environ["ACADEMIC_IMPACT_TEST_DOTENV_VALUE"] == "dotenv-model"


def test_env_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_IMPACT_AUTHOR_PROVIDER", raising=False)
    monkeypatch.delenv("ACADEMIC_IMPACT_DATABASE_URL", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "ACADEMIC_IMPACT_AUTHOR_PROVIDER=dblp",
                "ACADEMIC_IMPACT_DATABASE_URL=sqlite:///dotenv.db",
            ]
        ),
        encoding="utf-8",
    )

    from app.core.config import Settings, load_dotenv_file

    load_dotenv_file(env_path)
    settings = Settings()

    assert settings.author_provider == "dblp"
    assert settings.database_url == "sqlite:///dotenv.db"


def test_shell_env_overrides_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_IMPACT_CITATION_PROVIDER", "fake")
    env_path = tmp_path / ".env"
    env_path.write_text("ACADEMIC_IMPACT_CITATION_PROVIDER=openalex\n", encoding="utf-8")

    from app.core.config import Settings, load_dotenv_file

    load_dotenv_file(env_path)

    assert Settings().citation_provider == "fake"


def test_health_uses_configured_providers(monkeypatch):
    monkeypatch.setenv("ACADEMIC_IMPACT_AUTHOR_PROVIDER", "dblp")
    monkeypatch.setenv("ACADEMIC_IMPACT_CITATION_PROVIDER", "openalex")
    monkeypatch.setenv("ACADEMIC_IMPACT_METADATA_PROVIDER", "openalex")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_MODEL", "deepseek-chat")

    from app.main import health_json

    payload = health_json()

    assert payload["providers"]["author_provider"]["provider"] == "dblp"
    assert payload["providers"]["citation_provider"]["provider"] == "openalex"
    assert payload["providers"]["metadata_provider"]["provider"] == "openalex"
    assert payload["llm_provider"]["provider"] == "openai_compatible"
    assert payload["llm_provider"]["model"] == "deepseek-chat"
    assert payload["llm_provider"]["base_url_configured"] is True


def test_env_example_not_loaded_as_runtime_config(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_IMPACT_METADATA_PROVIDER", raising=False)
    (tmp_path / ".env.example").write_text(
        "ACADEMIC_IMPACT_METADATA_PROVIDER=openalex\n",
        encoding="utf-8",
    )

    from app.core.config import Settings, load_dotenv_file

    load_dotenv_file(tmp_path / ".env")

    assert Settings().metadata_provider == "fake"


def test_health_redacts_api_key(monkeypatch):
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_API_KEY", "do-not-print-this")
    monkeypatch.setenv("ACADEMIC_IMPACT_LLM_MODEL", "deepseek-chat")

    from app.main import health_json

    payload = health_json()

    assert payload["llm_provider"]["api_key_configured"] is True
    assert "do-not-print-this" not in str(payload)


def test_ieee_downloader_settings_are_loaded(monkeypatch):
    monkeypatch.setenv("ACADEMIC_IMPACT_IEEE_DOWNLOADER_COMMAND", "/opt/ieee/ieee-download")
    monkeypatch.setenv("ACADEMIC_IMPACT_IEEE_DOWNLOADER_DOWNLOAD_DIR", "/data/ieee/downloads")

    from app.core.config import Settings

    configured = Settings()
    assert configured.ieee_downloader_command == "/opt/ieee/ieee-download"
    assert configured.ieee_downloader_download_dir == "/data/ieee/downloads"
