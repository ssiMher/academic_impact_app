"""Application settings and lightweight .env loading."""

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv_file(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_simple_quotes(value.strip())
        if key:
            os.environ.setdefault(key, value)


def _strip_simple_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env(name: str, default: str, *legacy_names: str) -> str:
    for candidate in (name, *legacy_names):
        value = os.getenv(candidate)
        if value is not None:
            return value
    return default


def _env_int(name: str, default: int, *legacy_names: str) -> int:
    return int(_env(name, str(default), *legacy_names))


def _env_float(name: str, default: float, *legacy_names: str) -> float:
    return float(_env(name, str(default), *legacy_names))


def _env_bool(name: str, default: bool, *legacy_names: str) -> bool:
    value = _env(name, str(default).lower(), *legacy_names)
    return value.lower() in {"1", "true", "yes", "on"}


load_dotenv_file()


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_APP_NAME", "Academic Impact App", "APP_NAME"))
    environment: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_APP_ENV", "development", "APP_ENV"))
    log_level: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_LOG_LEVEL", "INFO", "LOG_LEVEL"))
    database_url: str = field(
        default_factory=lambda: _env(
            "ACADEMIC_IMPACT_DATABASE_URL",
            "sqlite:///var/academic_impact_app.db",
            "DATABASE_URL",
        )
    )
    pdf_asset_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_PDF_ASSET_DIR", "var/pdf_assets", "PDF_ASSET_DIR"))
    extracted_text_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_EXTRACTED_TEXT_DIR", "var/extracted_text", "EXTRACTED_TEXT_DIR"))
    export_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_EXPORT_DIR", "var/exports", "EXPORT_DIR"))
    pdf_max_upload_bytes: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_PDF_MAX_UPLOAD_BYTES", 100 * 1024 * 1024, "PDF_MAX_UPLOAD_BYTES"))
    author_provider: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_AUTHOR_PROVIDER", "fake"))
    citation_provider: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_CITATION_PROVIDER", "fake"))
    metadata_provider: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_METADATA_PROVIDER", "fake"))
    llm_provider: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_LLM_PROVIDER", "fake"))
    llm_base_url: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_LLM_MODEL", "gpt-4.1-mini"))
    llm_timeout_seconds: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_LLM_TIMEOUT_SECONDS", 30))
    llm_max_output_tokens: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_LLM_MAX_OUTPUT_TOKENS", 8192))
    llm_transient_max_retries: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_LLM_TRANSIENT_MAX_RETRIES", 2))
    llm_retry_backoff_seconds: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_LLM_RETRY_BACKOFF_SECONDS", 1.0))
    provider_timeout_seconds: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_PROVIDER_TIMEOUT_SECONDS", 20))
    provider_cache_enabled: bool = field(default_factory=lambda: _env_bool("ACADEMIC_IMPACT_PROVIDER_CACHE_ENABLED", True))
    unpaywall_email: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_UNPAYWALL_EMAIL", "", "UNPAYWALL_EMAIL"))
    unpaywall_timeout_seconds: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_UNPAYWALL_TIMEOUT_SECONDS", 8))
    llm_disable_thinking: bool = field(default_factory=lambda: _env_bool("ACADEMIC_IMPACT_LLM_DISABLE_THINKING", True))
    pdf_library_dirs: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_PDF_LIBRARY_DIRS", ""))
    pdf_index_path: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_PDF_INDEX_PATH", "var/pdf_library_index.json"))
    pdf_max_scan_files: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_PDF_MAX_SCAN_FILES", 1000))
    pdf_match_threshold: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_PDF_MATCH_THRESHOLD", 0.82))
    pdf_inbox_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_PDF_INBOX_DIR", "./var/pdf_inbox"))
    pdf_inbox_auto_scan: bool = field(default_factory=lambda: _env_bool("ACADEMIC_IMPACT_PDF_INBOX_AUTO_SCAN", True))
    pdf_inbox_match_threshold: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_PDF_INBOX_MATCH_THRESHOLD", 0.82))
    ieee_downloader_command: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_IEEE_DOWNLOADER_COMMAND", ""))
    ieee_downloader_work_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_IEEE_DOWNLOADER_WORK_DIR", ""))
    ieee_downloader_download_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_IEEE_DOWNLOADER_DOWNLOAD_DIR", ""))
    ieee_downloader_timeout_seconds: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_IEEE_DOWNLOADER_TIMEOUT_SECONDS", 900))
    ieee_downloader_portal_url: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_IEEE_DOWNLOADER_PORTAL_URL", ""))
    ieee_profile_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_IEEE_PROFILE_DIR", ""))
    ieee_runtime_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_IEEE_RUNTIME_DIR", ""))
    ieee_min_request_interval_seconds: float = field(default_factory=lambda: _env_float("ACADEMIC_IMPACT_IEEE_MIN_REQUEST_INTERVAL_SECONDS", 8.0))
    fulltext_direct_max_chars: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS", 120000))
    citation_expansion_default_limit: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_CITATION_EXPANSION_DEFAULT_LIMIT", 100))
    citation_expansion_max_limit: int = field(default_factory=lambda: _env_int("ACADEMIC_IMPACT_CITATION_EXPANSION_MAX_LIMIT", 1000))
    debug_save_llm_prompts: bool = field(default_factory=lambda: _env_bool("ACADEMIC_IMPACT_DEBUG_SAVE_LLM_PROMPTS", False))
    debug_llm_dir: str = field(default_factory=lambda: _env("ACADEMIC_IMPACT_DEBUG_LLM_DIR", "./var/debug/llm_prompts"))


settings = Settings()
