"""Repository for scholar analysis sessions."""

import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Publication, ScholarAnalysisSession, ScholarPublication
from app.schemas.provider import ProviderAuthorIdentity, ProviderPublication


def normalize_title(title: str) -> str:
    return " ".join(title.lower().split())


class ScholarSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_with_publications(
        self,
        author_identity: ProviderAuthorIdentity,
    ) -> ScholarAnalysisSession:
        session = ScholarAnalysisSession(
            display_name=author_identity.display_name,
            dblp_id=author_identity.dblp_id,
            openalex_id=author_identity.openalex_id,
            scopus_author_id=author_identity.scopus_author_id,
            status="created" if author_identity.publications else "no_publications",
            publication_count=len(author_identity.publications),
            citation_edge_count=0,
        )
        self.db.add(session)
        self.db.flush()

        for index, provider_publication in enumerate(author_identity.publications, start=1):
            publication = self.get_or_create_publication(provider_publication)
            self.db.add(
                ScholarPublication(
                    scholar_session_id=session.id,
                    publication_id=publication.id,
                    local_code=f"S{index:03d}",
                    title=provider_publication.title,
                    year=provider_publication.year,
                    venue=provider_publication.venue,
                    doi=provider_publication.doi,
                    selected_for_expansion=False,
                )
            )

        self.db.commit()
        self.db.refresh(session)
        return session

    def get_or_create_publication(self, provider_publication: ProviderPublication) -> Publication:
        existing = self.find_publication(provider_publication)
        if existing is not None:
            self._fill_missing_provider_ids(existing, provider_publication)
            return existing

        publication = Publication(
            title=provider_publication.title,
            normalized_title=normalize_title(provider_publication.title),
            year=provider_publication.year,
            venue=provider_publication.venue,
            doi=provider_publication.doi,
            openalex_id=provider_publication.openalex_id,
            authors_json=json.dumps(provider_publication.authors),
        )
        self.db.add(publication)
        self.db.flush()
        return publication

    def find_publication(
        self,
        provider_publication: ProviderPublication,
    ) -> Optional[Publication]:
        if provider_publication.openalex_id:
            statement = select(Publication).where(
                Publication.openalex_id == provider_publication.openalex_id
            )
            publication = self.db.scalars(statement).first()
            if publication is not None:
                return publication

        if provider_publication.doi:
            statement = select(Publication).where(Publication.doi == provider_publication.doi)
            publication = self.db.scalars(statement).first()
            if publication is not None:
                return publication

        normalized_title = normalize_title(provider_publication.title)
        statement = select(Publication).where(
            Publication.normalized_title == normalized_title,
            Publication.year == provider_publication.year,
        )
        return self.db.scalars(statement).first()

    def _fill_missing_provider_ids(
        self,
        publication: Publication,
        provider_publication: ProviderPublication,
    ) -> None:
        changed = False
        if provider_publication.openalex_id and not publication.openalex_id:
            publication.openalex_id = provider_publication.openalex_id
            changed = True
        if provider_publication.doi and not publication.doi:
            publication.doi = provider_publication.doi
            changed = True
        if not publication.normalized_title:
            publication.normalized_title = normalize_title(publication.title)
            changed = True
        if changed:
            self.db.flush()

    def get_by_id(self, session_id: int) -> Optional[ScholarAnalysisSession]:
        return self.db.get(ScholarAnalysisSession, session_id)

    def list_publications(self, session_id: int) -> List[ScholarPublication]:
        statement = (
            select(ScholarPublication)
            .where(ScholarPublication.scholar_session_id == session_id)
            .order_by(ScholarPublication.id.asc())
        )
        return list(self.db.scalars(statement))

    def list_selected_publications(self, session_id: int) -> List[ScholarPublication]:
        statement = (
            select(ScholarPublication)
            .where(
                ScholarPublication.scholar_session_id == session_id,
                ScholarPublication.selected_for_expansion.is_(True),
            )
            .order_by(ScholarPublication.id.asc())
        )
        return list(self.db.scalars(statement))

    def mark_selected_for_expansion(
        self,
        *,
        session_id: int,
        publication_ids: List[int],
    ) -> List[ScholarPublication]:
        statement = select(ScholarPublication).where(
            ScholarPublication.scholar_session_id == session_id,
            ScholarPublication.id.in_(publication_ids),
        )
        publications = list(self.db.scalars(statement))
        selected_ids = {publication.id for publication in publications}
        if selected_ids != set(publication_ids):
            missing = sorted(set(publication_ids) - selected_ids)
            raise ValueError(f"ScholarPublication ids not found for session: {missing}")

        for publication in publications:
            publication.selected_for_expansion = True

        self.db.commit()
        return publications

    def update_citation_edge_count(
        self,
        *,
        session_id: int,
        citation_edge_count: int,
    ) -> ScholarAnalysisSession:
        session = self.get_by_id(session_id)
        if session is None:
            raise ValueError(f"ScholarAnalysisSession {session_id} was not found")
        session.citation_edge_count = citation_edge_count
        self.db.commit()
        self.db.refresh(session)
        return session
