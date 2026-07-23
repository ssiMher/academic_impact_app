"""Repository for scholar deep analysis queue items."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CitationAuthorAnnotation,
    CitationEdge,
    DeepAnalysisQueueItem,
    NotableAuthor,
    PdfAsset,
    Publication,
)


class ScholarQueueRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_citation_edges(self, scholar_session_id: int) -> List[CitationEdge]:
        statement = (
            select(CitationEdge)
            .where(CitationEdge.scholar_session_id == scholar_session_id)
            .order_by(CitationEdge.id.asc())
        )
        return list(self.db.scalars(statement))

    def get_publication(self, publication_id: int) -> Optional[Publication]:
        return self.db.get(Publication, publication_id)

    def get_asset(self, asset_id: int) -> Optional[PdfAsset]:
        return self.db.get(PdfAsset, asset_id)

    def find_queue_item_by_edge(self, citation_edge_id: int) -> Optional[DeepAnalysisQueueItem]:
        statement = select(DeepAnalysisQueueItem).where(
            DeepAnalysisQueueItem.citation_edge_id == citation_edge_id
        )
        return self.db.scalars(statement).first()

    def get_queue_item(self, item_id: int) -> Optional[DeepAnalysisQueueItem]:
        return self.db.get(DeepAnalysisQueueItem, item_id)

    def create_queue_item(self, **values) -> DeepAnalysisQueueItem:
        item = DeepAnalysisQueueItem(**values)
        self.db.add(item)
        self.db.flush()
        return item

    def list_queue_items(self, scholar_session_id: int) -> List[DeepAnalysisQueueItem]:
        statement = (
            select(DeepAnalysisQueueItem)
            .where(DeepAnalysisQueueItem.scholar_session_id == scholar_session_id)
            .order_by(DeepAnalysisQueueItem.priority_score.desc(), DeepAnalysisQueueItem.year.desc())
        )
        return list(self.db.scalars(statement))

    def list_all_queue_items_with_pdf(self) -> List[DeepAnalysisQueueItem]:
        statement = select(DeepAnalysisQueueItem).where(
            DeepAnalysisQueueItem.pdf_asset_id.is_not(None)
        )
        return list(self.db.scalars(statement))

    def list_pdf_assets(self) -> List[PdfAsset]:
        statement = select(PdfAsset).order_by(PdfAsset.id.desc())
        return list(self.db.scalars(statement))

    def find_asset_for_publication(self, publication_id: int) -> Optional[PdfAsset]:
        from app.models import CitingPaper, ScholarPublication

        citing_statement = select(CitingPaper).where(
            CitingPaper.publication_id == publication_id,
            CitingPaper.pdf_asset_id.is_not(None),
        )
        citing_paper = self.db.scalars(citing_statement).first()
        if citing_paper is not None:
            return self.get_asset(citing_paper.pdf_asset_id)

        scholar_statement = select(ScholarPublication).where(
            ScholarPublication.publication_id == publication_id,
            ScholarPublication.pdf_asset_id.is_not(None),
        )
        scholar_publication = self.db.scalars(scholar_statement).first()
        if scholar_publication is not None:
            return self.get_asset(scholar_publication.pdf_asset_id)

        return None

    def list_annotations_for_queue_item(self, queue_item_id: int) -> List[CitationAuthorAnnotation]:
        statement = (
            select(CitationAuthorAnnotation)
            .where(CitationAuthorAnnotation.queue_item_id == queue_item_id)
            .order_by(CitationAuthorAnnotation.id.asc())
        )
        return list(self.db.scalars(statement))

    def list_notable_authors(self) -> List[NotableAuthor]:
        return list(self.db.scalars(select(NotableAuthor).order_by(NotableAuthor.id.asc())))
