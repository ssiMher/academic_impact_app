"""Local scholar citation expansion task handler."""

import json

from sqlalchemy.orm import Session

from app.models import AnalysisTask, ScholarAnalysisSession
from app.providers.citation_provider import get_citation_provider
from app.repositories.citation_edge_repo import CitationEdgeRepository
from app.repositories.scholar_session_repo import ScholarSessionRepository
from app.schemas.provider import ProviderPublication


def handle_expand_scholar_citations(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != "scholar_analysis":
        raise ValueError("expand_scholar_citations only supports scholar_analysis sessions")

    scholar_session = db.get(ScholarAnalysisSession, task.session_id)
    if scholar_session is None:
        raise ValueError(f"ScholarAnalysisSession {task.session_id} was not found")

    scholar_repo = ScholarSessionRepository(db)
    edge_repo = CitationEdgeRepository(db)
    selected_publications = scholar_repo.list_selected_publications(scholar_session.id)
    if not selected_publications:
        raise ValueError("No selected scholar publications found for citation expansion")

    provider = get_citation_provider()
    payload = _task_payload(task)
    limit_per_publication = int(payload.get("limit_per_publication") or 100)
    task.progress_total = len(selected_publications)
    task.progress_current = 0
    task.stage = "expanding_citations"
    task.stage_message = f"Expanding scholar citations with provider={provider.provider_name}; limit={limit_per_publication}."
    db.flush()

    fetched_count = 0
    saved_edges_count = 0
    duplicate_count = 0
    skipped_count = 0
    cited_by_count_total = 0
    cursor_pages = 0
    expansion_complete = True
    provider_metadata = {}
    for index, scholar_publication in enumerate(selected_publications, start=1):
        if hasattr(provider, "list_citing_papers"):
            target_publication = ProviderPublication(
                title=scholar_publication.title,
                year=scholar_publication.year,
                venue=scholar_publication.venue,
                doi=scholar_publication.doi,
            )
            citation_edges = provider.list_citing_papers(  # type: ignore[attr-defined]
                target_publication,
                limit=limit_per_publication,
            )
        else:
            citation_edges = provider.discover_citations(scholar_publication.title)
        provider_metadata = getattr(provider, "last_citation_expansion", {}) or {}
        fetched_count += int(provider_metadata.get("fetched_count") or len(citation_edges))
        cited_by_count = provider_metadata.get("openalex_cited_by_count")
        if isinstance(cited_by_count, int):
            cited_by_count_total += cited_by_count
        cursor_pages += int(provider_metadata.get("cursor_pages") or 0)
        if provider_metadata and provider_metadata.get("expansion_complete") is False:
            expansion_complete = False
        for citation_edge in citation_edges:
            citing_publication = scholar_repo.get_or_create_publication(citation_edge.citing_paper)
            existing_edge = edge_repo.get_existing(
                scholar_session_id=scholar_session.id,
                cited_publication_id=scholar_publication.publication_id,
                citing_publication_id=citing_publication.id,
            )
            edge_repo.create(
                scholar_session_id=scholar_session.id,
                cited_publication_id=scholar_publication.publication_id,
                citing_publication_id=citing_publication.id,
                provider_name=provider.provider_name,
                edge_meta={
                    "target_title": citation_edge.target_title,
                    "source_url": citation_edge.citing_paper.source_url,
                    "citation_contexts": citation_edge.citing_paper.citation_contexts,
                    "openalex_cited_by_count": provider_metadata.get("openalex_cited_by_count"),
                    "openalex_work_id": provider_metadata.get("openalex_work_id"),
                    "citation_expansion_limit": limit_per_publication,
                    "citation_expansion_complete": provider_metadata.get("expansion_complete"),
                },
            )
            if existing_edge is None:
                saved_edges_count += 1
            else:
                duplicate_count += 1
        task.progress_current = index

    scholar_session.citation_edge_count = edge_repo.count_for_session(scholar_session.id)
    scholar_session.status = "expanded"
    task.stage_message = (
        f"provider={provider.provider_name}; "
        f"openalex_cited_by_count={cited_by_count_total or provider_metadata.get('openalex_cited_by_count') or 'unknown'}; "
        f"fetched={fetched_count}; "
        f"saved_edges={saved_edges_count}; "
        f"duplicates={duplicate_count}; "
        f"skipped={skipped_count}; "
        f"limit={limit_per_publication}; "
        f"pages={cursor_pages or 'unknown'}; "
        f"complete={str(expansion_complete).lower()}"
    )
    db.commit()


def _task_payload(task: AnalysisTask) -> dict:
    if not task.payload_json:
        return {}
    try:
        payload = json.loads(task.payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
