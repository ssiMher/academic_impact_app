"""Repository for PDF assets and citing paper PDF links."""

import json
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    CitingPaper,
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    PdfAsset,
    PdfAssetPublicationLink,
    PdfLibraryEntry,
    PdfLibraryIndex,
    Publication,
    ScholarPublication,
    StrongEvidence,
)


class PdfRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_citing_paper(self, citing_paper_id: int) -> Optional[CitingPaper]:
        return self.db.get(CitingPaper, citing_paper_id)

    def get_pdf_asset(self, pdf_asset_id: int) -> Optional[PdfAsset]:
        return self.db.get(PdfAsset, pdf_asset_id)

    def get_publication(self, publication_id: int) -> Optional[Publication]:
        return self.db.get(Publication, publication_id)

    def create_asset(
        self,
        *,
        storage_path: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        source_type: str,
        extract_status: str,
        source_url: Optional[str] = None,
        license: Optional[str] = None,
        downloaded_at=None,
    ) -> PdfAsset:
        asset = PdfAsset(
            storage_path=storage_path,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            source_type=source_type,
            source_url=source_url,
            license=license,
            downloaded_at=downloaded_at,
            extract_status=extract_status,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def create_asset_if_missing_by_sha256(
        self,
        *,
        storage_path: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        source_type: str,
        extract_status: str,
        source_url: Optional[str] = None,
        license: Optional[str] = None,
        downloaded_at=None,
    ) -> PdfAsset:
        existing = self.find_asset_by_sha256(sha256)
        if existing is not None:
            return existing
        return self.create_asset(
            storage_path=storage_path,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            source_type=source_type,
            extract_status=extract_status,
            source_url=source_url,
            license=license,
            downloaded_at=downloaded_at,
        )

    def attach_asset_to_citing_paper(
        self,
        *,
        citing_paper: CitingPaper,
        asset: PdfAsset,
    ) -> CitingPaper:
        citing_paper.pdf_asset_id = asset.id
        self.db.commit()
        self.db.refresh(citing_paper)
        return citing_paper

    def attach_asset_to_scholar_publication(
        self,
        *,
        scholar_publication: ScholarPublication,
        asset: PdfAsset,
    ) -> ScholarPublication:
        scholar_publication.pdf_asset_id = asset.id
        self.db.commit()
        self.db.refresh(scholar_publication)
        return scholar_publication

    def mark_extract_succeeded(self, asset: PdfAsset, extracted_text_path: str) -> PdfAsset:
        asset.extract_status = "succeeded"
        asset.extracted_text_path = extracted_text_path
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def mark_extract_failed(self, asset: PdfAsset) -> PdfAsset:
        asset.extract_status = "failed"
        asset.extracted_text_path = None
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def get_strong_evidence_for_citing_paper(self, citing_paper_id: int) -> List[dict]:
        statement = (
            select(StrongEvidence, FulltextAnalysisResult.parsed_result_json)
            .join(
                FulltextAnalysisResult,
                StrongEvidence.fulltext_result_id == FulltextAnalysisResult.id,
            )
            .where(FulltextAnalysisResult.citing_paper_id == citing_paper_id)
            .order_by(StrongEvidence.score.desc(), StrongEvidence.id.asc())
        )
        evidence_items = []
        for evidence, parsed_result_json in self.db.execute(statement):
            reason = ""
            if parsed_result_json:
                parsed_result = json.loads(parsed_result_json)
                for finding in parsed_result.get("findings", []):
                    if finding.get("citation_text") == evidence.citation_text:
                        reason = finding.get("reasoning", "")
                        break
            evidence_items.append(
                {
                    "id": evidence.id,
                    "citation_text": evidence.citation_text,
                    "aspect": evidence.aspect,
                    "stance": evidence.stance,
                    "mention_type": evidence.mention_type,
                    "highlight_keywords_json": evidence.highlight_keywords_json,
                    "score": evidence.score,
                    "evidence_strength": evidence.evidence_strength,
                    "reason": reason,
                }
            )
        return evidence_items

    def create_library_index(
        self,
        *,
        index_path: str,
        source_dirs_json: str,
        status: str,
        started_at,
    ) -> PdfLibraryIndex:
        index = PdfLibraryIndex(
            index_path=index_path,
            source_dirs_json=source_dirs_json,
            status=status,
            entry_count=0,
            started_at=started_at,
        )
        self.db.add(index)
        self.db.commit()
        self.db.refresh(index)
        return index

    def mark_library_index_succeeded(
        self,
        *,
        index: PdfLibraryIndex,
        entry_count: int,
        finished_at,
    ) -> PdfLibraryIndex:
        index.status = "succeeded"
        index.entry_count = entry_count
        index.finished_at = finished_at
        index.error_message = None
        self.db.commit()
        self.db.refresh(index)
        return index

    def mark_library_index_failed(
        self,
        *,
        index: PdfLibraryIndex,
        error_message: str,
        finished_at,
    ) -> PdfLibraryIndex:
        index.status = "failed"
        index.error_message = error_message
        index.finished_at = finished_at
        self.db.commit()
        self.db.refresh(index)
        return index

    def create_library_entry(
        self,
        *,
        index_id: int,
        file_path: str,
        filename: str,
        size_bytes: int,
        sha256: str,
        detected_doi: Optional[str],
        detected_arxiv_id: Optional[str],
        normalized_title: str,
        title_candidates_json: str,
    ) -> PdfLibraryEntry:
        entry = PdfLibraryEntry(
            index_id=index_id,
            file_path=file_path,
            filename=filename,
            size_bytes=size_bytes,
            sha256=sha256,
            detected_doi=detected_doi,
            detected_arxiv_id=detected_arxiv_id,
            normalized_title=normalized_title,
            title_candidates_json=title_candidates_json,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def get_latest_successful_library_index(self) -> Optional[PdfLibraryIndex]:
        statement = (
            select(PdfLibraryIndex)
            .where(PdfLibraryIndex.status == "succeeded")
            .order_by(PdfLibraryIndex.finished_at.desc(), PdfLibraryIndex.id.desc())
            .limit(1)
        )
        return self.db.scalars(statement).first()

    def list_library_entries(self, index_id: int) -> List[PdfLibraryEntry]:
        statement = (
            select(PdfLibraryEntry)
            .where(PdfLibraryEntry.index_id == index_id)
            .order_by(PdfLibraryEntry.id.asc())
        )
        return list(self.db.scalars(statement))

    def delete_library_entries_except_index(self, index_id: int) -> None:
        self.db.execute(
            delete(PdfLibraryEntry).where(PdfLibraryEntry.index_id != index_id)
        )
        self.db.commit()

    def find_asset_by_sha256(self, sha256: str) -> Optional[PdfAsset]:
        statement = select(PdfAsset).where(PdfAsset.sha256 == sha256)
        return self.db.scalars(statement).first()

    def create_or_update_asset_publication_link(
        self,
        *,
        pdf_asset: PdfAsset,
        publication: Optional[Publication],
        raw_title: Optional[str],
        match_method: str,
        match_score: float,
        is_verified: bool,
    ) -> PdfAssetPublicationLink:
        doi = publication.doi if publication else None
        openalex_id = publication.openalex_id if publication else None
        normalized_title = publication.normalized_title if publication else None
        if not normalized_title and raw_title:
            from app.pdf.match import normalize_title_for_match

            normalized_title = normalize_title_for_match(raw_title)
        statement = select(PdfAssetPublicationLink).where(
            PdfAssetPublicationLink.pdf_asset_id == pdf_asset.id,
            PdfAssetPublicationLink.publication_id == (publication.id if publication else None),
            PdfAssetPublicationLink.normalized_title == normalized_title,
        )
        link = self.db.scalars(statement).first()
        if link is None:
            link = PdfAssetPublicationLink(
                pdf_asset_id=pdf_asset.id,
                publication_id=publication.id if publication else None,
                doi=doi,
                openalex_id=openalex_id,
                normalized_title=normalized_title,
                raw_title=raw_title or (publication.title if publication else None),
                match_method=match_method,
                match_score=match_score,
                is_verified=is_verified,
            )
            self.db.add(link)
            self.db.flush()
            return link

        link.doi = link.doi or doi
        link.openalex_id = link.openalex_id or openalex_id
        link.raw_title = link.raw_title or raw_title
        link.match_method = match_method
        link.match_score = max(float(link.match_score or 0.0), float(match_score))
        link.is_verified = bool(link.is_verified or is_verified)
        self.db.flush()
        return link

    def list_asset_publication_links(self) -> List[PdfAssetPublicationLink]:
        return list(self.db.scalars(select(PdfAssetPublicationLink)))

    def list_pdf_assets(self) -> List[PdfAsset]:
        statement = select(PdfAsset).order_by(PdfAsset.id.desc())
        return list(self.db.scalars(statement))

    def asset_pool_summary(self) -> dict:
        assets = self.list_pdf_assets()
        links = self.list_asset_publication_links()
        usage_rows = self.db.execute(
            select(DeepAnalysisQueueItem.pdf_asset_id, func.count(DeepAnalysisQueueItem.id))
            .where(DeepAnalysisQueueItem.pdf_asset_id.is_not(None))
            .group_by(DeepAnalysisQueueItem.pdf_asset_id)
        ).all()
        usage_by_asset = {asset_id: count for asset_id, count in usage_rows}
        recent = []
        for asset in assets[:10]:
            link = next((item for item in links if item.pdf_asset_id == asset.id), None)
            latest_item = (
                self.db.query(DeepAnalysisQueueItem)
                .filter_by(pdf_asset_id=asset.id)
                .order_by(DeepAnalysisQueueItem.updated_at.desc(), DeepAnalysisQueueItem.id.desc())
                .first()
            )
            recent.append(
                {
                    "id": asset.id,
                    "original_filename": asset.original_filename,
                    "source_type": asset.source_type,
                    "extract_status": asset.extract_status,
                    "doi": link.doi if link else None,
                    "openalex_id": link.openalex_id if link else None,
                    "raw_title": link.raw_title if link else None,
                    "queue_usage_count": int(usage_by_asset.get(asset.id, 0)),
                    "latest_citing_paper_title": latest_item.citing_paper_title if latest_item else "",
                }
            )
        return {
            "asset_count": len(assets),
            "extracted_count": sum(1 for asset in assets if asset.extract_status == "succeeded"),
            "linked_publication_count": len(links),
            "queue_reuse_count": sum(int(count) for count in usage_by_asset.values()),
            "recent_assets": recent,
        }

    def list_citing_papers_for_session(self, paper_session_id: int) -> List[CitingPaper]:
        statement = (
            select(CitingPaper)
            .where(CitingPaper.paper_session_id == paper_session_id)
            .order_by(CitingPaper.id.asc())
        )
        return list(self.db.scalars(statement))

    def list_scholar_publications_for_session(
        self,
        scholar_session_id: int,
    ) -> List[ScholarPublication]:
        statement = (
            select(ScholarPublication)
            .where(ScholarPublication.scholar_session_id == scholar_session_id)
            .order_by(ScholarPublication.id.asc())
        )
        return list(self.db.scalars(statement))
