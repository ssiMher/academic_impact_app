"""Service for uploaded PDF validation, storage, and extraction."""

from pathlib import Path
from datetime import datetime
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import CitingPaper, PdfAsset
from app.pdf.extract import PdfTextExtractionError, extract_pdf_text
from app.pdf.security import validate_pdf_upload
from app.pdf.storage import save_pdf_bytes, sha256_bytes
from app.repositories.pdf_repo import PdfRepository


class CitingPaperNotFoundError(ValueError):
    pass


class PdfService:
    def __init__(
        self,
        *,
        repository: PdfRepository,
        pdf_asset_dir: Path,
        extracted_text_dir: Path,
        max_upload_bytes: int,
    ) -> None:
        self.repository = repository
        self.pdf_asset_dir = pdf_asset_dir
        self.extracted_text_dir = extracted_text_dir
        self.max_upload_bytes = max_upload_bytes

    def upload_pdf_for_citing_paper(
        self,
        *,
        citing_paper_id: int,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> PdfAsset:
        citing_paper = self.repository.get_citing_paper(citing_paper_id)
        if citing_paper is None:
            raise CitingPaperNotFoundError(f"CitingPaper {citing_paper_id} was not found")

        asset = self.upload_pdf_asset(
            filename=filename,
            content=content,
            mime_type=mime_type,
        )
        self.repository.attach_asset_to_citing_paper(
            citing_paper=citing_paper,
            asset=asset,
        )
        return asset

    def upload_pdf_asset(
        self,
        *,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> PdfAsset:
        validate_pdf_upload(
            filename=filename,
            content=content,
            max_size_bytes=self.max_upload_bytes,
        )

        storage_path = save_pdf_bytes(content, self.pdf_asset_dir)
        asset = self.repository.create_asset(
            storage_path=str(storage_path),
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=sha256_bytes(content),
            source_type="upload",
            extract_status="pending",
        )

        self.extracted_text_dir.mkdir(parents=True, exist_ok=True)
        extracted_text_path = self.extracted_text_dir / f"{asset.id}.txt"
        try:
            extract_pdf_text(storage_path, extracted_text_path)
        except PdfTextExtractionError:
            return self.repository.mark_extract_failed(asset)

        return self.repository.mark_extract_succeeded(asset, str(extracted_text_path))

    def store_downloaded_pdf_asset(
        self,
        *,
        filename: str,
        content: bytes,
        source_type: str,
        source_url: str,
        license: Optional[str] = None,
    ) -> PdfAsset:
        validate_pdf_upload(
            filename=filename,
            content=content,
            max_size_bytes=self.max_upload_bytes,
        )
        storage_path = save_pdf_bytes(content, self.pdf_asset_dir)
        asset = self.repository.create_asset_if_missing_by_sha256(
            storage_path=str(storage_path),
            original_filename=filename,
            mime_type="application/pdf",
            size_bytes=len(content),
            sha256=sha256_bytes(content),
            source_type=source_type,
            source_url=source_url,
            license=license,
            downloaded_at=datetime.utcnow(),
            extract_status="pending",
        )
        if asset.extract_status == "succeeded":
            return asset
        self.extracted_text_dir.mkdir(parents=True, exist_ok=True)
        extracted_text_path = self.extracted_text_dir / f"{asset.id}.txt"
        try:
            extract_pdf_text(Path(asset.storage_path), extracted_text_path)
        except PdfTextExtractionError:
            return self.repository.mark_extract_failed(asset)
        return self.repository.mark_extract_succeeded(asset, str(extracted_text_path))

    def get_citing_paper(self, citing_paper_id: int) -> Optional[CitingPaper]:
        return self.repository.get_citing_paper(citing_paper_id)

    def get_pdf_asset_for_citing_paper(self, citing_paper: CitingPaper) -> Optional[PdfAsset]:
        if citing_paper.pdf_asset_id is None:
            return None
        return self.repository.get_pdf_asset(citing_paper.pdf_asset_id)

    def get_strong_evidence_for_citing_paper(self, citing_paper_id: int) -> List[dict]:
        return self.repository.get_strong_evidence_for_citing_paper(citing_paper_id)

    def get_analysis_readiness(self, citing_paper: CitingPaper) -> str:
        pdf_asset = self.get_pdf_asset_for_citing_paper(citing_paper)
        if pdf_asset is None:
            return "need_pdf"
        if pdf_asset.extract_status != "succeeded" or not pdf_asset.extracted_text_path:
            return "need_extracted_text"
        return "ready"


def get_pdf_service(db: Session = Depends(get_db)) -> PdfService:
    return PdfService(
        repository=PdfRepository(db),
        pdf_asset_dir=Path(settings.pdf_asset_dir),
        extracted_text_dir=Path(settings.extracted_text_dir),
        max_upload_bytes=settings.pdf_max_upload_bytes,
    )
