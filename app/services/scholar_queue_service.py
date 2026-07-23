"""Service for building and managing scholar deep analysis queues."""

import json
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from fastapi import Depends
from sqlalchemy.orm import Session

from app.analysis.queue_scoring import classify_venue_tier, score_queue_item
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    AnalysisTask,
    CitationEdge,
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    PdfAsset,
    PdfAssetPublicationLink,
    Publication,
    StrongEvidence,
)
from app.models.constants import (
    PDF_STATUS_LOCAL_LIBRARY,
    PDF_STATUS_MANUAL,
    PDF_STATUS_NEED,
    PDF_STATUS_REUSED,
    READY_PDF_STATUSES,
    SCHOLAR_ANALYSIS_SESSION_KIND,
    is_pdf_ready_status,
)
from app.pdf.match import normalize_title_for_match, title_similarity
from app.pdf.library import parse_library_dirs
from app.pdf.publisher import classify_publisher_from_doi_or_url
from app.repositories.pdf_repo import PdfRepository
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.services.pdf_discovery_service import PdfDiscoveryService
from app.repositories.task_repo import TaskRepository
from app.services.pdf_library_service import PdfLibraryService
from app.services.pdf_service import PdfService
from app.services.importance import is_queue_item_important
from app.services.task_service import TaskService
from app.services.template_service import TemplateService


class ScholarQueueItemNotFoundError(ValueError):
    pass


class QueueItemManualPdfExistsError(ValueError):
    pass


class PdfAssetNotFoundError(ValueError):
    pass


