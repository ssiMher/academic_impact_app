"""Unified per-queue-item PDF download orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DeepAnalysisQueueItem, Publication
from app.models.constants import PDF_STATUS_REUSED
from app.pdf.publisher import classify_publisher_from_doi_or_url
from app.repositories.pdf_repo import PdfRepository
from app.services.ieee_download_service import IeeeBrowserDownloader
from app.services.pdf_discovery_service import PdfDiscoveryService
from app.services.pdf_service import PdfService


@dataclass(frozen=True)
class PdfDownloadResult:
    queue_item_id: int
    status: str
    source: str = ""
    reason: str = ""
    pdf_asset_id: Optional[int] = None


class QueuePdfDownloadService:
    def __init__(
        self,
        db: Session,
        *,
        pdf_service: Optional[PdfService] = None,
        discovery_service: Optional[PdfDiscoveryService] = None,
        ieee_downloader: Optional[IeeeBrowserDownloader] = None,
    ) -> None:
        self.db = db
        self.pdf_repository = PdfRepository(db)
        self.pdf_service = pdf_service or PdfService(
            repository=self.pdf_repository,
            pdf_asset_dir=Path(settings.pdf_asset_dir),
            extracted_text_dir=Path(settings.extracted_text_dir),
            max_upload_bytes=settings.pdf_max_upload_bytes,
        )
        self.discovery_service = discovery_service or PdfDiscoveryService(
            db,
            timeout_seconds=settings.provider_timeout_seconds,
        )
        self.ieee_downloader = ieee_downloader

    def download_pdf_for_queue_item(
        self,
        queue_item_id: int,
        *,
        allow_restricted_browser: bool = False,
        force: bool = False,
    ) -> PdfDownloadResult:
        item = self.db.get(DeepAnalysisQueueItem, queue_item_id)
        if item is None:
            return PdfDownloadResult(
                queue_item_id,
                "failed",
                reason="queue_item_not_found",
            )
        if item.pdf_asset_id and not force:
            return PdfDownloadResult(
                queue_item_id,
                "skipped_existing_pdf",
                source=item.pdf_source or "existing_pdf",
                pdf_asset_id=item.pdf_asset_id,
            )

        open_result = self.discovery_service.discover_and_download_for_queue_item(
            item_id=queue_item_id,
            pdf_service=self.pdf_service,
        )
        if open_result.get("status") == "downloaded":
            asset = open_result.get("asset")
            self._ensure_publication_link(
                item,
                asset,
                match_method="open_access_download_for_queue_item",
            )
            self.db.commit()
            return PdfDownloadResult(
                queue_item_id,
                "downloaded",
                source=getattr(asset, "source_type", "") or "open_access",
                pdf_asset_id=getattr(asset, "id", None),
            )
        if open_result.get("status") == "skipped_existing_pdf":
            return PdfDownloadResult(
                queue_item_id,
                "skipped_existing_pdf",
                source=item.pdf_source or "existing_pdf",
                pdf_asset_id=item.pdf_asset_id,
            )

        publisher = self._publisher(item)
        if allow_restricted_browser and publisher.source == "ieee_xplore":
            return self._download_ieee(item, publisher)

        status = str(open_result.get("status") or "failed")
        reason = self._open_download_reason(open_result)
        return PdfDownloadResult(
            queue_item_id,
            status,
            source=getattr(open_result.get("candidate"), "source", "") or "",
            reason=reason,
        )

    def _download_ieee(self, item, publisher) -> PdfDownloadResult:
        downloader = self.ieee_downloader or IeeeBrowserDownloader(
            command=settings.ieee_downloader_command,
            work_dir=settings.ieee_downloader_work_dir,
            download_dir=settings.ieee_downloader_download_dir,
            timeout_seconds=settings.ieee_downloader_timeout_seconds,
        )
        try:
            result = downloader.download(self._ieee_query(item))
        except Exception as exc:
            item.pdf_discovery_status = "failed"
            item.pdf_access_status = "failed"
            item.requires_login_reason = "ieee_downloader_error"
            self.db.commit()
            return PdfDownloadResult(
                item.id,
                "failed",
                source="ieee_browser_helper",
                reason=f"{type(exc).__name__}: {exc}",
            )

        if result.status == "requires_login":
            item.pdf_discovery_status = "requires_login"
            item.pdf_access_status = "requires_login"
            item.requires_login_reason = "ieee_browser_session_required"
            self.db.commit()
            return PdfDownloadResult(
                item.id,
                "requires_login",
                source="ieee_browser_helper",
                reason=result.reason or "ieee_browser_session_required",
            )
        if result.status != "downloaded" or result.pdf_path is None:
            item.pdf_discovery_status = "failed"
            item.pdf_access_status = "failed"
            item.requires_login_reason = result.reason or "ieee_download_failed"
            self.db.commit()
            return PdfDownloadResult(
                item.id,
                "failed",
                source="ieee_browser_helper",
                reason=result.reason or "ieee_download_failed",
            )

        publication = self.db.get(Publication, item.citing_publication_id)
        doi = publication.doi if publication else None
        source_url = publisher.landing_url or (
            f"https://doi.org/{doi}" if doi else ""
        )
        asset = self.pdf_service.store_downloaded_pdf_asset(
            filename=result.pdf_path.name,
            content=result.pdf_path.read_bytes(),
            source_type="ieee_browser_helper",
            source_url=source_url,
            license="institution_authorized_access",
        )
        item.pdf_asset_id = asset.id
        item.pdf_readiness_status = PDF_STATUS_REUSED
        item.pdf_discovery_status = "downloaded"
        item.pdf_access_status = "manual_download_imported"
        item.pdf_source = "ieee_browser_helper"
        item.pdf_source_url = source_url
        item.requires_login_reason = None
        self._ensure_publication_link(
            item,
            asset,
            match_method="ieee_browser_helper_for_queue_item",
        )
        self.db.commit()
        return PdfDownloadResult(
            item.id,
            "downloaded",
            source="ieee_browser_helper",
            pdf_asset_id=asset.id,
        )

    def _ensure_publication_link(self, item, asset, *, match_method: str) -> None:
        if asset is None:
            return
        publication = self.db.get(Publication, item.citing_publication_id)
        self.pdf_repository.create_or_update_asset_publication_link(
            pdf_asset=asset,
            publication=publication,
            raw_title=item.citing_paper_title,
            match_method=match_method,
            match_score=1.0,
            is_verified=True,
        )

    def _publisher(self, item):
        publication = self.db.get(Publication, item.citing_publication_id)
        return classify_publisher_from_doi_or_url(
            publication.doi if publication else None,
            item.publisher_landing_url or item.pdf_source_url,
        )

    @staticmethod
    def _ieee_query(item) -> str:
        for url in (item.publisher_landing_url, item.pdf_source_url):
            if url and "ieeexplore.ieee.org/document/" in url.lower():
                return url
        return item.citing_paper_title

    @staticmethod
    def _open_download_reason(result: dict) -> str:
        failure = result.get("failure")
        if failure is not None:
            return getattr(failure, "error_kind", "") or str(failure)
        candidate = result.get("candidate")
        if candidate is not None:
            return getattr(candidate, "reason", "") or str(result.get("status") or "")
        return str(result.get("reason") or result.get("status") or "download_failed")
