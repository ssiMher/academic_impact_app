"""Manual browser-download PDF inbox scanning and queue matching."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import DeepAnalysisQueueItem, PdfAsset, PdfInboxEntry, Publication
from app.models.constants import PDF_STATUS_MANUAL
from app.pdf.index import metadata_from_pdf_path
from app.pdf.match import normalize_title_for_match, title_similarity
from app.pdf.security import validate_pdf_upload
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_service import PdfService
from app.services.task_service import TaskService
from app.repositories.task_repo import TaskRepository


ACCESS_OPEN_ACCESS_DOWNLOADED = "open_access_downloaded"
ACCESS_OPEN_ACCESS_AVAILABLE = "open_access_available"
ACCESS_REQUIRES_LOGIN = "requires_login"
ACCESS_MANUAL_DOWNLOAD_NEEDED = "manual_download_needed"
ACCESS_MANUAL_DOWNLOAD_IMPORTED = "manual_download_imported"
ACCESS_MATCHED_FROM_INBOX = "matched_from_inbox"
ACCESS_NO_PDF_FOUND = "no_pdf_found"
ACCESS_FAILED = "failed"


@dataclass(frozen=True)
class InboxScanSummary:
    scanned_count: int
    created_asset_count: int
    auto_bound_count: int
    manual_confirmation_count: int
    duplicate_count: int
    failed_count: int


class PdfInboxService:
    def __init__(
        self,
        *,
        db: Session,
        inbox_dir: Path,
        pdf_service: PdfService,
        match_threshold: float,
    ) -> None:
        self.db = db
        self.inbox_dir = inbox_dir
        self.pdf_service = pdf_service
        self.match_threshold = match_threshold

    def enqueue_scan(self):
        return TaskService(TaskRepository(self.db)).enqueue(
            session_kind="system",
            session_id=0,
            task_type="scan_pdf_inbox",
        )

    def scan_inbox(self) -> InboxScanSummary:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        counts = {
            "scanned": 0,
            "created_asset": 0,
            "auto_bound": 0,
            "manual_confirmation": 0,
            "duplicate": 0,
            "failed": 0,
        }
        for path in sorted(self.inbox_dir.glob("*.pdf")):
            counts["scanned"] += 1
            try:
                created, entry = self._scan_one(path)
                if created:
                    counts["created_asset"] += 1
                else:
                    counts["duplicate"] += 1
                if entry.match_status == "matched":
                    counts["auto_bound"] += 1
                elif entry.match_status in {"candidate", "unmatched"}:
                    counts["manual_confirmation"] += 1
            except Exception:
                counts["failed"] += 1
        self.db.commit()
        return InboxScanSummary(
            scanned_count=counts["scanned"],
            created_asset_count=counts["created_asset"],
            auto_bound_count=counts["auto_bound"],
            manual_confirmation_count=counts["manual_confirmation"],
            duplicate_count=counts["duplicate"],
            failed_count=counts["failed"],
        )

    def list_entries(self) -> List[Dict[str, object]]:
        entries = (
            self.db.query(PdfInboxEntry)
            .order_by(PdfInboxEntry.created_at.desc(), PdfInboxEntry.id.desc())
            .all()
        )
        return [self._entry_view(entry) for entry in entries]

    def bind_entry_to_queue_item(self, *, entry_id: int, queue_item_id: int) -> PdfInboxEntry:
        entry = self.db.get(PdfInboxEntry, entry_id)
        item = self.db.get(DeepAnalysisQueueItem, queue_item_id)
        if entry is None or item is None or entry.pdf_asset_id is None:
            raise ValueError("Inbox entry or queue item was not found")
        item.pdf_asset_id = entry.pdf_asset_id
        item.pdf_readiness_status = PDF_STATUS_MANUAL
        item.pdf_access_status = ACCESS_MATCHED_FROM_INBOX
        item.pdf_discovery_status = "manual_download_imported"
        item.pdf_source = "manual_download_inbox"
        entry.matched_queue_item_id = item.id
        entry.match_status = "matched"
        entry.match_reason = "manual_confirmed"
        entry.match_score = max(float(entry.match_score or 0.0), 1.0)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def ignore_entry(self, entry_id: int) -> PdfInboxEntry:
        entry = self.db.get(PdfInboxEntry, entry_id)
        if entry is None:
            raise ValueError("Inbox entry was not found")
        entry.ignored = True
        entry.match_status = "ignored"
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def missing_pdfs_download_rows(self, session_id: int) -> List[Dict[str, str]]:
        rows = []
        for item in (
            self.db.query(DeepAnalysisQueueItem)
            .filter_by(scholar_session_id=session_id)
            .order_by(DeepAnalysisQueueItem.id.asc())
            .all()
        ):
            if item.pdf_asset_id:
                continue
            publication = self.db.get(Publication, item.citing_publication_id)
            links = self.download_helper_links(item, publication)
            rows.append(
                {
                    "queue_item_id": str(item.id),
                    "citing_paper_title": item.citing_paper_title or "",
                    "cited_paper_title": item.cited_paper_title or "",
                    "doi": publication.doi if publication and publication.doi else "",
                    "publisher": links.get("publisher_name") or "",
                    "year": str(item.year or ""),
                    "venue": item.venue or "",
                    "doi_url": links.get("doi_url") or "",
                    "publisher_url": links.get("publisher_landing_url") or "",
                    "google_scholar_query_url": links.get("google_scholar_query_url") or "",
                    "status": item.pdf_access_status or item.pdf_discovery_status or "",
                }
            )
        return rows

    def download_helper_links(
        self,
        item: DeepAnalysisQueueItem,
        publication: Optional[Publication] = None,
    ) -> Dict[str, str]:
        publication = publication or self.db.get(Publication, item.citing_publication_id)
        doi = publication.doi if publication and publication.doi else ""
        openalex_id = publication.openalex_id if publication and publication.openalex_id else ""
        publisher_name = self._publisher_name(publication, item)
        doi_url = f"https://doi.org/{doi}" if doi else ""
        publisher_url = item.publisher_landing_url or item.pdf_source_url or doi_url
        return {
            "doi_url": item.doi_url or doi_url,
            "publisher_landing_url": publisher_url,
            "openalex_url": item.openalex_url or openalex_id,
            "google_scholar_query_url": item.google_scholar_query_url
            or f"https://scholar.google.com/scholar?q={quote_plus(item.citing_paper_title or '')}",
            "publisher_name": item.publisher_name or publisher_name,
            "requires_login_reason": item.requires_login_reason
            or "publisher_or_institution_login_required",
        }

    def _scan_one(self, path: Path) -> tuple:
        metadata = metadata_from_pdf_path(path)
        existing_asset = self.db.query(PdfAsset).filter_by(sha256=metadata.sha256).first()
        existing_entry = self.db.query(PdfInboxEntry).filter_by(sha256=metadata.sha256).first()
        created = existing_asset is None
        asset = existing_asset or self._create_asset_from_inbox(path, metadata.sha256)
        detected_title = self._detect_title(asset, metadata.title_candidates)
        detected_doi = metadata.detected_doi or self._detect_doi(asset)
        entry = existing_entry or PdfInboxEntry(
            filename=path.name,
            file_path=str(path),
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            pdf_asset_id=asset.id,
            detected_title=detected_title,
            detected_doi=detected_doi,
            page_count=None,
            match_status="unmatched",
            match_reason="not_matched",
        )
        if existing_entry is None:
            self.db.add(entry)
            self.db.flush()
        else:
            entry.pdf_asset_id = entry.pdf_asset_id or asset.id
            entry.detected_title = entry.detected_title or detected_title
            entry.detected_doi = entry.detected_doi or detected_doi
        self._match_entry(entry)
        return created, entry

    def _create_asset_from_inbox(self, path: Path, sha256: str) -> PdfAsset:
        content = path.read_bytes()
        validate_pdf_upload(
            filename=path.name,
            content=content,
            max_size_bytes=settings.pdf_max_upload_bytes,
        )
        return self.pdf_service.store_downloaded_pdf_asset(
            filename=path.name,
            content=content,
            source_type="manual_download_inbox",
            source_url="pdf_inbox",
            license=None,
        )

    def _detect_title(self, asset: PdfAsset, title_candidates: List[str]) -> Optional[str]:
        if title_candidates:
            return title_candidates[0]
        text = self._read_extracted_text(asset)
        for line in (text or "").splitlines()[:20]:
            cleaned = " ".join(line.strip().split())
            if len(cleaned) >= 12:
                return cleaned[:300]
        return None

    def _detect_doi(self, asset: PdfAsset) -> Optional[str]:
        text = self._read_extracted_text(asset)[:5000]
        match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
        return match.group(0).rstrip(".,;)").lower() if match else None

    def _read_extracted_text(self, asset: PdfAsset) -> str:
        if not asset.extracted_text_path:
            return ""
        path = Path(asset.extracted_text_path)
        if not path.exists() or path.is_absolute() and "var" not in str(path):
            return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""

    def _match_entry(self, entry: PdfInboxEntry) -> None:
        best_item = None
        best_score = 0.0
        best_reason = "not_matched"
        normalized_detected = normalize_title_for_match(entry.detected_title or entry.filename)
        for item in self.db.query(DeepAnalysisQueueItem).all():
            publication = self.db.get(Publication, item.citing_publication_id)
            doi = (publication.doi or "").lower() if publication and publication.doi else ""
            if entry.detected_doi and doi and entry.detected_doi.lower() == doi:
                best_item, best_score, best_reason = item, 1.0, "doi_exact"
                break
            title = publication.title if publication else item.citing_paper_title
            score = title_similarity(normalized_detected, title or "")
            if score > best_score:
                best_item, best_score, best_reason = item, score, "fuzzy_title"
        entry.matched_queue_item_id = best_item.id if best_item else None
        entry.match_score = round(best_score, 4)
        entry.match_reason = best_reason
        if best_item and best_score >= 0.95:
            self._bind_asset_to_item(best_item, entry, "matched")
        elif best_item and best_score >= self.match_threshold:
            entry.match_status = "candidate"
        else:
            entry.match_status = "unmatched"

    def _bind_asset_to_item(self, item: DeepAnalysisQueueItem, entry: PdfInboxEntry, status: str) -> None:
        item.pdf_asset_id = entry.pdf_asset_id
        item.pdf_readiness_status = PDF_STATUS_MANUAL
        item.pdf_access_status = ACCESS_MATCHED_FROM_INBOX
        item.pdf_discovery_status = "manual_download_imported"
        item.pdf_source = "manual_download_inbox"
        entry.match_status = status
        entry.match_reason = entry.match_reason or "auto_bound"

    def _entry_view(self, entry: PdfInboxEntry) -> Dict[str, object]:
        candidates = []
        if entry.match_status == "candidate" and entry.matched_queue_item_id:
            item = self.db.get(DeepAnalysisQueueItem, entry.matched_queue_item_id)
            if item is not None:
                candidates.append(
                    {
                        "queue_item_id": item.id,
                        "citing_paper_title": item.citing_paper_title,
                        "cited_paper_title": item.cited_paper_title,
                        "match_score": entry.match_score,
                        "match_reason": entry.match_reason,
                    }
                )
        return {
            "id": entry.id,
            "filename": entry.filename,
            "size_bytes": entry.size_bytes,
            "detected_title": entry.detected_title,
            "detected_doi": entry.detected_doi,
            "page_count": entry.page_count,
            "match_status": entry.match_status,
            "match_reason": entry.match_reason,
            "match_score": entry.match_score,
            "matched_queue_item_id": entry.matched_queue_item_id,
            "ignored": entry.ignored,
            "candidates": candidates,
        }

    def _publisher_name(self, publication: Optional[Publication], item: DeepAnalysisQueueItem) -> str:
        combined = " ".join([
            publication.doi if publication and publication.doi else "",
            publication.venue if publication and publication.venue else "",
            item.provider_name or "",
        ]).lower()
        if "10.1145" in combined or "acm" in combined:
            return "ACM"
        if "ieee" in combined or "10.1109" in combined:
            return "IEEE"
        if "springer" in combined:
            return "Springer"
        if "elsevier" in combined:
            return "Elsevier"
        return ""


def get_pdf_inbox_service(db: Session = Depends(get_db)) -> PdfInboxService:
    return PdfInboxService(
        db=db,
        inbox_dir=Path(settings.pdf_inbox_dir),
        pdf_service=PdfService(
            repository=PdfRepository(db),
            pdf_asset_dir=Path(settings.pdf_asset_dir),
            extracted_text_dir=Path(settings.extracted_text_dir),
            max_upload_bytes=settings.pdf_max_upload_bytes,
        ),
        match_threshold=settings.pdf_inbox_match_threshold,
    )
