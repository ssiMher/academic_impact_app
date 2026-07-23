"""Build paper analysis export payloads from existing analysis results."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    CitingPaper,
    FulltextAnalysisResult,
    PaperAnalysisSession,
    Publication,
    StrongEvidence,
)
from app.repositories.report_repo import ReportRepository


class ReportNotFoundError(ValueError):
    pass


class ReportService:
    def __init__(self, db: Session) -> None:
        self.repository = ReportRepository(db)

    def build_report_markdown(self, session_id: int) -> str:
        data = self.build_structured_data(session_id)
        lines = [
            "# Academic Impact Report",
            "",
            f"Target query: {data['session']['query_text']}",
            f"Query kind: {data['session']['query_kind']}",
            f"Session status: {data['session']['status']}",
            f"Citing papers: {len(data['citing_papers'])}",
            f"Analyzed citing papers: {self._count_analyzed_citing_papers(data)}",
            f"Strong evidence: {len(data['strong_evidence'])}",
            "",
        ]

        lines.extend(self._build_citing_paper_section(data["citing_papers"]))
        lines.extend(["## Strong Evidence", ""])

        if not data["strong_evidence"]:
            lines.append("No strong evidence has been generated yet.")
            lines.append("")
            return "\n".join(lines)

        for index, evidence in enumerate(data["strong_evidence"], start=1):
            lines.extend(
                [
                    f"### Evidence {index}",
                    "",
                    f"Citing paper: {evidence['citing_paper_title']}",
                    f"Aspect: {evidence['aspect']}",
                    f"Stance: {evidence['stance']}",
                    f"Mention type: {evidence['mention_type']}",
                    f"Evidence strength: {evidence['evidence_strength']}",
                    f"Score: {self._format_score(evidence['score'])}",
                    f"Citation text: {self._single_line(evidence['citation_text'])}",
                    "Highlight keywords: "
                    + (
                        ", ".join(evidence["highlight_keywords"])
                        if evidence["highlight_keywords"]
                        else "None"
                    ),
                    f"Reason: {self._single_line(evidence['reason']) or 'Not available'}",
                    "",
                ]
            )

        return "\n".join(lines)

    def _build_citing_paper_section(
        self,
        citing_papers: List[Dict[str, Any]],
    ) -> List[str]:
        lines = ["## Citing Papers", ""]
        if not citing_papers:
            lines.extend(["No citing papers have been discovered yet.", ""])
            return lines

        for index, citing_paper in enumerate(citing_papers, start=1):
            publication = citing_paper["publication"]
            lines.extend(
                [
                    f"### Citing Paper {index}",
                    "",
                    f"Title: {publication['title']}",
                    f"Analysis status: {citing_paper['analysis_status']}",
                    f"PDF status: {citing_paper['pdf_status']}",
                    "",
                ]
            )
        return lines

    def build_structured_json(self, session_id: int) -> str:
        return json.dumps(
            self.build_structured_data(session_id),
            ensure_ascii=False,
            indent=2,
        )

    def build_structured_data(self, session_id: int) -> Dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ReportNotFoundError(f"PaperAnalysisSession {session_id} was not found")

        citing_rows = self.repository.list_citing_papers(session_id)
        result_rows = self.repository.list_fulltext_results(session_id)
        evidence_rows = self.repository.list_strong_evidence(session_id)
        result_lookup = {result.id: result for result, _citing_paper in result_rows}

        return {
            "exports": self._exports_metadata(),
            "session": self._session_to_dict(session),
            "citing_papers": [
                self._citing_paper_to_dict(citing_paper, publication)
                for citing_paper, publication in citing_rows
            ],
            "fulltext_results": [
                self._fulltext_result_to_dict(result)
                for result, _citing_paper in result_rows
            ],
            "strong_evidence": [
                self._strong_evidence_to_dict(
                    evidence=evidence,
                    fulltext_result=fulltext_result,
                    citing_paper=citing_paper,
                    publication=publication,
                    result_lookup=result_lookup,
                )
                for evidence, fulltext_result, citing_paper, publication in evidence_rows
            ],
        }

    def _session_to_dict(self, session: PaperAnalysisSession) -> Dict[str, Any]:
        return {
            "id": session.id,
            "query_text": session.query_text,
            "query_kind": session.query_kind,
            "status": session.status,
            "provider_total_citation_count": session.provider_total_citation_count,
            "displayed_candidate_count": session.displayed_candidate_count,
            "created_at": self._datetime_to_str(session.created_at),
            "updated_at": self._datetime_to_str(session.updated_at),
        }

    def _exports_metadata(self) -> Dict[str, Any]:
        return {
            "schema_version": "phase8.5",
            "generated_at": datetime.utcnow().isoformat(),
            "formats": ["report.md", "structured.json"],
        }

    def _citing_paper_to_dict(
        self,
        citing_paper: CitingPaper,
        publication: Publication,
    ) -> Dict[str, Any]:
        return {
            "id": citing_paper.id,
            "local_code": citing_paper.local_code,
            "analysis_status": citing_paper.analysis_status,
            "pdf_asset_attached": citing_paper.pdf_asset_id is not None,
            "pdf_status": "attached" if citing_paper.pdf_asset_id is not None else "need_pdf",
            "publication": self._publication_to_dict(publication),
        }

    def _publication_to_dict(self, publication: Publication) -> Dict[str, Any]:
        return {
            "id": publication.id,
            "title": publication.title,
            "year": publication.year,
            "venue": publication.venue,
            "doi": publication.doi,
            "authors": self._load_json_list(publication.authors_json),
        }

    def _fulltext_result_to_dict(
        self,
        result: FulltextAnalysisResult,
    ) -> Dict[str, Any]:
        return {
            "id": result.id,
            "citing_paper_id": result.citing_paper_id,
            "analysis_scope": result.analysis_scope,
            "status": result.status,
            "parsed_result": self._load_json_object(result.parsed_result_json),
        }

    def _strong_evidence_to_dict(
        self,
        *,
        evidence: StrongEvidence,
        fulltext_result: FulltextAnalysisResult,
        citing_paper: CitingPaper,
        publication: Publication,
        result_lookup: Dict[int, FulltextAnalysisResult],
    ) -> Dict[str, Any]:
        parsed_source = result_lookup.get(fulltext_result.id, fulltext_result)
        return {
            "id": evidence.id,
            "fulltext_result_id": evidence.fulltext_result_id,
            "citing_paper_id": citing_paper.id,
            "citing_paper_title": publication.title,
            "aspect": evidence.aspect,
            "stance": evidence.stance,
            "mention_type": evidence.mention_type,
            "citation_text": evidence.citation_text,
            "highlight_keywords": self._load_json_list(evidence.highlight_keywords_json),
            "score": evidence.score,
            "evidence_strength": evidence.evidence_strength,
            "reason": self._find_reason(parsed_source, evidence),
        }

    def _find_reason(
        self,
        result: FulltextAnalysisResult,
        evidence: StrongEvidence,
    ) -> str:
        parsed = self._load_json_object(result.parsed_result_json)
        for finding in parsed.get("findings", []):
            if not isinstance(finding, dict):
                continue
            if finding.get("citation_text") != evidence.citation_text:
                continue
            if finding.get("evidence_type") != evidence.aspect:
                continue
            if finding.get("stance") != evidence.stance:
                continue
            return str(finding.get("reasoning") or "")
        return ""

    def _count_analyzed_citing_papers(self, data: Dict[str, Any]) -> int:
        return sum(
            1
            for citing_paper in data["citing_papers"]
            if citing_paper["analysis_status"] == "analyzed"
        )

    def _load_json_object(self, value: Optional[str]) -> Dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _load_json_list(self, value: Optional[str]) -> List[Any]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _datetime_to_str(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value is not None else None

    def _format_score(self, value: Optional[float]) -> str:
        return f"{value:.2f}" if value is not None else "N/A"

    def _single_line(self, value: Optional[str]) -> str:
        return " ".join((value or "").split())


def get_report_service(db: Session = Depends(get_db)) -> ReportService:
    return ReportService(db)