class ScholarQueueService:
    def __init__(
        self,
        *,
        repository: ScholarQueueRepository,
        pdf_library_service: PdfLibraryService,
    ) -> None:
        self.repository = repository
        self.pdf_library_service = pdf_library_service

    def build_queue(self, session_id: int) -> List[DeepAnalysisQueueItem]:
        items = []
        for edge in self.repository.list_citation_edges(session_id):
            cited = self.repository.get_publication(edge.cited_publication_id)
            citing = self.repository.get_publication(edge.citing_publication_id)
            if cited is None or citing is None:
                continue

            existing = self.repository.find_queue_item_by_edge(edge.id)
            values = self._build_item_values(edge, cited, citing, existing)
            if existing is None:
                item = self.repository.create_queue_item(**values)
            else:
                for key, value in values.items():
                    if key in {"queue_status", "user_review_status", "user_note"}:
                        continue
                    setattr(existing, key, value)
                item = existing
            TemplateService(self.repository.db).match_templates_for_queue_item(item.id)
            self._auto_attach_reusable_pdf(item)
            items.append(item)

        self.repository.db.commit()
        return self.list_queue_items(session_id, filters={"view": "all"})

    def rebuild_queue(self, session_id: int) -> List[DeepAnalysisQueueItem]:
        return self.build_queue(session_id)

    def list_queue_items(
        self,
        session_id: int,
        filters: Optional[Dict[str, str]] = None,
        pagination: Optional[dict] = None,
    ) -> List[DeepAnalysisQueueItem]:
        view = (filters or {}).get("view", "all")
        items = self.repository.list_queue_items(session_id)
        changed = False
        for item in items:
            changed = self._auto_attach_reusable_pdf(item) or changed
        if changed:
            self.repository.db.commit()
        for item in items:
            self._attach_pdf_display_fields(item)
        items = [item for item in items if self._matches_view(item, view)]
        return sorted(
            items,
            key=lambda item: (
                item.priority_score,
                item.year or 0,
                self._venue_sort_value(item.venue_tier),
                self._pdf_sort_value(item.pdf_readiness_status),
            ),
            reverse=True,
        )

    def get_queue_summary(self, session_id: int) -> Dict[str, int]:
        items = self.repository.list_queue_items(session_id)
        citation_edge_count = len(self.repository.list_citation_edges(session_id))
        return {
            "total": len(items),
            "total_queue_items": len(items),
            "citation_edge_count": citation_edge_count,
            "ready_count": sum(
                1 for item in items if is_pdf_ready_status(item.pdf_readiness_status)
            ),
            "ready_items": sum(
                1 for item in items if is_pdf_ready_status(item.pdf_readiness_status)
            ),
            "need_pdf_count": sum(
                1 for item in items if item.pdf_readiness_status == PDF_STATUS_NEED
            ),
            "need_pdf_items": sum(
                1 for item in items if item.pdf_readiness_status == PDF_STATUS_NEED
            ),
            "selected_count": sum(1 for item in items if item.queue_status == "selected"),
            "selected_items": sum(1 for item in items if item.queue_status == "selected"),
            "analyzed_count": sum(1 for item in items if item.queue_status == "analyzed"),
            "analyzed_items": sum(1 for item in items if item.queue_status == "analyzed"),
            "failed_count": sum(1 for item in items if item.queue_status == "failed"),
            "failed_items": sum(1 for item in items if item.queue_status == "failed"),
            "important_count": sum(
                1
                for item in items
                if is_queue_item_important(
                    item,
                    self.repository.list_annotations_for_queue_item(item.id),
                )
            ),
            "strong_evidence_items": self.repository.db.query(StrongEvidence)
            .filter_by(scholar_session_id=session_id)
            .count(),
        }

    def selected_ready_item_ids(self, session_id: int) -> List[int]:
        return [
            item.id
            for item in self.repository.list_queue_items(session_id)
            if item.queue_status == "selected"
            and is_pdf_ready_status(item.pdf_readiness_status)
        ]

    def item_ids_for_view(self, session_id: int, view: str) -> List[int]:
        return [item.id for item in self.list_queue_items(session_id, filters={"view": view})]

    def item_ids_for_ready(self, session_id: int) -> List[int]:
        return [
            item.id
            for item in self.repository.list_queue_items(session_id)
            if is_pdf_ready_status(item.pdf_readiness_status)
        ]

    def item_ids_for_important(self, session_id: int) -> List[int]:
        return [
            item.id
            for item in self.repository.list_queue_items(session_id)
            if self._matches_view(item, "important")
        ]

    def attach_existing_pdf_to_queue_item(
        self,
        *,
        session_id: int,
        item_id: int,
        pdf_asset_id: int,
    ) -> DeepAnalysisQueueItem:
        item = self.repository.get_queue_item(item_id)
        if item is None or item.scholar_session_id != session_id:
            raise ScholarQueueItemNotFoundError(
                f"DeepAnalysisQueueItem {item_id} was not found"
            )
        asset = self.repository.get_asset(pdf_asset_id)
        if asset is None:
            raise PdfAssetNotFoundError(f"PdfAsset {pdf_asset_id} was not found")
        existing_asset = (
            self.repository.get_asset(item.pdf_asset_id) if item.pdf_asset_id else None
        )
        if (
            item.pdf_readiness_status == PDF_STATUS_MANUAL
            and existing_asset is not None
            and existing_asset.source_type == "upload"
        ):
            raise QueueItemManualPdfExistsError(
                "Queue item already has a manual PDF. Replace is not supported."
            )
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = self._readiness_for_attached_asset(asset, reused=True)
        publication = self.repository.get_publication(item.citing_publication_id)
        self._create_pdf_publication_link(
            asset=asset,
            publication=publication,
            raw_title=item.citing_paper_title,
            match_method="manual_attach_existing_pdf",
            match_score=1.0,
            is_verified=True,
        )
        self._rescore(item)
        self.repository.db.commit()
        self.repository.db.refresh(item)
        self._attach_pdf_display_fields(item)
        return item

    def get_queue_item_for_session(
        self,
        *,
        session_id: int,
        item_id: int,
    ) -> DeepAnalysisQueueItem:
        item = self.repository.get_queue_item(item_id)
        if item is None or item.scholar_session_id != session_id:
            raise ScholarQueueItemNotFoundError(
                f"DeepAnalysisQueueItem {item_id} was not found"
            )
        return item

    def upload_pdf_for_queue_item(
        self,
        *,
        session_id: int,
        item_id: int,
        filename: str,
        content: bytes,
        mime_type: str,
        pdf_service: PdfService,
    ) -> DeepAnalysisQueueItem:
        item = self.repository.get_queue_item(item_id)
        if item is None or item.scholar_session_id != session_id:
            raise ScholarQueueItemNotFoundError(
                f"DeepAnalysisQueueItem {item_id} was not found"
            )

        existing_asset = (
            self.repository.get_asset(item.pdf_asset_id) if item.pdf_asset_id else None
        )
        if (
            item.pdf_readiness_status == PDF_STATUS_MANUAL
            and existing_asset is not None
            and existing_asset.source_type == "upload"
        ):
            raise QueueItemManualPdfExistsError(
                "Queue item already has a manual PDF. Replace is not supported."
            )

        asset = pdf_service.upload_pdf_asset(
            filename=filename,
            content=content,
            mime_type=mime_type,
        )
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = PDF_STATUS_MANUAL
        publication = self.repository.get_publication(item.citing_publication_id)
        self._create_pdf_publication_link(
            asset=asset,
            publication=publication,
            raw_title=item.citing_paper_title,
            match_method="manual_upload_for_queue_item",
            match_score=1.0,
            is_verified=True,
        )
        self._rescore(item)
        self.repository.db.commit()
        self.repository.db.refresh(item)
        self._attach_pdf_display_fields(item)
        return item

    def update_queue_item_review(
        self,
        item_id: int,
        review_status: str,
        user_note: str,
    ) -> DeepAnalysisQueueItem:
        item = self.repository.get_queue_item(item_id)
        if item is None:
            raise ValueError(f"DeepAnalysisQueueItem {item_id} was not found")
        item.user_review_status = review_status
        item.user_note = user_note
        self._rescore(item)
        self.repository.db.commit()
        self.repository.db.refresh(item)
        return item

    def select_queue_items(self, session_id: int, item_ids: List[int]) -> None:
        self._set_queue_status(session_id, item_ids, "selected")

    def skip_queue_items(self, session_id: int, item_ids: List[int]) -> None:
        self._set_queue_status(session_id, item_ids, "skipped")

    def clear_queue_selection(self, session_id: int, item_ids: List[int]) -> None:
        self._set_queue_status(session_id, item_ids, "pending")

    def enqueue_build_queue(self, session_id: int) -> AnalysisTask:
        return TaskService(TaskRepository(self.repository.db)).enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="build_scholar_queue",
        )

    def _build_item_values(self, edge, cited: Publication, citing: Publication, existing) -> dict:
        cited_authors = self._load_authors(cited)
        citing_authors = self._load_authors(citing)
        self_status, third_party_status = self._classify_self_citation(
            cited_authors=cited_authors,
            citing_authors=citing_authors,
        )
        pdf_asset = self._find_or_match_pdf_asset(citing.id, existing)
        pdf_readiness_status = self._pdf_readiness_status(pdf_asset)
        venue_tier = classify_venue_tier(citing.venue or "")
        queue_status = existing.queue_status if existing else "pending"
        review_status = existing.user_review_status if existing else "unreviewed"
        template_matches = TemplateService(self.repository.db).preview_matches_for_text(
            edge.scholar_session_id,
            self._template_match_text(
                citing_title=citing.title,
                cited_title=cited.title,
                venue=citing.venue,
                citing_authors_json=citing.authors_json,
                edge_meta_json=edge.edge_meta_json,
            ),
        )
        priority_score, reasons = score_queue_item(
            third_party_status=third_party_status,
            self_citation_status=self_status,
            pdf_readiness_status=pdf_readiness_status,
            venue_tier=venue_tier,
            year=citing.year or 0,
            user_review_status=review_status,
            queue_status=queue_status,
            template_matches=template_matches,
        )

        return {
            "scholar_session_id": edge.scholar_session_id,
            "citation_edge_id": edge.id,
            "cited_publication_id": cited.id,
            "citing_publication_id": citing.id,
            "queue_status": queue_status,
            "priority_score": priority_score,
            "priority_reasons_json": json.dumps(reasons),
            "third_party_status": third_party_status,
            "self_citation_status": self_status,
            "pdf_readiness_status": pdf_readiness_status,
            "pdf_asset_id": pdf_asset.id if pdf_asset else None,
            "venue": citing.venue,
            "venue_tier": venue_tier,
            "citing_paper_title": citing.title,
            "cited_paper_title": cited.title,
            "citing_authors_json": json.dumps(citing_authors),
            "cited_authors_json": json.dumps(cited_authors),
            "year": citing.year,
            "provider_name": edge.provider_name,
            "user_review_status": review_status,
            "user_note": existing.user_note if existing else None,
        }

    def _find_or_match_pdf_asset(
        self,
        publication_id: int,
        existing: Optional[DeepAnalysisQueueItem] = None,
    ) -> Optional[PdfAsset]:
        if existing is not None and existing.pdf_asset_id is not None:
            existing_asset = self.repository.get_asset(existing.pdf_asset_id)
            if existing_asset is not None and existing_asset.source_type == "upload":
                return existing_asset
        existing = self.repository.find_asset_for_publication(publication_id)
        if existing is not None:
            return existing
        match = self.pdf_library_service.match_publication(publication_id)
        if match is None or match.pdf_asset_id is None:
            return None
        return self.repository.get_asset(match.pdf_asset_id)

    def _pdf_readiness_status(self, asset: Optional[PdfAsset]) -> str:
        if asset is None:
            return PDF_STATUS_NEED
        if asset.source_type == "upload":
            return PDF_STATUS_MANUAL
        if asset.source_type == "local_library":
            return PDF_STATUS_LOCAL_LIBRARY
        return "unavailable"

    def _readiness_for_attached_asset(self, asset: PdfAsset, *, reused: bool) -> str:
        if asset.source_type == "local_library":
            return PDF_STATUS_LOCAL_LIBRARY
        if reused:
            return PDF_STATUS_REUSED
        return PDF_STATUS_MANUAL

    def _load_authors(self, publication: Publication) -> List[str]:
        if not publication.authors_json:
            return []
        try:
            parsed = json.loads(publication.authors_json)
        except json.JSONDecodeError:
            return []
        return [str(author) for author in parsed] if isinstance(parsed, list) else []

    def _classify_self_citation(self, *, cited_authors: List[str], citing_authors: List[str]):
        if not cited_authors or not citing_authors:
            return "unknown", "ambiguous"
        cited = {self._normalize_name(author) for author in cited_authors}
        citing = {self._normalize_name(author) for author in citing_authors}
        if cited & citing:
            return "self_citation", "not_third_party"
        return "not_self_citation", "third_party"

    def _normalize_name(self, name: str) -> str:
        return " ".join((name or "").lower().split())

    def _matches_view(self, item: DeepAnalysisQueueItem, view: str) -> bool:
        if view in {"all", ""}:
            return True
        if view == "ready_only":
            return is_pdf_ready_status(item.pdf_readiness_status)
        if view == "need_pdf":
            return item.pdf_readiness_status == PDF_STATUS_NEED
        if view == "third_party_only":
            return item.third_party_status == "third_party"
        if view == "exclude_self_citation":
            return item.self_citation_status != "self_citation"
        if view == "selected":
            return item.queue_status == "selected"
        if view == "skipped":
            return item.queue_status == "skipped"
        if view == "analyzed":
            return item.queue_status == "analyzed"
        if view == "failed":
            return item.queue_status == "failed"
        if view == "important":
            return is_queue_item_important(
                item,
                self.repository.list_annotations_for_queue_item(item.id),
            )
        return True

    def _venue_sort_value(self, venue_tier: str) -> int:
        return {"A": 3, "B": 2, "C": 1}.get(venue_tier or "", 0)

    def _pdf_sort_value(self, readiness: str) -> int:
        return {
            PDF_STATUS_MANUAL: 4,
            PDF_STATUS_REUSED: 3,
            PDF_STATUS_LOCAL_LIBRARY: 2,
            PDF_STATUS_NEED: 1,
        }.get(readiness, 0)

    def _set_queue_status(self, session_id: int, item_ids: List[int], status: str) -> None:
        for item_id in item_ids:
            item = self.repository.get_queue_item(item_id)
            if item is None or item.scholar_session_id != session_id:
                continue
            item.queue_status = status
            self._rescore(item)
        self.repository.db.commit()

    def _rescore(self, item: DeepAnalysisQueueItem) -> None:
        template_matches = TemplateService(self.repository.db).preview_matches_for_text(
            item.scholar_session_id,
            self._template_match_text(
                citing_title=item.citing_paper_title,
                cited_title=item.cited_paper_title,
                venue=item.venue,
                citing_authors_json=item.citing_authors_json,
                edge_meta_json=self._edge_meta_json(item.citation_edge_id),
            ),
        )
        score, reasons = score_queue_item(
            third_party_status=item.third_party_status,
            self_citation_status=item.self_citation_status,
            pdf_readiness_status=item.pdf_readiness_status,
            venue_tier=item.venue_tier or "",
            year=item.year or 0,
            user_review_status=item.user_review_status,
            queue_status=item.queue_status,
            template_matches=template_matches,
        )
        notable_delta = 0
        for annotation in self.repository.list_annotations_for_queue_item(item.id):
            if annotation.is_important and annotation.match_status == "matched":
                reasons.append(
                    {
                        "reason": f"notable_author: {annotation.honor_category}",
                        "delta": 30,
                    }
                )
                notable_delta += 30
        item.priority_score = score + notable_delta
        item.priority_reasons_json = json.dumps(reasons)

    def _template_match_text(
        self,
        *,
        citing_title: Optional[str],
        cited_title: Optional[str],
        venue: Optional[str],
        citing_authors_json: Optional[str],
        edge_meta_json: Optional[str],
    ) -> str:
        parts = [
            citing_title or "",
            cited_title or "",
            venue or "",
            citing_authors_json or "",
        ]
        if edge_meta_json:
            try:
                edge_meta = json.loads(edge_meta_json)
            except json.JSONDecodeError:
                edge_meta = {}
            contexts = edge_meta.get("citation_contexts", [])
            if isinstance(contexts, list):
                parts.extend(str(context) for context in contexts)
            parts.append(str(edge_meta.get("target_title") or ""))
        return " ".join(parts)

    def _edge_meta_json(self, citation_edge_id: int) -> Optional[str]:
        edge = self.repository.db.get(CitationEdge, citation_edge_id)
        return edge.edge_meta_json if edge is not None else None

    def _attach_pdf_display_fields(self, item: DeepAnalysisQueueItem) -> None:
        if item.pdf_asset_id is None:
            self._auto_attach_reusable_pdf(item)
        asset = self.repository.get_asset(item.pdf_asset_id) if item.pdf_asset_id else None
        item.pdf_asset_filename = asset.original_filename if asset else None
        item.pdf_asset_source_type = self._source_label(asset, item.pdf_readiness_status) if asset else None
        item.pdf_asset_extract_status = asset.extract_status if asset else None
        publication = self.repository.get_publication(item.citing_publication_id)
        item.citing_publication_doi = publication.doi if publication else None
        item.citing_publication_openalex_id = publication.openalex_id if publication else None
        item.citing_publication_normalized_title = (
            publication.normalized_title
            if publication and publication.normalized_title
            else normalize_title_for_match(item.citing_paper_title or "")
        )
        item.reusable_pdf_candidates = [] if asset else self._reusable_pdf_candidates(item)
        self._attach_pdf_download_helper_fields(item, publication)
        annotations = self.repository.list_annotations_for_queue_item(item.id)
        item.notable_author_annotations = [
            {
                "citing_author_name": annotation.citing_author_name,
                "honor_category": annotation.honor_category,
                "match_method": annotation.match_method,
                "match_score": annotation.match_score,
                "match_status": annotation.match_status,
                "is_important": annotation.is_important,
            }
            for annotation in annotations
        ]
        matched_annotation = next(
            (annotation for annotation in annotations if annotation.match_status == "matched"),
            None,
        )
        item.venue_source_hint = (
            "CSV 导入"
            if matched_annotation
            and matched_annotation.parsed_citing_venue_short
            and item.venue == matched_annotation.parsed_citing_venue_short
            else ""
        )
        item.fulltext_result_count = self.repository.db.query(FulltextAnalysisResult).filter_by(
            queue_item_id=item.id
        ).count()
        item.strong_evidence_count = self.repository.db.query(StrongEvidence).filter_by(
            queue_item_id=item.id
        ).count()
        latest_result = (
            self.repository.db.query(FulltextAnalysisResult)
            .filter_by(queue_item_id=item.id)
            .order_by(FulltextAnalysisResult.created_at.desc(), FulltextAnalysisResult.id.desc())
            .first()
        )
        item.latest_analysis_status = latest_result.status if latest_result else "not_run"
        item.latest_analysis_scope = latest_result.analysis_scope if latest_result else None

    def _attach_pdf_download_helper_fields(
        self,
        item: DeepAnalysisQueueItem,
        publication: Optional[Publication],
    ) -> None:
        doi = publication.doi if publication and publication.doi else ""
        openalex_id = publication.openalex_id if publication and publication.openalex_id else ""
        doi_url = f"https://doi.org/{doi}" if doi else ""
        publisher = classify_publisher_from_doi_or_url(
            doi,
            item.publisher_landing_url or item.pdf_source_url,
        )
        item.doi_url = item.doi_url or doi_url
        item.publisher_landing_url = publisher.landing_url or doi_url
        item.openalex_url = item.openalex_url or openalex_id
        item.google_scholar_query_url = item.google_scholar_query_url or (
            f"https://scholar.google.com/scholar?q={quote_plus(item.citing_paper_title or '')}"
        )
        item.publisher_name = (
            publisher.publisher
            if publisher.publisher != "Publisher"
            else item.publisher_name or self._publisher_name(publication, item)
        )
        item.publisher_access_hint = publisher.access_hint
        item.ieee_downloader_available = bool(
            publisher.source == "ieee_xplore" and settings.ieee_downloader_command
        )
        item.ieee_downloader_portal_url = settings.ieee_downloader_portal_url
        item.ieee_download_task = self._latest_ieee_download_task(item)
        candidates = self._pdf_download_candidates(item, publication)
        item.pdf_download_candidates = candidates
        item.pdf_direct_download_available = any(
            candidate["can_auto_download"] and candidate["url_type"] == "direct_pdf"
            for candidate in candidates
        )
        requires_login_count = sum(1 for candidate in candidates if candidate["access_status"] == "requires_login")
        item.pdf_discovery_diagnostics = {
            "tried_sources": [candidate["source_name"] for candidate in candidates],
            "found_candidates_count": len(candidates),
            "requires_login_count": requires_login_count,
            "no_pdf_found_reason": "no_open_access_pdf_found" if not any(candidate["can_auto_download"] for candidate in candidates) else "",
        }
        if item.pdf_discovery_status == "requires_login":
            item.pdf_access_status = "requires_login"
            item.requires_login_reason = (
                item.requires_login_reason or "publisher_or_institution_login_required"
            )
        elif item.pdf_asset_id:
            item.pdf_access_status = "matched_from_inbox" if item.pdf_source == "manual_download_inbox" else "open_access_downloaded"
        elif not item.pdf_access_status:
            item.pdf_access_status = "manual_download_needed"

    def _latest_ieee_download_task(self, item: DeepAnalysisQueueItem) -> Optional[dict]:
        tasks = (
            self.repository.db.query(AnalysisTask)
            .filter_by(
                session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
                session_id=item.scholar_session_id,
                task_type="download_ieee_pdf",
            )
            .order_by(AnalysisTask.created_at.desc(), AnalysisTask.id.desc())
            .limit(20)
            .all()
        )
        for task in tasks:
            try:
                payload = json.loads(task.payload_json or "{}")
            except json.JSONDecodeError:
                continue
            if int(payload.get("queue_item_id") or 0) == item.id:
                return {
                    "id": task.id,
                    "status": task.status,
                    "stage_message": task.stage_message or "",
                    "error_message": task.error_message or "",
                }
        return None

    def _publisher_name(
        self,
        publication: Optional[Publication],
        item: DeepAnalysisQueueItem,
    ) -> str:
        combined = " ".join(
            [
                publication.doi if publication and publication.doi else "",
                publication.venue if publication and publication.venue else "",
                item.pdf_source_url or "",
                item.provider_name or "",
            ]
        ).lower()
        if "10.1145" in combined or "acm" in combined:
            return "ACM"
        if "10.1109" in combined or "ieee" in combined:
            return "IEEE"
        if "springer" in combined:
            return "Springer"
        if "elsevier" in combined:
            return "Elsevier"
        return ""

    def _pdf_download_candidates(
        self,
        item: DeepAnalysisQueueItem,
        publication: Optional[Publication],
    ) -> List[dict]:
        candidates = []
        seen = set()
        for candidate in PdfDiscoveryService(self.repository.db).discover_pdf_candidates_for_queue_item(item.id):
            payload = {
                "source": candidate.source,
                "source_name": candidate.source_name or self._source_name_for_url(candidate.url, candidate.source),
                "display_label": candidate.display_label or candidate.source_name or self._source_name_for_url(candidate.url, candidate.source),
                "url": candidate.url,
                "access_status": "requires_login" if candidate.requires_login else (candidate.access_status or ("open_access" if candidate.is_open_access else "unknown")),
                "can_auto_download": bool(
                    candidate.can_auto_download
                    and candidate.url_type == "direct_pdf"
                    and candidate.is_open_access
                    and not candidate.requires_login
                ),
                "url_type": candidate.url_type,
                "reason": candidate.reason,
                "user_action_hint": candidate.user_action_hint,
            }
            self._append_candidate(candidates, seen, payload)

        doi = publication.doi if publication and publication.doi else ""
        if doi:
            self._append_candidate(
                candidates,
                seen,
                {
                    "source": "doi",
                    "source_name": "DOI",
                    "display_label": "DOI",
                    "url": f"https://doi.org/{doi}",
                    "access_status": "unknown",
                    "can_auto_download": False,
                    "url_type": "landing_page",
                    "reason": "doi_fallback",
                    "user_action_hint": "通过 DOI 打开论文官方落地页",
                },
            )
        if item.pdf_source_url and item.pdf_source_url != item.publisher_landing_url:
            source_url_type = PdfDiscoveryService(self.repository.db).classify_url_type(item.pdf_source_url)
            self._append_candidate(
                candidates,
                seen,
                {
                    "source": item.pdf_source or "unknown",
                    "source_name": self._source_name_for_url(item.pdf_source_url, item.pdf_source or "Metadata"),
                    "display_label": self._source_name_for_url(item.pdf_source_url, item.pdf_source or "Metadata"),
                    "url": item.pdf_source_url,
                    "access_status": "unknown" if source_url_type == "metadata_page" else item.pdf_access_status or "unknown",
                    "can_auto_download": False,
                    "url_type": source_url_type,
                    "reason": "metadata_page_not_direct_pdf" if source_url_type == "metadata_page" else item.requires_login_reason or "source_page",
                    "user_action_hint": (
                        "OpenAlex 是元数据来源，不是出版社下载入口"
                        if "openalex.org" in item.pdf_source_url.lower()
                        else "该链接仅提供元数据，请使用出版社或 DOI 页面"
                    ) if source_url_type == "metadata_page" else "请在页面确认 PDF 访问方式",
                },
            )
        if item.openalex_url:
            self._append_candidate(
                candidates,
                seen,
                {
                    "source": "openalex",
                    "source_name": "OpenAlex OA",
                    "display_label": "OpenAlex",
                    "url": item.openalex_url,
                    "access_status": "unknown",
                    "can_auto_download": False,
                    "url_type": "metadata_page",
                    "reason": "metadata_page",
                    "user_action_hint": "OpenAlex 是元数据来源，不是出版社下载入口",
                },
            )
        self._append_candidate(
            candidates,
            seen,
            {
                "source": "search",
                "source_name": "Google Scholar",
                "display_label": "Google Scholar",
                "url": item.google_scholar_query_url,
                "access_status": "search_only",
                "can_auto_download": False,
                "url_type": "metadata_page",
                "reason": "search_fallback",
                "user_action_hint": "搜索论文的可用版本",
            },
        )
        return sorted(
            candidates,
            key=lambda candidate: (
                0 if candidate["can_auto_download"] and candidate["url_type"] == "direct_pdf"
                else 1 if candidate["url_type"] == "landing_page"
                else 2,
                candidate["display_label"],
            ),
        )

    def _append_candidate(self, candidates: List[dict], seen: set, payload: dict) -> None:
        url = payload.get("url") or ""
        key = (url, payload.get("source") or payload.get("source_name") or "")
        if not url or key in seen:
            return
        seen.add(key)
        candidates.append(payload)

    def _source_name_for_url(self, url: str, fallback: str) -> str:
        value = (url or "").lower()
        if "dl.acm.org" in value or "10.1145" in value:
            return "ACM Digital Library"
        if "ieeexplore.ieee.org" in value or "10.1109" in value:
            return "IEEE Xplore"
        if "arxiv.org" in value:
            return "arXiv"
        if "semanticscholar.org" in value:
            return "Semantic Scholar"
        if "openalex.org" in value:
            return "OpenAlex OA"
        if "doi.org" in value:
            return "DOI"
        return fallback or "Unknown"

    def _auto_attach_reusable_pdf(self, item: DeepAnalysisQueueItem) -> bool:
        if item.pdf_asset_id is not None:
            return False
        candidates = self._reusable_pdf_candidates(item)
        best = candidates[0] if candidates else None
        if best is None or not best.get("auto_attach"):
            return False
        asset = self.repository.get_asset(best["pdf_asset_id"])
        if asset is None:
            return False
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = self._readiness_for_attached_asset(asset, reused=True)
        self._rescore(item)
        return True

    def _reusable_pdf_candidates(self, item: DeepAnalysisQueueItem) -> List[dict]:
        candidates: List[dict] = []
        seen_asset_ids = set()

        title = item.citing_paper_title or ""
        normalized_title = normalize_title_for_match(title)
        publication = self.repository.get_publication(item.citing_publication_id)
        publication_doi = (publication.doi or "").lower() if publication and publication.doi else ""
        publication_openalex_id = (
            publication.openalex_id if publication and publication.openalex_id else ""
        )
        publication_normalized_title = (
            publication.normalized_title
            if publication and publication.normalized_title
            else normalized_title
        )

        for link in self.repository.db.query(PdfAssetPublicationLink).all():
            asset = self.repository.get_asset(link.pdf_asset_id)
            if asset is None or asset.id in seen_asset_ids:
                continue
            payload = None
            if publication_doi and link.doi and link.doi.lower() == publication_doi:
                payload = self._candidate_payload(
                    asset,
                    score=1.0,
                    reason="DOI 完全一致",
                    method=link.match_method,
                    auto_attach=True,
                )
            elif publication_openalex_id and link.openalex_id == publication_openalex_id:
                payload = self._candidate_payload(
                    asset,
                    score=1.0,
                    reason="OpenAlex ID 完全一致",
                    method=link.match_method,
                    auto_attach=True,
                )
            elif link.publication_id and link.publication_id == item.citing_publication_id:
                payload = self._candidate_payload(
                    asset,
                    score=1.0,
                    reason="publication_id 完全一致",
                    method=link.match_method,
                    auto_attach=True,
                )
            elif (
                publication_normalized_title
                and link.normalized_title
                and link.normalized_title == publication_normalized_title
            ):
                payload = self._candidate_payload(
                    asset,
                    score=0.95,
                    reason="normalized title 完全一致",
                    method=link.match_method,
                    auto_attach=True,
                )
            if payload is not None:
                candidates.append(payload)
                seen_asset_ids.add(asset.id)

        for existing in self.repository.list_all_queue_items_with_pdf():
            if existing.id == item.id or not existing.pdf_asset_id:
                continue
            asset = self.repository.get_asset(existing.pdf_asset_id)
            if asset is None:
                continue
            score = title_similarity(normalized_title, existing.citing_paper_title or "")
            if score >= 0.80:
                candidates.append(
                    self._candidate_payload(
                        asset,
                        score=1.0 if score >= 0.98 else round(score, 4),
                        reason="历史队列中相同引用论文标题",
                        method="queue_title_similarity",
                        auto_attach=score >= 0.98,
                    )
                )
                seen_asset_ids.add(asset.id)

        for asset in self.repository.list_pdf_assets():
            if asset.id in seen_asset_ids:
                continue
            filename_score = title_similarity(normalized_title, asset.original_filename or "")
            if filename_score >= 0.80:
                candidates.append(
                    self._candidate_payload(
                        asset,
                        score=round(filename_score, 4),
                        reason="上传文件名与引用论文标题相似",
                        method="filename_title_similarity",
                        auto_attach=False,
                    )
                )
                seen_asset_ids.add(asset.id)

        library_match = self.pdf_library_service.match_publication(item.citing_publication_id)
        if library_match is not None and library_match.pdf_asset_id is not None:
            asset = self.repository.get_asset(library_match.pdf_asset_id)
            if asset is not None and asset.id not in seen_asset_ids:
                candidates.append(
                    self._candidate_payload(
                        asset,
                        score=library_match.match_score,
                        reason=f"本地 PDF 库匹配：{library_match.match_reason}",
                        method=f"local_library_{library_match.match_reason}",
                        auto_attach=library_match.match_score >= 0.95,
                    )
                )

        return sorted(candidates, key=lambda candidate: candidate["match_score"], reverse=True)[:3]

    def _candidate_payload(
        self,
        asset: PdfAsset,
        *,
        score: float,
        reason: str,
        method: str,
        auto_attach: bool,
    ) -> dict:
        return {
            "pdf_asset_id": asset.id,
            "original_filename": asset.original_filename or f"pdf_asset_{asset.id}.pdf",
            "match_reason": reason,
            "match_method": method,
            "match_score": score,
            "source_type": self._source_label(asset, "reused_pdf"),
            "extract_status": asset.extract_status,
            "auto_attach": auto_attach,
        }

    def _source_label(self, asset: Optional[PdfAsset], readiness: Optional[str]) -> str:
        if asset is None:
            return ""
        if readiness == PDF_STATUS_REUSED:
            return "已上传复用"
        if asset.source_type == "local_library":
            return "本地库匹配"
        if asset.source_type == "upload":
            return "新上传"
        return asset.source_type or "未知"

    def _create_pdf_publication_link(
        self,
        *,
        asset: PdfAsset,
        publication: Optional[Publication],
        raw_title: str,
        match_method: str,
        match_score: float,
        is_verified: bool,
    ) -> None:
        PdfRepository(self.repository.db).create_or_update_asset_publication_link(
            pdf_asset=asset,
            publication=publication,
            raw_title=raw_title,
            match_method=match_method,
            match_score=match_score,
            is_verified=is_verified,
        )


def get_scholar_queue_service(db: Session = Depends(get_db)) -> ScholarQueueService:
    pdf_library_service = PdfLibraryService(
        repository=PdfRepository(db),
        library_dirs=parse_library_dirs(settings.pdf_library_dirs),
        index_path=settings.pdf_index_path,
        max_scan_files=settings.pdf_max_scan_files,
        match_threshold=settings.pdf_match_threshold,
    )
    return ScholarQueueService(
        repository=ScholarQueueRepository(db),
        pdf_library_service=pdf_library_service,
    )
