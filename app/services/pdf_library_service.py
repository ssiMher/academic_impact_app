"""Service for local PDF library indexing and matching."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import AnalysisTask, PdfAsset, PdfLibraryIndex, Publication
from app.pdf.arxiv import extract_arxiv_identifier
from app.pdf.extract import PdfTextExtractionError, extract_pdf_text
from app.pdf.index import metadata_from_pdf_path
from app.pdf.library import parse_library_dirs, redact_path, scan_pdf_library
from app.pdf.match import PdfLibraryMatch, normalize_title_for_match, title_similarity
from app.repositories.pdf_repo import PdfRepository
from app.repositories.task_repo import TaskRepository
from app.services.task_service import TaskService


@dataclass(frozen=True)
class MatchCandidate:
    entry_id: int
    score: float
    reason: str
    filename: str


class PdfLibraryService:
    def __init__(
        self,
        *,
        repository: PdfRepository,
        library_dirs: List[Path],
        index_path: Path,
        max_scan_files: int,
        match_threshold: float,
    ) -> None:
        self.repository = repository
        self.library_dirs = library_dirs
        self.index_path = index_path
        self.max_scan_files = max_scan_files
        self.match_threshold = match_threshold

    def get_index_status(self) -> dict:
        asset_pool = self.repository.asset_pool_summary()
        if not self.library_dirs:
            return {
                "enabled": False,
                "message": "local library disabled",
                "asset_pool": asset_pool,
                "entry_count": 0,
                "source_dirs": [],
                "source_dir_infos": [],
                "recent_error": None,
                "entries": [],
            }

        latest = self.repository.get_latest_successful_library_index()
        entries = self.repository.list_library_entries(latest.id) if latest else []
        return {
            "enabled": True,
            "message": "local library enabled",
            "asset_pool": asset_pool,
            "index": latest,
            "entry_count": latest.entry_count if latest else 0,
            "source_dirs": [redact_path(path) for path in self.library_dirs],
            "source_dir_infos": [
                {
                    "display_path": redact_path(path),
                    "is_relative": not path.is_absolute(),
                    "exists": path.exists(),
                }
                for path in self.library_dirs
            ],
            "recent_error": latest.error_message if latest else None,
            "entries": [
                {
                    "filename": entry.filename,
                    "sha256": entry.sha256,
                    "detected_doi": entry.detected_doi,
                    "detected_arxiv_id": entry.detected_arxiv_id,
                }
                for entry in entries
            ],
        }

    def rebuild_index(self, task: Optional[AnalysisTask] = None) -> PdfLibraryIndex:
        started_at = datetime.utcnow()
        source_dirs_json = json.dumps([str(path) for path in self.library_dirs])
        index = self.repository.create_library_index(
            index_path=str(self.index_path),
            source_dirs_json=source_dirs_json,
            status="running",
            started_at=started_at,
        )
        if not self.library_dirs:
            return self.repository.mark_library_index_failed(
                index=index,
                error_message="local library disabled",
                finished_at=datetime.utcnow(),
            )

        try:
            pdf_paths = scan_pdf_library(self.library_dirs, self.max_scan_files)
            if task is not None:
                task.progress_total = len(pdf_paths)
                task.progress_current = 0
                task.stage = "scanning_pdf_library"
                task.stage_message = "Scanning configured local PDF library directories."
                self.repository.db.flush()

            for scanned_count, pdf_path in enumerate(pdf_paths, start=1):
                metadata = metadata_from_pdf_path(pdf_path)
                self.repository.create_library_entry(
                    index_id=index.id,
                    file_path=str(metadata.file_path),
                    filename=metadata.filename,
                    size_bytes=metadata.size_bytes,
                    sha256=metadata.sha256,
                    detected_doi=metadata.detected_doi,
                    detected_arxiv_id=metadata.detected_arxiv_id,
                    normalized_title=metadata.normalized_title,
                    title_candidates_json=json.dumps(metadata.title_candidates),
                )
                asset = self._get_or_create_asset_for_metadata(metadata)
                publication = self._publication_for_metadata(metadata)
                if publication is not None:
                    self.repository.create_or_update_asset_publication_link(
                        pdf_asset=asset,
                        publication=publication,
                        raw_title=publication.title,
                        match_method="local_library_scan",
                        match_score=1.0,
                        is_verified=False,
                    )
                if task is not None:
                    task.progress_current = scanned_count
            self.repository.db.commit()
        except Exception as exc:
            self.repository.db.rollback()
            return self.repository.mark_library_index_failed(
                index=index,
                error_message=str(exc),
                finished_at=datetime.utcnow(),
            )

        succeeded_index = self.repository.mark_library_index_succeeded(
            index=index,
            entry_count=len(pdf_paths),
            finished_at=datetime.utcnow(),
        )
        self.repository.delete_library_entries_except_index(succeeded_index.id)
        self.repository.db.refresh(succeeded_index)
        return succeeded_index

    def match_publication(self, publication_id: int) -> Optional[PdfLibraryMatch]:
        publication = self.repository.get_publication(publication_id)
        if publication is None:
            raise ValueError(f"Publication {publication_id} was not found")

        latest = self.repository.get_latest_successful_library_index()
        if latest is None:
            return None

        entries = self.repository.list_library_entries(latest.id)
        candidate = self._best_match(publication, entries)
        if candidate is None or candidate.score < self.match_threshold:
            return None

        entry = next(entry for entry in entries if entry.id == candidate.entry_id)
        asset = self._get_or_create_asset_for_entry(entry)
        self.repository.create_or_update_asset_publication_link(
            pdf_asset=asset,
            publication=publication,
            raw_title=publication.title,
            match_method=f"local_library_{candidate.reason}",
            match_score=round(candidate.score, 4),
            is_verified=candidate.score >= 1.0,
        )
        return PdfLibraryMatch(
            entry_id=entry.id,
            pdf_asset_id=asset.id,
            match_score=round(candidate.score, 4),
            match_reason=candidate.reason,
            filename=entry.filename,
        )

    def match_session_pdfs(self, session_kind: str, session_id: int) -> int:
        matched_count = 0
        if session_kind == "paper_analysis":
            for citing_paper in self.repository.list_citing_papers_for_session(session_id):
                if citing_paper.pdf_asset_id is not None:
                    continue
                match = self.match_publication(citing_paper.publication_id)
                if match is None or match.pdf_asset_id is None:
                    continue
                asset = self.repository.get_pdf_asset(match.pdf_asset_id)
                self.repository.attach_asset_to_citing_paper(
                    citing_paper=citing_paper,
                    asset=asset,
                )
                matched_count += 1
            return matched_count

        if session_kind == "scholar_analysis":
            for scholar_publication in self.repository.list_scholar_publications_for_session(
                session_id
            ):
                if scholar_publication.pdf_asset_id is not None:
                    continue
                match = self.match_publication(scholar_publication.publication_id)
                if match is None or match.pdf_asset_id is None:
                    continue
                asset = self.repository.get_pdf_asset(match.pdf_asset_id)
                self.repository.attach_asset_to_scholar_publication(
                    scholar_publication=scholar_publication,
                    asset=asset,
                )
                matched_count += 1
            return matched_count

        raise ValueError(f"Unsupported session kind for local PDF matching: {session_kind}")

    def enqueue_pdf_library_rebuild(self) -> AnalysisTask:
        return TaskService(TaskRepository(self.repository.db)).enqueue(
            session_kind="pdf_library",
            session_id=0,
            task_type="rebuild_pdf_index",
        )

    def enqueue_match_session_pdfs(self, session_kind: str, session_id: int) -> AnalysisTask:
        return TaskService(TaskRepository(self.repository.db)).enqueue(
            session_kind=session_kind,
            session_id=session_id,
            task_type="match_session_pdfs",
        )

    def _best_match(self, publication: Publication, entries) -> Optional[MatchCandidate]:
        best: Optional[MatchCandidate] = None
        publication_doi = (publication.doi or "").lower()
        publication_arxiv_id = self._publication_arxiv_id(publication)
        publication_title = publication.normalized_title or normalize_title_for_match(
            publication.title
        )

        for entry in entries:
            if publication_doi and entry.detected_doi == publication_doi:
                return MatchCandidate(entry.id, 1.0, "doi", entry.filename)
            if publication_arxiv_id and entry.detected_arxiv_id == publication_arxiv_id:
                return MatchCandidate(entry.id, 0.98, "arxiv_id", entry.filename)

            score = title_similarity(publication_title, entry.normalized_title or "")
            if best is None or score > best.score:
                best = MatchCandidate(entry.id, score, "title", entry.filename)

        return best

    def _get_or_create_asset_for_entry(self, entry) -> PdfAsset:
        existing = self.repository.find_asset_by_sha256(entry.sha256)
        if existing is not None:
            return existing
        asset = self.repository.create_asset(
            storage_path=entry.file_path,
            original_filename=entry.filename,
            mime_type="application/pdf",
            size_bytes=entry.size_bytes,
            sha256=entry.sha256,
            source_type="local_library",
            extract_status="pending",
        )
        return self._extract_asset_text(asset, Path(entry.file_path))

    def _get_or_create_asset_for_metadata(self, metadata) -> PdfAsset:
        existing = self.repository.find_asset_by_sha256(metadata.sha256)
        if existing is not None:
            if existing.extract_status == "pending":
                return self._extract_asset_text(existing, metadata.file_path)
            return existing
        asset = self.repository.create_asset(
            storage_path=str(metadata.file_path),
            original_filename=metadata.filename,
            mime_type="application/pdf",
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            source_type="local_library",
            extract_status="pending",
        )
        return self._extract_asset_text(asset, metadata.file_path)

    def _extract_asset_text(self, asset: PdfAsset, pdf_path: Path) -> PdfAsset:
        if asset.extract_status == "succeeded" and asset.extracted_text_path:
            return asset
        extracted_text_path = Path(settings.extracted_text_dir) / f"{asset.id}.txt"
        try:
            extract_pdf_text(pdf_path, extracted_text_path)
        except PdfTextExtractionError:
            return self.repository.mark_extract_failed(asset)
        return self.repository.mark_extract_succeeded(asset, str(extracted_text_path))

    def _publication_for_metadata(self, metadata) -> Optional[Publication]:
        if metadata.detected_doi:
            from sqlalchemy import select

            publication = self.repository.db.scalars(
                select(Publication).where(Publication.doi == metadata.detected_doi)
            ).first()
            if publication is not None:
                return publication
        if metadata.normalized_title:
            from sqlalchemy import select

            return self.repository.db.scalars(
                select(Publication).where(Publication.normalized_title == metadata.normalized_title)
            ).first()
        return None

    def _publication_arxiv_id(self, publication: Publication) -> Optional[str]:
        for value in [publication.openalex_id, publication.semantic_scholar_id, publication.dblp_id]:
            identifier = extract_arxiv_identifier(value or "")
            if identifier:
                return identifier
        return None


def get_pdf_library_service(db: Session = Depends(get_db)) -> PdfLibraryService:
    return PdfLibraryService(
        repository=PdfRepository(db),
        library_dirs=parse_library_dirs(settings.pdf_library_dirs),
        index_path=Path(settings.pdf_index_path),
        max_scan_files=settings.pdf_max_scan_files,
        match_threshold=settings.pdf_match_threshold,
    )
