"""Import external citation lists without scraping Google Scholar."""

import csv
import io
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (
    CitationEdge,
    CitingPaper,
    ExternalCitationImportBatch,
    ExternalCitationImportRow,
    PaperAnalysisSession,
    Publication,
    ScholarAnalysisSession,
    ScholarPublication,
    TargetPaper,
)
from app.repositories.scholar_session_repo import normalize_title


EXTERNAL_PROVIDER_GOOGLE = "google_scholar_import"
EXTERNAL_PROVIDER_GENERIC = "external_import"


@dataclass
class ExternalCitationRecord:
    title: str
    normalized_title: str
    authors: List[str]
    year: Optional[int]
    venue: Optional[str]
    doi: Optional[str]
    url: Optional[str]
    cited_by_url: Optional[str]
    source_provider: str
    raw_row_json: Dict[str, str]


class ExternalCitationImportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def import_csv(
        self,
        *,
        session_kind: str,
        session_id: int,
        content: bytes,
        filename: str,
        source_name: str = "external_import",
    ) -> ExternalCitationImportBatch:
        rows = self._read_csv(content)
        provider_name = self._provider_name(source_name)
        batch = ExternalCitationImportBatch(
            session_kind=session_kind,
            session_id=session_id,
            source_name=source_name,
            filename=filename,
            total_rows=len(rows),
        )
        self.db.add(batch)
        self.db.flush()
        for index, row in enumerate(rows, start=1):
            try:
                record = self._record_from_row(row, provider_name)
                if not record.title:
                    self._add_row(batch, index, row, None, "skipped", "missing_title", None, "missing title")
                    batch.skipped_count += 1
                    continue
                if session_kind == "scholar_analysis":
                    status, reason, edge_id = self._import_scholar_record(session_id, record)
                elif session_kind == "paper_analysis":
                    status, reason, edge_id = self._import_paper_record(session_id, record)
                else:
                    raise ValueError(f"Unsupported session_kind: {session_kind}")
                self._add_row(batch, index, row, record, status, reason, edge_id, None)
                if status == "imported":
                    batch.imported_count += 1
                elif status == "matched_existing":
                    batch.matched_existing_count += 1
                elif status == "duplicate":
                    batch.duplicate_count += 1
                elif status == "skipped":
                    batch.skipped_count += 1
            except Exception as exc:
                self._add_row(batch, index, row, None, "error", "exception", None, str(exc))
                batch.error_count += 1
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def rows_for_batch(self, batch_id: int) -> List[ExternalCitationImportRow]:
        return (
            self.db.query(ExternalCitationImportRow)
            .filter_by(batch_id=batch_id)
            .order_by(ExternalCitationImportRow.row_index.asc())
            .all()
        )

    def external_count_for_session(self, *, session_kind: str, session_id: int) -> int:
        if session_kind == "scholar_analysis":
            return (
                self.db.query(CitationEdge)
                .filter(
                    CitationEdge.scholar_session_id == session_id,
                    CitationEdge.provider_name.in_([EXTERNAL_PROVIDER_GOOGLE, EXTERNAL_PROVIDER_GENERIC]),
                )
                .count()
            )
        if session_kind == "paper_analysis":
            return (
                self.db.query(ExternalCitationImportRow)
                .join(ExternalCitationImportBatch, ExternalCitationImportBatch.id == ExternalCitationImportRow.batch_id)
                .filter(
                    ExternalCitationImportBatch.session_kind == session_kind,
                    ExternalCitationImportBatch.session_id == session_id,
                    ExternalCitationImportRow.match_status.in_(["imported", "matched_existing"]),
                )
                .count()
            )
        return 0

    def _import_scholar_record(self, session_id: int, record: ExternalCitationRecord) -> Tuple[str, str, Optional[int]]:
        session = self.db.get(ScholarAnalysisSession, session_id)
        if session is None:
            raise ValueError(f"ScholarAnalysisSession {session_id} was not found")
        target = self._scholar_target_publication(session_id)
        if target is None:
            return "skipped", "no_target_publication", None
        citing = self._find_or_create_publication(record)
        existing = self._find_existing_scholar_edge(session_id, target.publication_id, citing, record)
        if existing is not None:
            return "matched_existing", self._match_reason(citing, record), existing.id
        edge = CitationEdge(
            scholar_session_id=session_id,
            cited_publication_id=target.publication_id,
            citing_publication_id=citing.id,
            provider_name=record.source_provider,
            self_citation_status="unknown",
            third_party_status="third_party",
            edge_meta_json=json.dumps(
                {
                    "source": record.source_provider,
                    "source_priority": "lower_than_openalex",
                    "metadata_confidence": "imported",
                    "url": record.url,
                    "cited_by_url": record.cited_by_url,
                    "raw_row": record.raw_row_json,
                },
                ensure_ascii=False,
            ),
        )
        self.db.add(edge)
        self.db.flush()
        session.citation_edge_count = (
            self.db.query(CitationEdge).filter_by(scholar_session_id=session_id).count()
        )
        return "imported", "new_external_citation_edge", edge.id

    def _import_paper_record(self, session_id: int, record: ExternalCitationRecord) -> Tuple[str, str, Optional[int]]:
        session = self.db.get(PaperAnalysisSession, session_id)
        if session is None:
            raise ValueError(f"PaperAnalysisSession {session_id} was not found")
        self._ensure_paper_target(session)
        citing = self._find_or_create_publication(record)
        existing = (
            self.db.query(CitingPaper)
            .filter_by(paper_session_id=session_id, publication_id=citing.id)
            .first()
        )
        if existing is not None:
            return "matched_existing", self._match_reason(citing, record), None
        self.db.add(CitingPaper(paper_session_id=session_id, publication_id=citing.id))
        session.displayed_candidate_count = (session.displayed_candidate_count or 0) + 1
        self.db.flush()
        return "imported", "new_external_citing_paper", None

    def _read_csv(self, content: bytes) -> List[Dict[str, str]]:
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def _record_from_row(self, row: dict, provider_name: str) -> ExternalCitationRecord:
        title = self._field(row, "title", "Title")
        authors = self._parse_authors(self._field(row, "authors", "Authors"))
        year = self._parse_year(self._field(row, "year", "Year"))
        venue = self._field(row, "venue", "Source", "source", "Publisher")
        doi = self._normalize_doi(self._field(row, "doi", "DOI"))
        url = self._field(row, "url", "ArticleURL", "articleurl")
        cited_by_url = self._field(row, "cited_by_url", "CitesURL", "citesurl")
        return ExternalCitationRecord(
            title=title,
            normalized_title=normalize_title(title) if title else "",
            authors=authors,
            year=year,
            venue=venue or None,
            doi=doi,
            url=url or None,
            cited_by_url=cited_by_url or None,
            source_provider=provider_name,
            raw_row_json=dict(row),
        )

    def _find_or_create_publication(self, record: ExternalCitationRecord) -> Publication:
        existing = self._find_publication_by_record(record)
        if existing is not None:
            return existing
        publication = Publication(
            title=record.title,
            normalized_title=record.normalized_title,
            year=record.year,
            venue=record.venue,
            doi=record.doi,
            authors_json=json.dumps(record.authors, ensure_ascii=False),
        )
        self.db.add(publication)
        self.db.flush()
        return publication

    def _find_publication_by_record(self, record: ExternalCitationRecord) -> Optional[Publication]:
        if record.doi:
            existing = self.db.query(Publication).filter_by(doi=record.doi).first()
            if existing is not None:
                return existing
        if record.normalized_title:
            exact = self.db.query(Publication).filter_by(normalized_title=record.normalized_title).first()
            if exact is not None:
                return exact
            candidates = self.db.query(Publication).all()
            for candidate in candidates:
                score = SequenceMatcher(None, record.normalized_title, candidate.normalized_title or normalize_title(candidate.title)).ratio()
                if score >= 0.92 and (record.year is None or candidate.year is None or record.year == candidate.year):
                    return candidate
        return None

    def _find_existing_scholar_edge(
        self,
        session_id: int,
        cited_publication_id: int,
        citing: Publication,
        record: ExternalCitationRecord,
    ) -> Optional[CitationEdge]:
        existing = (
            self.db.query(CitationEdge)
            .filter_by(
                scholar_session_id=session_id,
                cited_publication_id=cited_publication_id,
                citing_publication_id=citing.id,
            )
            .first()
        )
        if existing is not None:
            return existing
        if record.doi:
            matching_publications = self.db.query(Publication).filter_by(doi=record.doi).all()
            ids = [publication.id for publication in matching_publications]
            if ids:
                return (
                    self.db.query(CitationEdge)
                    .filter(
                        CitationEdge.scholar_session_id == session_id,
                        CitationEdge.cited_publication_id == cited_publication_id,
                        CitationEdge.citing_publication_id.in_(ids),
                    )
                    .first()
                )
        return None

    def _scholar_target_publication(self, session_id: int) -> Optional[ScholarPublication]:
        return (
            self.db.query(ScholarPublication)
            .filter_by(scholar_session_id=session_id, selected_for_expansion=True)
            .order_by(ScholarPublication.id.asc())
            .first()
            or self.db.query(ScholarPublication)
            .filter_by(scholar_session_id=session_id)
            .order_by(ScholarPublication.id.asc())
            .first()
        )

    def _ensure_paper_target(self, session: PaperAnalysisSession) -> TargetPaper:
        existing = self.db.query(TargetPaper).filter_by(paper_session_id=session.id).first()
        if existing is not None:
            return existing
        publication = Publication(
            title=session.query_text,
            normalized_title=normalize_title(session.query_text),
        )
        self.db.add(publication)
        self.db.flush()
        target = TargetPaper(
            paper_session_id=session.id,
            publication_id=publication.id,
            raw_query=session.query_text,
            resolved_by_provider=False,
        )
        self.db.add(target)
        self.db.flush()
        return target

    def _add_row(
        self,
        batch: ExternalCitationImportBatch,
        row_index: int,
        raw_row: dict,
        record: Optional[ExternalCitationRecord],
        status: str,
        reason: str,
        edge_id: Optional[int],
        error: Optional[str],
    ) -> None:
        self.db.add(
            ExternalCitationImportRow(
                batch_id=batch.id,
                row_index=row_index,
                raw_row_json=json.dumps(raw_row, ensure_ascii=False),
                parsed_title=record.title if record else None,
                parsed_doi=record.doi if record else None,
                parsed_year=record.year if record else None,
                parsed_venue=record.venue if record else None,
                match_status=status,
                match_reason=reason,
                citation_edge_id=edge_id,
                error_message=error,
            )
        )

    def _provider_name(self, source_name: str) -> str:
        lowered = (source_name or "").lower()
        if "google" in lowered or "scholar" in lowered or "publish" in lowered:
            return EXTERNAL_PROVIDER_GOOGLE
        return EXTERNAL_PROVIDER_GENERIC

    def _field(self, row: dict, *names: str) -> str:
        lower_map = {str(key).strip().lower(): value for key, value in row.items()}
        for name in names:
            value = lower_map.get(name.lower())
            if value is not None:
                return str(value).strip()
        return ""

    def _parse_authors(self, value: str) -> List[str]:
        if not value:
            return []
        return [part.strip() for part in re.split(r";|\band\b|,", value) if part.strip()]

    def _parse_year(self, value: str) -> Optional[int]:
        match = re.search(r"(19|20)\d{2}", value or "")
        return int(match.group(0)) if match else None

    def _normalize_doi(self, value: str) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        lowered = raw.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if lowered.startswith(prefix):
                return raw[len(prefix):].lower()
        return raw.lower()

    def _match_reason(self, publication: Publication, record: ExternalCitationRecord) -> str:
        if record.doi and publication.doi == record.doi:
            return "doi_exact"
        if record.normalized_title and publication.normalized_title == record.normalized_title:
            return "normalized_title_exact"
        return "title_similarity"
