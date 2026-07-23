"""Local discover_paper task handler using the fake citation provider."""

import json

from sqlalchemy.orm import Session

from app.models import AnalysisTask, CitingPaper, PaperAnalysisSession, Publication
from app.providers.citation_provider import get_citation_provider


def normalize_title(title: str) -> str:
    return " ".join(title.lower().split())


def handle_discover_paper(db: Session, task: AnalysisTask) -> None:
    if task.session_kind != "paper_analysis":
        raise ValueError("discover_paper only supports paper_analysis sessions")

    paper_session = db.get(PaperAnalysisSession, task.session_id)
    if paper_session is None:
        raise ValueError(f"PaperAnalysisSession {task.session_id} was not found")

    provider = get_citation_provider()
    citation_edges = provider.discover_citations(paper_session.query_text)

    task.progress_total = len(citation_edges)
    task.progress_current = 0
    task.stage = "discovering"
    task.stage_message = "Discovering citing papers with fake provider."
    db.flush()

    for index, edge in enumerate(citation_edges, start=1):
        citing_publication = edge.citing_paper
        publication = Publication(
            title=citing_publication.title,
            normalized_title=normalize_title(citing_publication.title),
            year=citing_publication.year,
            venue=citing_publication.venue,
            doi=citing_publication.doi,
            authors_json=json.dumps(citing_publication.authors),
        )
        db.add(publication)
        db.flush()

        db.add(
            CitingPaper(
                paper_session_id=paper_session.id,
                publication_id=publication.id,
                local_code=f"C{index:03d}",
                analysis_status="discovered",
            )
        )
        task.progress_current = index

    paper_session.provider_total_citation_count = len(citation_edges)
    paper_session.displayed_candidate_count = len(citation_edges)
    db.commit()
