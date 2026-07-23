"""FastAPI entrypoint for the Phase 0 project skeleton."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.base import init_db
from app.routers.analysis_templates import router as analysis_templates_router
from app.routers.exports import router as exports_router
from app.routers.external_citations import router as external_citations_router
from app.routers.highlight_cards import router as highlight_cards_router
from app.routers.honor_imports import router as honor_imports_router
from app.routers.paper_sessions import router as paper_sessions_router
from app.routers.pdf_library import router as pdf_library_router
from app.routers.pdf_inbox import router as pdf_inbox_router
from app.routers.scholar_evidence import router as scholar_evidence_router
from app.routers.scholar_queue import router as scholar_queue_router
from app.routers.scholar_sessions import router as scholar_sessions_router
from app.routers.tasks import router as tasks_router
from app.routers.uploads import router as uploads_router
from app.services.provider_health_service import ProviderHealthService


BASE_DIR = Path(__file__).resolve().parent

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(paper_sessions_router)
app.include_router(scholar_sessions_router)
app.include_router(scholar_queue_router)
app.include_router(scholar_evidence_router)
app.include_router(highlight_cards_router)
app.include_router(honor_imports_router)
app.include_router(analysis_templates_router)
app.include_router(pdf_library_router)
app.include_router(pdf_inbox_router)
app.include_router(tasks_router)
app.include_router(uploads_router)
app.include_router(exports_router)
app.include_router(external_citations_router)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": settings.app_name,
            "environment": settings.environment,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health.json")
def health_json():
    provider_health = ProviderHealthService()
    providers = provider_health.all_provider_status()
    llm_provider = provider_health.llm_provider_status()
    return {
        "status": "ok",
        "author_provider": providers["author_provider"]["provider"],
        "citation_provider": providers["citation_provider"]["provider"],
        "metadata_provider": providers["metadata_provider"]["provider"],
        "llm_provider_name": llm_provider["provider"],
        "llm_model": llm_provider["model"],
        "base_url_configured": llm_provider["base_url_configured"],
        "api_key_configured": llm_provider["api_key_configured"],
        "llm_provider": llm_provider,
        "providers": providers,
    }


@app.get("/providers/health")
def providers_health():
    return ProviderHealthService().all_provider_status()
