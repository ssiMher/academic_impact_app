"""Import notable citation author metadata from user-provided CSV files."""

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.queue_scoring import score_queue_item
from app.models import CitationAuthorAnnotation, DeepAnalysisQueueItem, NotableAuthor
from app.pdf.match import normalize_title_for_match, title_similarity


REQUIRED_HONOR_COLUMNS = [
    "Honor/Category",
    "Citing Author",
    "Citing Author Affiliation",
    "Citing Paper Info",
    "My Cited Paper Title",
    "My Cited Paper Venue",
    "My Cited Paper Year",
]


class HonorCsvImportError(ValueError):
    pass


@dataclass
class HonorCsvImportSummary:
    total_rows: int
    matched_count: int
    ambiguous_count: int
    unmatched_count: int
    created_notable_authors: int
    important_queue_items_count: int
    no_queue_items: bool
    ambiguous_rows: List[dict]
    unmatched_rows: List[dict]


class HonorCsvImportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def import_csv(self, *, session_id: int, content: bytes) -> HonorCsvImportSummary:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if reader.fieldnames is None:
            raise HonorCsvImportError("CSV 缺少表头。")
        missing = [column for column in REQUIRED_HONOR_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise HonorCsvImportError(f"CSV 缺少必要字段: {missing}")

        rows = list(reader)
        queue_items = self._queue_items(session_id)
        no_queue_items = len(queue_items) == 0
        self.db.execute(
            delete(CitationAuthorAnnotation).where(
                CitationAuthorAnnotation.scholar_session_id == session_id
            )
        )
        self.db.flush()

        created_notable_authors = 0
        matched_count = 0
        ambiguous_count = 0
        unmatched_count = 0
        important_queue_ids = set()
        ambiguous_rows: List[dict] = []
        unmatched_rows: List[dict] = []

        for row in rows:
            notable_author, created = self._get_or_create_notable_author(row)
            if created:
                created_notable_authors += 1
            paper_info = parse_citing_paper_info(row["Citing Paper Info"])
            citing_title = paper_info["parsed_citing_paper_title"]
            cited_title = (row.get("My Cited Paper Title") or "").strip()
            matches = self._match_queue_items(queue_items, citing_title, cited_title, row["Citing Author"])
            if matches and matches[0]["score"] >= 0.90 and len(matches) == 1:
                match = matches[0]
                matched_count += 1
                important_queue_ids.add(match["item"].id)
                self._create_annotation(
                    session_id=session_id,
                    notable_author=notable_author,
                    row=row,
                    parsed_info=paper_info,
                    parsed_citing_paper_title=citing_title,
                    queue_item=match["item"],
                    match_method=match["method"],
                    match_score=match["score"],
                    match_status="matched",
                    is_important=True,
                    unmatched_reason=None,
                )
                self._backfill_citing_venue(match["item"], paper_info)
                self._mark_queue_item_important(match["item"], row["Honor/Category"])
            elif matches and matches[0]["score"] >= 0.75:
                ambiguous_count += 1
                best = matches[0]
                ambiguous_rows.append(
                    {
                        "citing_author": row["Citing Author"],
                        "honor_category": row["Honor/Category"],
                        "citing_paper_info": row["Citing Paper Info"],
                        "parsed_citing_paper_title": citing_title,
                        "parsed_citing_venue_short": paper_info["citing_venue_short"],
                        "csv_my_cited_paper_title": cited_title,
                        "suggested_queue_item_id": best["item"].id,
                        "suggested_citing_paper_title": best["item"].citing_paper_title,
                        "suggested_cited_paper_title": best["item"].cited_paper_title,
                        "match_score": best["score"],
                    }
                )
                self._create_annotation(
                    session_id=session_id,
                    notable_author=notable_author,
                    row=row,
                    parsed_info=paper_info,
                    parsed_citing_paper_title=citing_title,
                    queue_item=best["item"],
                    match_method=best["method"],
                    match_score=best["score"],
                    match_status="ambiguous",
                    is_important=False,
                    unmatched_reason="multiple_close_matches",
                )
            else:
                unmatched_count += 1
                unmatched_rows.append(
                    {
                        "citing_author": row["Citing Author"],
                        "honor_category": row["Honor/Category"],
                        "citing_paper_info": row["Citing Paper Info"],
                        "parsed_citing_paper_title": citing_title,
                        "parsed_citing_venue_short": paper_info["citing_venue_short"],
                        "csv_my_cited_paper_title": cited_title,
                        "unmatched_reason": "no_queue_items" if no_queue_items else "no_match_above_threshold",
                    }
                )
                self._create_annotation(
                    session_id=session_id,
                    notable_author=notable_author,
                    row=row,
                    parsed_info=paper_info,
                    parsed_citing_paper_title=citing_title,
                    queue_item=None,
                    match_method="unmatched",
                    match_score=0.0,
                    match_status="unmatched",
                    is_important=False,
                    unmatched_reason="no_queue_items" if no_queue_items else "no_match_above_threshold",
                )

        self.db.commit()
        return HonorCsvImportSummary(
            total_rows=len(rows),
            matched_count=matched_count,
            ambiguous_count=ambiguous_count,
            unmatched_count=unmatched_count,
            created_notable_authors=created_notable_authors,
            important_queue_items_count=len(important_queue_ids),
            no_queue_items=no_queue_items,
            ambiguous_rows=ambiguous_rows,
            unmatched_rows=unmatched_rows,
        )

    def rematch_existing_annotations(self, session_id: int) -> HonorCsvImportSummary:
        annotations = self.current_annotations(session_id)
        rows = [
            {
                "Honor/Category": annotation.honor_category,
                "Citing Author": annotation.citing_author_name,
                "Citing Author Affiliation": annotation.citing_author_affiliation or "",
                "Citing Paper Info": annotation.citing_paper_info or "",
                "My Cited Paper Title": annotation.my_cited_paper_title or "",
                "My Cited Paper Venue": "",
                "My Cited Paper Year": "",
            }
            for annotation in annotations
        ]
        if not rows:
            return HonorCsvImportSummary(
                total_rows=0,
                matched_count=0,
                ambiguous_count=0,
                unmatched_count=0,
                created_notable_authors=0,
                important_queue_items_count=0,
                no_queue_items=len(self._queue_items(session_id)) == 0,
                ambiguous_rows=[],
                unmatched_rows=[],
            )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=REQUIRED_HONOR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return self.import_csv(session_id=session_id, content=output.getvalue().encode("utf-8"))

    def current_annotations(self, session_id: int) -> List[CitationAuthorAnnotation]:
        statement = (
            select(CitationAuthorAnnotation)
            .where(CitationAuthorAnnotation.scholar_session_id == session_id)
            .order_by(CitationAuthorAnnotation.id.asc())
        )
        return list(self.db.scalars(statement))

    def _get_or_create_notable_author(self, row: Dict[str, str]):
        normalized_name = normalize_title_for_match(row["Citing Author"])
        statement = select(NotableAuthor).where(
            NotableAuthor.name == row["Citing Author"].strip(),
            NotableAuthor.fellow_status == row["Honor/Category"].strip(),
        )
        author = self.db.scalars(statement).first()
        if author is not None:
            return author, False
        author = NotableAuthor(
            name=row["Citing Author"].strip(),
            affiliation=row.get("Citing Author Affiliation", "").strip() or None,
            fellow_status=row["Honor/Category"].strip() or "unknown",
            notes=f"normalized_name={normalized_name}",
            source="honor_csv_import",
            is_manual_verified=True,
        )
        self.db.add(author)
        self.db.flush()
        return author, True

    def _queue_items(self, session_id: int) -> List[DeepAnalysisQueueItem]:
        statement = (
            select(DeepAnalysisQueueItem)
            .where(DeepAnalysisQueueItem.scholar_session_id == session_id)
            .order_by(DeepAnalysisQueueItem.id.asc())
        )
        return list(self.db.scalars(statement))

    def _match_queue_items(
        self,
        queue_items: List[DeepAnalysisQueueItem],
        citing_title: str,
        cited_title: str,
        citing_author: str,
    ) -> List[dict]:
        normalized_citing = normalize_title_for_match(citing_title)
        normalized_cited = normalize_title_for_match(cited_title)
        matches = []
        if not queue_items:
            return []
        for item in queue_items:
            citing_score = title_similarity(normalized_citing, item.citing_paper_title or "")
            cited_score = title_similarity(normalized_cited, item.cited_paper_title or "")
            author_score = 0.0
            authors = self._load_json_list(item.citing_authors_json)
            if any(normalize_title_for_match(author) == normalize_title_for_match(citing_author) for author in authors):
                author_score = 0.05
            total_score = round(min(1.0, citing_score * 0.85 + cited_score * 0.15 + author_score), 4)
            if normalize_title_for_match(item.citing_paper_title or "") == normalized_citing and normalize_title_for_match(item.cited_paper_title or "") == normalized_cited:
                total_score = 1.0
            if total_score >= 0.75:
                matches.append(
                    {
                        "item": item,
                        "score": total_score,
                        "method": "title_exact"
                        if total_score == 1.0
                        else "title_fuzzy",
                    }
                )
        matches.sort(key=lambda match: match["score"], reverse=True)
        if len(matches) > 1 and (
            abs(matches[0]["score"] - matches[1]["score"]) < 0.05
            or matches[0]["score"] < 0.95
        ):
            return matches[:2]
        return matches[:1]

    def _create_annotation(
        self,
        *,
        session_id: int,
        notable_author: NotableAuthor,
        row: Dict[str, str],
        parsed_info: Dict[str, object],
        parsed_citing_paper_title: str,
        queue_item: Optional[DeepAnalysisQueueItem],
        match_method: str,
        match_score: float,
        match_status: str,
        is_important: bool,
        unmatched_reason: Optional[str],
    ) -> None:
        annotation = CitationAuthorAnnotation(
            scholar_session_id=session_id,
            queue_item_id=queue_item.id if queue_item else None,
            citation_edge_id=queue_item.citation_edge_id if queue_item else None,
            citing_publication_id=queue_item.citing_publication_id if queue_item else None,
            notable_author_id=notable_author.id,
            citing_author_name=row["Citing Author"].strip(),
            citing_author_affiliation=row.get("Citing Author Affiliation", "").strip() or None,
            honor_category=row["Honor/Category"].strip(),
            citing_paper_info=row.get("Citing Paper Info", "").strip() or None,
            parsed_citing_paper_title=parsed_citing_paper_title or None,
            parsed_citing_venue_short=str(parsed_info.get("citing_venue_short") or "") or None,
            parsed_citing_year=parsed_info.get("citing_year"),
            parsed_citing_pub_type=str(parsed_info.get("citing_pub_type") or "") or None,
            my_cited_paper_title=row.get("My Cited Paper Title", "").strip() or None,
            matched_citing_paper_title=queue_item.citing_paper_title if queue_item else None,
            matched_cited_paper_title=queue_item.cited_paper_title if queue_item else None,
            match_method=match_method,
            match_score=match_score,
            match_status=match_status,
            unmatched_reason=unmatched_reason,
            is_important=is_important,
        )
        self.db.add(annotation)
        self.db.flush()

    def _backfill_citing_venue(self, item: DeepAnalysisQueueItem, parsed_info: Dict[str, object]) -> None:
        venue_short = str(parsed_info.get("citing_venue_short") or "").strip()
        if not venue_short:
            return
        if not item.venue or item.venue.lower() == "unknown":
            item.venue = venue_short
        publication = None
        if item.citing_publication_id:
            from app.models import Publication

            publication = self.db.get(Publication, item.citing_publication_id)
        if publication is not None and (not publication.venue or publication.venue.lower() == "unknown"):
            publication.venue = venue_short

    def _mark_queue_item_important(self, item: DeepAnalysisQueueItem, honor_category: str) -> None:
        if item.user_review_status != "rejected":
            if item.user_review_status in {None, "", "unreviewed"}:
                item.user_review_status = "important"
            reasons = self._load_priority_reasons(item.priority_reasons_json)
            if not any(reason.get("reason") == f"notable_author: {honor_category}" for reason in reasons):
                reasons.append({"reason": f"notable_author: {honor_category}", "delta": 30})
                item.priority_reasons_json = json.dumps(reasons, ensure_ascii=False)
                item.priority_score = float(item.priority_score or 0.0) + 30.0

    def _load_priority_reasons(self, value: Optional[str]) -> List[dict]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _load_json_list(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []


def extract_citing_title_from_info(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    return text.rstrip(". ").strip()


def parse_citing_paper_info(value: str) -> dict:
    raw = (value or "").strip()
    title = extract_citing_title_from_info(raw)
    prefix_match = re.match(r"^\[([^\]]+)\]\s*", raw)
    venue_short = ""
    pub_type = ""
    year = None
    if prefix_match:
        prefix = prefix_match.group(1)
        venue_match = re.match(r"^([A-Za-z][A-Za-z0-9&+\- ]*?)(?:\s*'\d{2}|\s+Inproceedings|\s+Article|\s+Proceedings|\s+Journal|$)", prefix)
        if venue_match:
            venue_short = venue_match.group(1).strip()
        year_match = re.search(r"'(\d{2})", prefix)
        if year_match:
            year = 2000 + int(year_match.group(1))
        pub_type_match = re.search(r"\b(Inproceedings|Article|Proceedings|Journal)\b", prefix, re.IGNORECASE)
        if pub_type_match:
            pub_type = pub_type_match.group(1)
    return {
        "parsed_citing_paper_title": title,
        "citing_venue_short": venue_short,
        "citing_year": year,
        "citing_pub_type": pub_type,
    }
